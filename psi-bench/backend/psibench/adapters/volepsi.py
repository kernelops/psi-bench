"""VOLE-PSI (Rindal/Rosulek, Visa Research) file-based two-party PSI.

Party `receiver` (default 0, the smaller set) learns the intersection and is the
TCP server. Both parties run in their own container on the bench network.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import config, datasets
from .base import Adapter, Collected, PartyPlan, Plan, RunSpec

PORT = 1212
_PHASE = re.compile(r"^(?P<name>[A-Za-z][^.]*?)\.\.\.\s*(?P<ms>\d+(?:\.\d+)?)\s*ms\s*$")
_SIZE = re.compile(r"intesection_size\s*=\s*(\d+)|intersection_size\s*=\s*(\d+)")


def parse_log(text: str) -> dict:
    phases: dict[str, float] = {}
    out: dict = {}
    for line in text.splitlines():
        line = line.strip()
        m = _PHASE.match(line)
        if m:
            phases[m.group("name").strip()] = float(m.group("ms"))
            continue
        s = _SIZE.search(line)
        if s:
            out["intersection_size"] = int(s.group(1) or s.group(2))
    if phases:
        out["phases_ms"] = phases
    return out


class VolePsiAdapter(Adapter):
    name = "volepsi"
    min_parties = max_parties = 2

    def plan(self, spec: RunSpec) -> Plan:
        self.validate(spec)
        recv = int(spec.params.get("receiver", 0))
        send = 1 - recv
        recv_ip = config.party_ip(recv)
        flags: list[str] = ["-v"]
        if spec.params.get("malicious"):
            flags.append("-malicious")
        if spec.params.get("okvs"):
            flags += ["-okvs", str(spec.params["okvs"])]
        if spec.params.get("ssp"):
            flags += ["-ssp", str(spec.params["ssp"])]

        def argv(i: int) -> list[str]:
            return [
                config.FRONTEND_IN_IMAGE["volepsi"], "-in", f"/data/party_{i}.csv",
                "-r", "1" if i == recv else "0", "-out", "/out/result.csv",
                "-ip", f"{recv_ip}:{PORT}", *flags,
            ]

        parties = [
            PartyPlan(recv, "receiver", "docker", argv(recv), image=config.IMAGES["volepsi"],
                      ip=recv_ip, announce=[PORT]),
            PartyPlan(send, "sender", "docker", argv(send), image=config.IMAGES["volepsi"],
                      ip=config.party_ip(send), wait_for=[f"listen_p{recv}_{PORT}"]),
        ]
        return Plan(parties=sorted(parties, key=lambda p: p.idx))

    def collect(self, spec: RunSpec, plan: Plan, run_dir: Path, metrics: dict[int, dict]) -> Collected:
        c = Collected()
        recv = int(spec.params.get("receiver", 0))
        for p in plan.parties:
            log = run_dir / f"party_{p.idx}" / "stdout.log"
            c.party_reported[p.idx] = parse_log(log.read_text(errors="replace")) if log.exists() else {}
        c.reported = {"receiver": recv}
        if spec.threads > 1:
            c.reported["note"] = "VOLE-PSI file mode is single-threaded; --threads was ignored"
        if spec.dataset_dir:
            c.check = datasets.check_result(spec.dataset_dir, run_dir / f"party_{recv}" / "result.csv")
        return c
