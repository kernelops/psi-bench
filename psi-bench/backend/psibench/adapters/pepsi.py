"""PEPSI (USENIX Security 2024), benchmark mode.

The released repo only benchmarks: it generates synthetic inputs, runs client and
server in one process and never decodes the result. This adapter therefore
cannot verify correctness (Collected.check stays None). A real end-to-end driver
is planned for Phase 3.

Native (no container): SEAL/OpenMP build in pepsi/build. `omp_set_num_threads(32)`
is hardcoded in the repo; OMP_THREAD_LIMIT caps it to --threads.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .. import config
from .base import Adapter, Collected, PartyPlan, Plan, RunSpec

ONLINE_KEYS = ("comm_request", "comm_response")


def parse_results_csv(path: Path) -> dict:
    out: dict = {}
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if len(row) == 2:
                try:
                    out[row[0]] = int(row[1])
                except ValueError:
                    try:
                        out[row[0]] = float(row[1])
                    except ValueError:
                        out[row[0]] = row[1]
    return out


class PepsiAdapter(Adapter):
    min_parties = max_parties = 2

    def __init__(self, protocol: str = "pepsi"):
        self.name = protocol

    def plan(self, spec: RunSpec) -> Plan:
        self.validate(spec)
        binary = config.PEPSI_BUILD / config.PEPSI_BINARIES[spec.protocol]
        if not binary.exists():
            raise FileNotFoundError(f"{binary} not built (see pepsi/README.md)")
        client, server = spec.sizes
        task = str(spec.params.get("task", "PSI"))
        argv = [str(binary), "-c", str(client), "-s", str(server), "-t", task]
        if spec.params.get("label_bytes"):
            argv += ["-l", str(spec.params["label_bytes"])]
        env = {"OMP_THREAD_LIMIT": str(spec.threads), "OMP_NUM_THREADS": str(spec.threads)}
        # One process plays both roles; it is recorded as party 0.
        return Plan(parties=[PartyPlan(0, "client+server", "native", argv, env=env)], checkable=False)

    def collect(self, spec: RunSpec, plan: Plan, run_dir: Path, metrics: dict[int, dict]) -> Collected:
        c = Collected()
        pdir = run_dir / "party_0"
        files = sorted((pdir / "results").glob("*.csv")) if (pdir / "results").exists() else []
        rep: dict = parse_results_csv(files[-1]) if files else {}
        log = pdir / "stdout.log"
        if log.exists():
            m = re.search(r"Final Noise:\s*(-?\d+)", log.read_text(errors="replace"))
            if m:
                rep["final_noise_budget_bits"] = int(m.group(1))
        c.reported = {"simulated_single_process": True, "synthetic_inputs": True, **rep}
        c.party_reported[0] = rep
        comm = {k: v for k, v in rep.items() if k.startswith("comm_") and isinstance(v, int)}
        if comm:
            c.comm_total_bytes = sum(comm.values())
            c.comm_online_bytes = sum(v for k, v in comm.items() if k in ONLINE_KEYS)
        return c
