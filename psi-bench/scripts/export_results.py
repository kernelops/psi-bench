#!/usr/bin/env python3
"""Write the recorded suite results to psi-bench/results/ so they can be committed and cited.

Produces, for every suite in the history database:
  results/<suite>.md        comparison table (median, 95% CI over repetitions)
  results/<suite>.tex       the same as a booktabs table
and, once:
  results/runs_suites.csv   every individual suite run (warm-up runs included and flagged)
  results/environment.json  hardware/software snapshot of the machine the runs were recorded on
  results/CONDITIONS.md     what the machine was doing while measuring (load, governor, other containers)

Usage:  scripts/export_results.py [--out results]
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))

from psibench import config, db, report  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "results"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    with db.connect() as conn:
        suites = [r["suite"] for r in conn.execute("SELECT DISTINCT suite FROM runs WHERE suite IS NOT NULL ORDER BY suite")]
        if not suites:
            print("no suite runs recorded yet; run ./psibench suite suites/<file>.json first", file=sys.stderr)
            return 1
        for s in suites:
            rows = report.collect(conn, s)
            (out / f"{s}.md").write_text(f"# {s}\n\n" + report.markdown(rows))
            (out / f"{s}.tex").write_text(report.latex(rows))
            print(f"{s}: {len(rows)} experiments")

        # every individual suite run
        runs = conn.execute("SELECT * FROM runs WHERE suite IS NOT NULL ORDER BY id").fetchall()
        skip = {"host_state", "reported", "check_detail", "netem", "dataset", "run_dir"}
        cols = [c for c in runs[0].keys() if c not in skip]
        with open(out / "runs_suites.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in runs:
                w.writerow([r[c] for c in cols])
        print(f"runs_suites.csv: {len(runs)} runs")

        # environment: all snapshots used by the suite runs (normally exactly one)
        env_ids = sorted({r["env_id"] for r in runs})
        envs = [conn.execute("SELECT hash, created_at, snapshot FROM environments WHERE id=?", (i,)).fetchone() for i in env_ids]
        (out / "environment.json").write_text(json.dumps(
            [{"hash": e["hash"], "recorded": e["created_at"], **json.loads(e["snapshot"])} for e in envs], indent=2))

        # conditions while measuring
        loads, containers, governors, freq = [], [], set(), []
        for r in runs:
            hs = json.loads(r["host_state"] or "{}")
            if hs.get("loadavg"):
                loads.append(hs["loadavg"][0])
            if "running_containers" in hs:
                containers.append(hs["running_containers"])
            if hs.get("governor"):
                governors.add(hs["governor"])
            freq += list((hs.get("cur_mhz") or {}).values())
        lines = [
            "# Measurement conditions",
            "",
            f"Recorded for {len(runs)} suite runs (including warm-ups). Values are read at the start of each run.",
            "",
            f"- 1-minute load average at run start: median {statistics.median(loads):.1f}, min {min(loads):.1f}, max {max(loads):.1f}",
            f"- other Docker containers running at run start: min {min(containers)}, max {max(containers)}",
            f"- CPU frequency governor: {', '.join(sorted(governors))}",
            f"- instantaneous frequency of the pinned P-cores: min {min(freq)} MHz, max {max(freq)} MHz" if freq else "",
            "",
            "The load average includes the benchmark runs that came just before (a 6-thread PEPSI run alone adds about 6),",
            "so it overstates outside load. The outside factor is the other running containers (here an unrelated",
            "Airflow stack) plus the `powersave` governor, which lets the core frequency swing widely. The machine was",
            "therefore not quiet: timings are indicative and absolute numbers will differ on an idle machine.",
            "To replace them, stop other workloads, set the governor to `performance` if possible, and re-run a suite",
            "without `--skip-done` (the report always uses the most recent group of each experiment).",
            "",
            "Protocol builds differ in compiler (VOLE-PSI and PEPSI driver: GCC 13 on Ubuntu 24.04; BZS-MPSI: GCC 11 on",
            "Ubuntu 22.04) because the pinned dependencies require it. See environment.json.",
        ]
        (out / "CONDITIONS.md").write_text("\n".join(l for l in lines) + "\n")
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
