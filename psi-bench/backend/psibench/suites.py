"""Experiment suites: JSON files describing many runs, executed and recorded reproducibly.

Suite file format (see psi-bench/suites/*.json):
  {"name": "...", "description": "...",
   "defaults": {"reps": 5, "warmup": 1, "timeout": 900, "common": 100, "threads": 1, "network": "none"},
   "experiments": [
      {"protocol": "volepsi", "variant": "", "matrix": {"sizes": [[1024, 65536], [1024, 1048576]], "network": ["none", "wan"]},
       "elem_bits": 32, "params": {}}
   ]}
Every list under "matrix" is expanded as a cartesian product. Labels are generated from the fields so that
re-running a suite with --skip-done only repeats what is missing.
"""
from __future__ import annotations

import itertools
import json
import time
import uuid
from pathlib import Path

from . import config, datasets, db, runner
from .adapters import SYNTHETIC_ONLY
from .adapters.base import RunSpec

DEFAULTS = {"reps": 5, "warmup": 1, "timeout": 900, "common": 100, "threads": 1, "network": "none",
            "elem_bits": 128, "seed": 1, "params": {}, "variant": ""}


def normalize_sizes(sizes) -> list[int]:
    """[1024, 65536] stays; "65536x4" means 4 parties with 65536 elements each."""
    if isinstance(sizes, str):
        n, k = sizes.lower().split("x")
        return [int(n)] * int(k)
    return [int(s) for s in sizes]


def label_of(e: dict) -> str:
    s = e["sizes"]
    if len(s) == 2:
        sizes = f"{s[0]} vs {s[1]}"
    elif len(set(s)) == 1:
        sizes = f"{len(s)}p@{s[0]}"
    else:
        sizes = ",".join(str(x) for x in s)
    parts = [e["protocol"] + (f"[{e['variant']}]" if e.get("variant") else ""), sizes, e["network"], f"t{e['threads']}"]
    if e["elem_bits"] != 128:
        parts.append(f"{e['elem_bits']}bit")
    return " ".join(parts)


def expand(suite: dict) -> list[dict]:
    base = {**DEFAULTS, **suite.get("defaults", {})}
    out: list[dict] = []
    for exp in suite["experiments"]:
        matrix = exp.get("matrix", {})
        keys = list(matrix)
        for combo in itertools.product(*[matrix[k] for k in keys]) if keys else [()]:
            e = {**base, **{k: v for k, v in exp.items() if k != "matrix"}, **dict(zip(keys, combo))}
            e["sizes"] = normalize_sizes(e["sizes"])
            e["label"] = e.get("label") or label_of(e)
            out.append(e)
    return out


def spec_from_entry(e: dict) -> RunSpec:
    sizes = [int(s) for s in e["sizes"]]
    dataset_dir = None
    if e["protocol"] not in SYNTHETIC_ONLY:
        dataset_dir = datasets.generate(sizes, e["common"], e["seed"], elem_bits=e["elem_bits"]).resolve()
    return RunSpec(protocol=e["protocol"], sizes=sizes, common=e["common"], seed=e["seed"], dataset_dir=dataset_dir,
                   network=e["network"], threads=e["threads"], cpus=e.get("cpus"), params=dict(e.get("params", {})),
                   timeout_s=e["timeout"])


def _done(suite: str, label: str, reps: int) -> bool:
    with db.connect() as conn:
        r = conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE suite=? AND label=? AND warmup=0 AND status='ok' GROUP BY group_id "
            "ORDER BY n DESC LIMIT 1", (suite, label)).fetchone()
    return bool(r and r["n"] >= reps)


def run_suite(path: Path, only: str | None = None, skip_done: bool = False, dry_run: bool = False,
              log=print) -> dict:
    suite = json.loads(Path(path).read_text())
    name = suite["name"]
    entries = [e for e in expand(suite) if not only or only in e["label"]]
    total_runs = sum(e["reps"] + e["warmup"] for e in entries)
    log(f"suite {name}: {len(entries)} experiments, {total_runs} runs")
    if dry_run:
        for e in entries:
            log(f"  - {e['label']}  (reps={e['reps']}+{e['warmup']})")
        return {"experiments": len(entries), "runs": total_runs}
    t0 = time.time()
    summary = {"ok": 0, "failed": 0, "wrong": 0, "skipped": 0}
    for i, e in enumerate(entries, 1):
        if skip_done and _done(name, e["label"], e["reps"]):
            log(f"[{i}/{len(entries)}] skip (done): {e['label']}")
            summary["skipped"] += 1
            continue
        log(f"[{i}/{len(entries)}] {e['label']}  ({time.time() - t0:.0f}s elapsed)")
        group = uuid.uuid4().hex[:8]
        try:
            spec = spec_from_entry(e)
        except Exception as ex:  # invalid experiment: record nothing, continue
            log(f"    cannot build experiment: {ex}")
            summary["failed"] += 1
            continue
        for r in range(e["reps"] + e["warmup"]):
            warm = r < e["warmup"]
            try:
                rid = runner.run_once(spec, group_id=group, rep_index=r if warm else r - e["warmup"], warmup=warm,
                                      suite=name, label=e["label"])
            except Exception as ex:  # noqa: BLE001
                log(f"    run error: {type(ex).__name__}: {ex}")
                summary["failed"] += 1
                continue
            with db.connect() as conn:
                row, _ = db.get_run(conn, rid)
            tag = "warm-up" if warm else f"rep {r - e['warmup'] + 1}"
            log(f"    run {rid} ({tag}): {row['status']} correct={row['correct']} wall={row['wall_s'] or 0:.3f}s"
                + (f" ERROR {row['error']}" if row["error"] else ""))
            if not warm:
                summary["ok" if row["status"] == "ok" and row["correct"] != 0 else "failed"] += 1
                summary["wrong"] += row["correct"] == 0
    log(f"suite {name} finished in {time.time() - t0:.0f}s: {summary}")
    return summary
