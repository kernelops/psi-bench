"""BZS-MPSI in the authors' benchmark mode (`frontend -perf -mpsi`), the mode used for the paper's numbers.

Every party generates its own random set of 2^nn elements and plants `ts` elements shared by all parties,
so the true intersection size is exactly `ts` and the Leader's printed intersection size is checked against it.
Parties are separate processes talking over real TCP sockets, here one container per party.

Sizes are given as one size per party; all must be equal and a power of two (the benchmark takes -nn).
`common` is the planted intersection size (-ts).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from .. import config
from .base import Adapter, Collected, PartyPlan, Plan, RunSpec
from .bzs import parse_log

LEADER_PIVOT_PORT = 10000
LEADER_CLIENT_BASE = 10100
PIVOT_CLIENT_BASE = 10500

_SIZE = re.compile(r"P(\d+)'s Intersection Size:\s*(\d+)")


class BzsPerfAdapter(Adapter):
    name = "bzs-perf"
    min_parties = 3
    max_parties = None

    def _nn(self, spec: RunSpec) -> int:
        s = spec.sizes[0]
        if any(x != s for x in spec.sizes) or s < 2 or s & (s - 1):
            raise ValueError("bzs-perf needs equal set sizes that are a power of two (e.g. 4096,4096,4096)")
        return int(math.log2(s))

    def plan(self, spec: RunSpec) -> Plan:
        self.validate(spec)
        nn = self._nn(spec)
        n = spec.n_parties
        pivot, leader = n - 2, n - 1
        pivot_ip, leader_ip = config.party_ip(pivot), config.party_ip(leader)
        ts = spec.common if spec.common else spec.sizes[0] // 10
        if ts > spec.sizes[0]:
            raise ValueError("planted intersection larger than the sets")
        flags: list[str] = []
        if spec.params.get("ca"):
            flags.append("-ca")
        if spec.params.get("bc"):
            flags.append("-bc")
        if spec.params.get("la"):
            flags += ["-la", str(spec.params["la"])]

        def argv(i: int) -> list[str]:
            return [config.FRONTEND_IN_IMAGE["bzs"], "-perf", "-mpsi", "-nu", str(n), "-id", str(i),
                    "-nn", str(nn), "-ts", str(ts), "-nt", str(spec.threads),
                    "-ipp", pivot_ip, "-ipl", leader_ip, *flags]

        img = config.IMAGES["bzs"]
        parties = [
            PartyPlan(i, "client", "docker", argv(i), image=img, ip=config.party_ip(i),
                      wait_for=[f"listen_p{leader}_{LEADER_CLIENT_BASE + i}", f"listen_p{pivot}_{PIVOT_CLIENT_BASE + i}"])
            for i in range(n - 2)
        ]
        parties.append(PartyPlan(pivot, "pivot", "docker", argv(pivot), image=img, ip=pivot_ip,
                                 announce=[PIVOT_CLIENT_BASE + i for i in range(n - 2)]))
        parties.append(PartyPlan(leader, "leader", "docker", argv(leader), image=img, ip=leader_ip,
                                 announce=[LEADER_PIVOT_PORT] + [LEADER_CLIENT_BASE + i for i in range(n - 2)]))
        return Plan(parties=parties, checkable=True)

    def collect(self, spec: RunSpec, plan: Plan, run_dir: Path, metrics: dict[int, dict]) -> Collected:
        c = Collected()
        leader = spec.n_parties - 1
        ts = spec.common if spec.common else spec.sizes[0] // 10
        got = None
        for p in plan.parties:
            log = run_dir / f"party_{p.idx}" / "stdout.log"
            text = log.read_text(errors="replace") if log.exists() else ""
            c.party_reported[p.idx] = parse_log(text)
            m = _SIZE.search(text)
            if m and int(m.group(1)) == leader:
                got = int(m.group(2))
        c.reported = {"mode": "benchmark (-perf)", "leader": leader, "pivot": leader - 1, "planted_intersection": ts,
                      "reported_intersection": got}
        c.check = {"correct": got == ts, "reported_cardinality": got, "true_cardinality": ts}
        # protocol-reported communication of the last three parties (MB), for cross-checking the wire counters
        mb = [d.get("comm_mb_reported") for d in c.party_reported.values() if d.get("comm_mb_reported") is not None]
        if mb:
            c.reported["comm_mb_reported_sum_last3"] = round(sum(mb), 6)
        return c
