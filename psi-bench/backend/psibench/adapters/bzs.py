"""BZS-MPSI (CCS 2024) file-based multi-party PSI, n >= 3 parties.

Roles: parties 0..n-3 are Clients, n-2 is the Pivot, n-1 is the Leader. The
Leader writes the result. Pivot and Leader listen; Clients connect to both.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import config, datasets
from .base import Adapter, Collected, PartyPlan, Plan, RunSpec

PIVOT_BASE = 10000
LEADER_BASE = 12000

_COMM = re.compile(r"Comm:\s*([\d.]+)\s*MB")
_ROW = re.compile(r"^(?P<label>[A-Za-z][A-Za-z0-9 _-]*?)\s+(?P<t>\d+(?:\.\d+)?)\s+(?P<d>\d+(?:\.\d+)?)\s*\**\s*$")


def parse_log(text: str) -> dict:
    out: dict = {}
    phases: list[list] = []
    for line in text.splitlines():
        m = _COMM.search(line)
        if m:
            out["comm_mb_reported"] = float(m.group(1))
            continue
        r = _ROW.match(line.strip())
        if r and r.group("label") != "Label":
            phases.append([r.group("label").strip(), float(r.group("t")), float(r.group("d"))])
    if phases:
        out["phases"] = phases  # [label, cumulative_ms, delta_ms]
    out["tail"] = text.strip().splitlines()[-8:]
    return out


class BzsAdapter(Adapter):
    name = "bzs"
    min_parties = 3
    max_parties = None

    def plan(self, spec: RunSpec) -> Plan:
        self.validate(spec)
        n = spec.n_parties
        pivot, leader = n - 2, n - 1
        pivot_ip, leader_ip = config.party_ip(pivot), config.party_ip(leader)
        flags: list[str] = []
        ca = bool(spec.params.get("ca"))
        if ca:
            flags.append("-ca")
        if spec.params.get("bc"):
            flags.append("-bc")
        if spec.params.get("la"):
            flags += ["-la", str(spec.params["la"])]

        def argv(i: int) -> list[str]:
            return [
                config.FRONTEND_IN_IMAGE["bzs"], "-mpsi", "-nu", str(n), "-id", str(i),
                "-in", f"/data/party_{i}.csv", "-out", "/out/result.csv",
                "-ipp", f"{pivot_ip}:{PIVOT_BASE}", "-ipl", f"{leader_ip}:{LEADER_BASE}",
                "-nt", str(spec.threads), *flags,
            ]

        img = config.IMAGES["bzs"]
        parties: list[PartyPlan] = []
        for i in range(n - 2):
            parties.append(PartyPlan(
                i, "client", "docker", argv(i), image=img, ip=config.party_ip(i),
                wait_for=[f"listen_p{leader}_{LEADER_BASE + i}", f"listen_p{pivot}_{PIVOT_BASE + i}"],
                start_delay_ms=int(spec.params.get("client_delay_ms", 0)),
            ))
        parties.append(PartyPlan(pivot, "pivot", "docker", argv(pivot), image=img, ip=pivot_ip,
                                 announce=[PIVOT_BASE + i for i in range(n - 2)]))
        parties.append(PartyPlan(leader, "leader", "docker", argv(leader), image=img, ip=leader_ip,
                                 announce=[LEADER_BASE + i for i in range(n - 1)]))
        return Plan(parties=parties, cardinality_only=ca)

    def collect(self, spec: RunSpec, plan: Plan, run_dir: Path, metrics: dict[int, dict]) -> Collected:
        c = Collected()
        for p in plan.parties:
            log = run_dir / f"party_{p.idx}" / "stdout.log"
            c.party_reported[p.idx] = parse_log(log.read_text(errors="replace")) if log.exists() else {}
        leader = spec.n_parties - 1
        c.reported = {"leader": leader, "pivot": leader - 1}
        if spec.dataset_dir:
            c.check = datasets.check_result(spec.dataset_dir, run_dir / f"party_{leader}" / "result.csv",
                                            cardinality_only=plan.cardinality_only)
        return c
