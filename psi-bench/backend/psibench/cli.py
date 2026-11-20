"""Command line interface: python -m psibench <command>."""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from . import config, datasets, db, envinfo, runner
from .adapters import PROTOCOLS, SYNTHETIC_ONLY
from .adapters.base import RunSpec


def _parse_params(items: list[str]) -> dict:
    out: dict = {}
    for it in items or []:
        k, _, v = it.partition("=")
        if v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
        else:
            try:
                out[k] = int(v)
            except ValueError:
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v if v else True
    return out


def _size(x: str) -> int:
    x = x.strip().replace("_", "")
    if "^" in x:  # 2^20
        base, exp = x.split("^")
        return int(base) ** int(exp)
    return int(float(x)) if "e" in x.lower() else int(x)


def _sizes(s: str) -> list[int]:
    """'1024,2^20' -> [1024, 1048576];  '65536x4' -> four parties of 65536 elements."""
    s = s.strip()
    if "x" in s.lower() and "," not in s:
        n, k = s.lower().split("x")
        return [_size(n)] * int(k)
    return [_size(x) for x in s.split(",")]


def _fmt(v, nd=2, none="-"):
    return none if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def _mb(b):
    return None if b is None else b / 1e6


def cmd_env(a) -> int:
    snap = envinfo.snapshot(include_images=not a.no_images)
    print(json.dumps(snap, indent=2))
    print("hash:", envinfo.snapshot_hash(snap))
    print(json.dumps({"host_state": envinfo.host_state()}, indent=2))
    return 0


def cmd_gen(a) -> int:
    d = datasets.generate(_sizes(a.sizes), a.common, a.seed, elem_bits=a.elem_bits)
    print(d)
    return 0


def cmd_import(a) -> int:
    d = datasets.import_files([Path(p) for p in a.files], a.name, hash_elements=not a.no_hash)
    print(d, json.dumps(datasets.load_meta(d)))
    return 0


def cmd_run(a) -> int:
    params = _parse_params(a.param)
    if a.dataset:
        d = Path(a.dataset)
        d = d if d.is_absolute() or d.exists() else config.DATASETS_DIR / a.dataset
        meta = datasets.load_meta(d)
        sizes, common, dataset_dir = meta["sizes"], meta["common"], d.resolve()
    else:
        sizes = _sizes(a.sizes)
        common = a.common
        # PEPSI's repo only benchmarks synthetic data of the given sizes; no files needed.
        # benchmark-mode binaries generate their own inputs and take no files
        dataset_dir = None if a.protocol in SYNTHETIC_ONLY else datasets.generate(sizes, common, a.seed, elem_bits=a.elem_bits).resolve()
    spec = RunSpec(protocol=a.protocol, sizes=sizes, common=common, seed=a.seed, dataset_dir=dataset_dir,
                   network=a.network, threads=a.threads, cpus=a.cpus, params=params, timeout_s=a.timeout)
    group = uuid.uuid4().hex[:8]
    total = a.warmup + a.reps
    print(f"group {group}: {a.protocol} sizes={sizes} common={common} net={a.network} threads={a.threads} "
          f"reps={a.reps}(+{a.warmup} warm-up)")
    failures = 0
    for i in range(total):
        warm = i < a.warmup
        rid = runner.run_once(spec, group_id=group, rep_index=i - a.warmup if not warm else i, warmup=warm)
        with db.connect() as conn:
            r, _ = db.get_run(conn, rid)
        flag = {1: "correct", 0: "WRONG", None: "unchecked"}[r["correct"]]
        print(f"  run {rid:>4}{' (warm-up)' if warm else ''}: {r['status']:<7} {flag:<9} wall={_fmt(r['wall_s'], 3)}s "
              f"cpu={_fmt(r['cpu_s'], 2)}s peak_rss={_fmt(_mb(r['peak_rss_kb_max'] and r['peak_rss_kb_max'] * 1000), 0)}MB "
              f"comm={_fmt(_mb(r['comm_total_bytes']), 3)}MB" + (f"  ERROR: {r['error']}" if r["error"] else ""))
        failures += r["status"] != "ok" or r["correct"] == 0
    if a.reps > 0:
        with db.connect() as conn:
            _print_summary(db.summarize_group(conn, group))
    return 1 if failures else 0


def _print_summary(s: dict) -> None:
    counts = s.get("status_counts", {})
    bad = {k: v for k, v in counts.items() if k != "ok"}
    print(f"summary of group {s['group_id']}: {counts.get('ok', 0)}/{sum(counts.values())} runs ok"
          + (f", NOT ok: {bad} (excluded from the statistics below)" if bad else "")
          + f", all_correct={s['all_correct']}")
    for m in db.SUMMARY_METRICS:
        d = s[m]
        if d.get("n"):
            ci = f" +-{d['ci95']:.4g} (95% CI)" if "ci95" in d else ""
            print(f"  {m:<18} n={d['n']} median={d['median']:.6g} mean={d['mean']:.6g}{ci} min={d['min']:.6g} max={d['max']:.6g}")


def cmd_history(a) -> int:
    with db.connect() as conn:
        rows = db.list_runs(conn, protocol=a.protocol, group=a.group, limit=a.limit)
    hdr = f"{'id':>4} {'group':<8} {'protocol':<11} {'n':>2} {'sizes':<22} {'net':<4} {'thr':>3} {'status':<7} {'ok':<9} {'wall_s':>8} {'cpu_s':>8} {'rssMB':>7} {'commMB':>9}"
    print(hdr)
    for r in rows:
        ok = {1: "correct", 0: "WRONG", None: "-"}[r["correct"]]
        sizes = ",".join(str(x) for x in json.loads(r["set_sizes"] or "[]"))
        rss = None if r["peak_rss_kb_max"] is None else r["peak_rss_kb_max"] / 1024
        print(f"{r['id']:>4} {(r['group_id'] or ''):<8} {r['protocol']:<11} {r['n_parties'] or '':>2} {sizes[:22]:<22} "
              f"{r['network']:<4} {r['threads']:>3} {r['status']:<7} {ok:<9} {_fmt(r['wall_s'], 3):>8} "
              f"{_fmt(r['cpu_s'], 2):>8} {_fmt(rss, 0):>7} {_fmt(_mb(r['comm_total_bytes']), 3):>9}"
              + ("  (warm-up)" if r["warmup"] else ""))
    return 0


