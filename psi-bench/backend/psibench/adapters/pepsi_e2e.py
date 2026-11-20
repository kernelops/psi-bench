"""PEPSI end-to-end driver (pepsi/e2e): real input files, client and server in separate containers.

Party 0 is the client (smaller set, learns the intersection), party 1 the server. The server does its
offline phase (hashing, plaintext encoding) before it starts listening; the client only starts once the
server listens, so the client's wall time is the online latency.

Parameter defaults follow the dataset: 32-bit element domains use the paper's 32-bit setting
(lambda=32, identity mapping, h=8); everything else uses the large-element setting (Lemma 1, hashed).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import config, datasets
from .base import Adapter, Collected, PartyPlan, Plan, RunSpec

PORT = 1212
_LINE = re.compile(r"^(PSI_METRICS|PSI_PARAMS) (\{.*\})\s*$")

# parameters that both sides must share (public parameters)
SHARED = ("cmax", "alpha", "lambda", "hw", "hash-index", "map", "seed")


def parse_log(text: str) -> dict:
    out: dict = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m:
            try:
                out["params" if m.group(1) == "PSI_PARAMS" else "metrics"] = json.loads(m.group(2))
            except json.JSONDecodeError:
                pass
        elif line.startswith(("ERROR:", "PROTOCOL FAILURE:")):
            out["failure_message"] = line.strip()
    return out


class PepsiE2EAdapter(Adapter):
    name = "pepsi-e2e"
    min_parties = max_parties = 2

    def _public_args(self, spec: RunSpec) -> list[str]:
        p = dict(spec.params)
        elem_bits = 128
        if spec.dataset_dir:
            elem_bits = datasets.load_meta(spec.dataset_dir).get("elem_bits", 128)
        if elem_bits <= 40:  # paper's 32-bit setting
            p.setdefault("lambda", elem_bits)
            p.setdefault("map", "identity")
        p.setdefault("cmax", max(4096, spec.sizes[0]))
        args: list[str] = ["--n", str(spec.sizes[1])]
        for k in SHARED:
            key = k.replace("-", "_")
            if key in p:
                v = p[key]
                args += [f"--{k}", str(int(v) if isinstance(v, bool) else v)]
        return args

    def plan(self, spec: RunSpec) -> Plan:
        self.validate(spec)
        if not spec.dataset_dir:
            raise ValueError("pepsi-e2e needs input files (--dataset or --sizes)")
        exe = config.PEPSI_E2E_IN_IMAGE
        img = config.IMAGES["pepsi"]
        pub = self._public_args(spec)
        server_extra: list[str] = []
        if "precompute" in spec.params:
            server_extra += ["--precompute", str(spec.params["precompute"])]
        both_extra: list[str] = []
        if "server_scale" in spec.params:
            both_extra += ["--server-scale", str(int(spec.params["server_scale"]))]
        client = [exe, "client", "--in", "/data/party_0.csv", "--out", "/out/result.csv",
                  "--host", config.party_ip(1), "--port", str(PORT), *pub, *both_extra]
        server = [exe, "server", "--in", "/data/party_1.csv", "--port", str(PORT),
                  "--threads", str(spec.threads), *pub, *both_extra, *server_extra]
        return Plan(parties=[
            PartyPlan(0, "client", "docker", client, image=img, ip=config.party_ip(0), wait_for=[f"listen_p1_{PORT}"]),
            PartyPlan(1, "server", "docker", server, image=img, ip=config.party_ip(1), announce=[PORT]),
        ])

    def collect(self, spec: RunSpec, plan: Plan, run_dir: Path, metrics: dict[int, dict]) -> Collected:
        c = Collected()
        for p in plan.parties:
            log = run_dir / f"party_{p.idx}" / "stdout.log"
            c.party_reported[p.idx] = parse_log(log.read_text(errors="replace")) if log.exists() else {}
        cm = c.party_reported[0].get("metrics", {})
        sm = c.party_reported[1].get("metrics", {})
        params = c.party_reported[1].get("params") or c.party_reported[0].get("params") or {}
        c.reported = {
            "params": params,
            "client_prep_ms": cm.get("client_prep_total_ms"),     # keygen + cuckoo + encode + encrypt (can be done in advance)
            "client_online_ms": cm.get("online_ms"),               # send + wait for answer + (not decrypt)
            "client_decode_ms": (cm.get("t_decrypt_ms") or 0) + (cm.get("t_extract_ms") or 0) if cm else None,
            "server_offline_ms": sm.get("offline_total_ms"),       # hashing + plaintext encoding
            "server_online_ms": sm.get("online_ms"),               # deserialize + compute + send (excludes waiting)
            "server_compute_ms": sm.get("t_compute_ms"),
            "hash_index": params.get("hash_index"),
            "server_scale": sm.get("server_scale"),
            "min_noise_budget_bits": cm.get("min_noise_budget_bits"),
        }
        for p in plan.parties:
            fm = c.party_reported[p.idx].get("failure_message")
            if fm:
                c.reported["failure_message"] = fm
        if cm:
            c.comm_online_bytes = (cm.get("query_bytes") or 0) + (cm.get("response_payload_bytes") or 0)
            c.reported["relin_key_bytes"] = cm.get("relin_key_bytes")
        c.check = datasets.check_result(spec.dataset_dir, run_dir / "party_0" / "result.csv")
        return c
