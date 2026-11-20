"""VOLE-PSI in the authors' benchmark mode (`frontend -perf -psi`).

Both parties run in ONE process, connected by an in-memory socket; sets have equal size 2^nn and are random
(the intersection is not defined, so there is no correctness check). There is no real network, so network
profiles cannot be applied meaningfully, and CPU/memory cover both parties together. Communication is the
exact byte count the benchmark prints for each direction.

Use it to reproduce the authors' numbers; use `volepsi` (file mode, two containers) for like-for-like
comparisons with PEPSI over a real network.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from .. import config
from .base import Adapter, Collected, PartyPlan, Plan, RunSpec

_BYTES = re.compile(r"^(\d+)\s+(\d+)\s*$", re.M)
_END = re.compile(r"^end\s+([\d.]+)\s", re.M)


class VolePsiPerfAdapter(Adapter):
    name = "volepsi-perf"
    min_parties = max_parties = 2

    def _nn(self, spec: RunSpec) -> int:
        a, b = spec.sizes
        if a != b or a < 2 or a & (a - 1):
            raise ValueError("volepsi-perf needs two equal set sizes that are a power of two (e.g. 65536,65536)")
        return int(math.log2(a))

    def plan(self, spec: RunSpec) -> Plan:
        self.validate(spec)
        argv = [config.FRONTEND_IN_IMAGE["volepsi"], "-perf", "-psi", "-nn", str(self._nn(spec)), "-t", "1",
                "-nt", str(spec.threads), "-v"]
        if spec.params.get("malicious"):
            argv.append("-malicious")
        if spec.params.get("okvs"):
            argv += ["-okvs", str(spec.params["okvs"])]
        if spec.params.get("fakeBase"):
            argv.append("-fakeBase")
        return Plan(parties=[PartyPlan(0, "both parties (one process)", "docker", argv,
                                       image=config.IMAGES["volepsi"], ip=config.party_ip(0))],
                    checkable=False)

    def collect(self, spec: RunSpec, plan: Plan, run_dir: Path, metrics: dict[int, dict]) -> Collected:
        c = Collected()
        log = run_dir / "party_0" / "stdout.log"
        text = log.read_text(errors="replace") if log.exists() else ""
        rep: dict = {"mode": "benchmark (-perf), both parties in one process, in-memory socket"}
        b = _BYTES.search(text)
        if b:
            rep["bytes_receiver_to_sender"] = int(b.group(1))
            rep["bytes_sender_to_receiver"] = int(b.group(2))
            c.comm_total_bytes = int(b.group(1)) + int(b.group(2))
        e = _END.search(text)
        if e:
            rep["protocol_time_ms"] = float(e.group(1))
        if spec.network != "none":
            rep["note"] = "network profile has no effect: parties communicate in memory"
        c.reported = rep
        c.party_reported[0] = rep
        return c