def cmd_show(a) -> int:
    with db.connect() as conn:
        run, parties = db.get_run(conn, a.run_id)
        if not run:
            print("no such run", file=sys.stderr)
            return 1
        env = conn.execute("SELECT snapshot FROM environments WHERE id=?", (run["env_id"],)).fetchone()
    skip = {"host_state", "reported", "check_detail", "params"}
    print("RUN", a.run_id)
    for k in run.keys():
        if k not in skip and run[k] is not None:
            print(f"  {k:<18} {run[k]}")
    for k in ("params", "check_detail", "reported", "host_state"):
        if run[k]:
            print(f"  {k}: {json.dumps(json.loads(run[k]))}")
    print("PARTIES")
    for p in parties:
        print(f"  [{p['idx']}] {p['role']:<14} exit={p['exit_code']} wall={_fmt(p['wall_s'], 3)}s user={_fmt(p['user_s'], 2)}s sys={_fmt(p['sys_s'], 2)}s "
              f"maxrss={_fmt(p['maxrss_kb'] and p['maxrss_kb'] / 1024, 0)}MB tx={_fmt(_mb(p['tx_bytes']), 3)}MB rx={_fmt(_mb(p['rx_bytes']), 3)}MB")
        if p["reported"] and a.verbose:
            print("      reported:", p["reported"])
    if env and a.verbose:
        print("ENVIRONMENT", json.dumps(json.loads(env["snapshot"]), indent=2))
    return 0


def cmd_summary(a) -> int:
    with db.connect() as conn:
        _print_summary(db.summarize_group(conn, a.group))
    return 0


def cmd_suite(a) -> int:
    from . import suites
    res = suites.run_suite(Path(a.file), only=a.only, skip_done=a.skip_done, dry_run=a.dry_run,
                           log=lambda s: print(s, flush=True))
    return 1 if res.get("failed") or res.get("wrong") else 0


def cmd_report(a) -> int:
    from . import report
    with db.connect() as conn:
        print(report.markdown(report.collect(conn, a.suite, a.like)))
    return 0


def cmd_export(a) -> int:
    with db.connect() as conn:
        n = db.export_csv(conn, Path(a.csv))
    print(f"wrote {n} runs to {a.csv}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="psibench", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("env", help="print the hardware/software snapshot")
    p.add_argument("--no-images", action="store_true", help="skip querying docker images (faster)")
    p.set_defaults(fn=cmd_env)

    p = sub.add_parser("gen", help="generate a synthetic dataset with a planted intersection")
    p.add_argument("--sizes", required=True, help="comma list, one set size per party, e.g. 1024,1048576")
    p.add_argument("--common", type=int, required=True, help="size of the intersection shared by all parties")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--elem-bits", type=int, default=128, help="element domain size in bits (32 = the paper's 32-bit setting)")
    p.set_defaults(fn=cmd_gen)

    p = sub.add_parser("import", help="register your own files (one element per line) as a dataset")
    p.add_argument("--name", required=True)
    p.add_argument("--no-hash", action="store_true", help="require 32-hex elements instead of hashing")
    p.add_argument("files", nargs="+")
    p.set_defaults(fn=cmd_import)

    p = sub.add_parser("run", help="run a protocol (optionally repeated)")
    p.add_argument("--protocol", required=True, choices=PROTOCOLS)
    p.add_argument("--dataset", help="dataset directory or name under data/datasets")
    p.add_argument("--sizes", help="generate a synthetic dataset with these set sizes (comma list)")
    p.add_argument("--common", type=int, default=100)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--elem-bits", type=int, default=128, help="element domain bits for generated datasets")
    p.add_argument("--network", default="none", choices=list(config.NETWORK_PROFILES))
    p.add_argument("--threads", type=int, default=1)
    p.add_argument("--cpus", help="CPU list to pin to (default: P-cores)")
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--warmup", type=int, default=0)
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--param", action="append", default=[], help="protocol option k=v (e.g. ca=true, malicious=true, task=PSISum)")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("history", help="list recent runs")
    p.add_argument("--protocol")
    p.add_argument("--group")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(fn=cmd_history)

    p = sub.add_parser("show", help="details of one run")
    p.add_argument("run_id", type=int)
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("summary", help="median/mean/CI over the repetitions of a group")
    p.add_argument("group")
    p.set_defaults(fn=cmd_summary)

    p = sub.add_parser("suite", help="run an experiment suite (JSON file)")
    p.add_argument("file")
    p.add_argument("--only", help="only experiments whose label contains this text")
    p.add_argument("--skip-done", action="store_true", help="skip experiments that already have enough ok runs")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_suite)

    p = sub.add_parser("report", help="comparison table of suite experiments (markdown)")
    p.add_argument("--suite")
    p.add_argument("--like", help="only labels containing this text")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("export", help="export all runs to CSV")
    p.add_argument("--csv", required=True)
    p.set_defaults(fn=cmd_export)

    a = ap.parse_args(argv)
    if a.cmd == "run" and not (a.dataset or a.sizes):
        ap.error("run needs --dataset or --sizes")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
