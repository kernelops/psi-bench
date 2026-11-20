"""SQLite run history. One row per run, one row per party, deduplicated environments."""
from __future__ import annotations

import csv
import json
import math
import sqlite3
import statistics
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS environments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    snapshot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id TEXT,
    rep_index INTEGER DEFAULT 0,
    warmup INTEGER DEFAULT 0,
    started_at TEXT NOT NULL,
    protocol TEXT NOT NULL,
    n_parties INTEGER,
    set_sizes TEXT,
    true_intersection INTEGER,
    network TEXT,
    netem TEXT,
    threads INTEGER,
    cpus TEXT,
    params TEXT,
    dataset TEXT,
    env_id INTEGER REFERENCES environments(id),
    host_state TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    error TEXT,
    correct INTEGER,
    check_detail TEXT,
    wall_s REAL,
    cpu_s REAL,
    peak_rss_kb_max INTEGER,
    peak_rss_kb_sum INTEGER,
    comm_total_bytes INTEGER,
    comm_online_bytes INTEGER,
    reported TEXT,
    run_dir TEXT
);
CREATE TABLE IF NOT EXISTS parties (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    role TEXT,
    runtime TEXT,
    exit_code INTEGER,
    start_epoch REAL,
    end_epoch REAL,
    wall_s REAL,
    user_s REAL,
    sys_s REAL,
    maxrss_kb INTEGER,
    cgroup_peak_kb INTEGER,
    tx_bytes INTEGER,
    rx_bytes INTEGER,
    tx_packets INTEGER,
    rx_packets INTEGER,
    reported TEXT,
    mem_timeline TEXT,
    netem_stats TEXT,
    log_path TEXT,
    PRIMARY KEY (run_id, idx)
);
CREATE INDEX IF NOT EXISTS idx_runs_protocol ON runs(protocol);
CREATE INDEX IF NOT EXISTS idx_runs_group ON runs(group_id);
"""


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    config.ensure_dirs()
    conn = sqlite3.connect(str(path or config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    # lightweight migrations for databases created by earlier versions
    have = {r["name"] for r in conn.execute("PRAGMA table_info(runs)")}
    for col in ("suite", "label"):
        if col not in have:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_suite ON runs(suite, label)")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _j(x: Any) -> str | None:
    return None if x is None else json.dumps(x)


def get_or_create_env(conn: sqlite3.Connection, h: str, snapshot: dict) -> int:
    row = conn.execute("SELECT id FROM environments WHERE hash=?", (h,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO environments(hash, created_at, snapshot) VALUES (?,?,?)",
        (h, time.strftime("%Y-%m-%dT%H:%M:%S"), json.dumps(snapshot)),
    )
    return cur.lastrowid


def start_run(conn: sqlite3.Connection, **f: Any) -> int:
    cur = conn.execute(
        """INSERT INTO runs(group_id, rep_index, warmup, started_at, protocol, n_parties, set_sizes,
               true_intersection, network, netem, threads, cpus, params, dataset, env_id, host_state,
               suite, label, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'running')""",
        (
            f.get("group_id"), f.get("rep_index", 0), int(f.get("warmup", False)),
            time.strftime("%Y-%m-%dT%H:%M:%S"), f["protocol"], f.get("n_parties"),
            _j(f.get("set_sizes")), f.get("true_intersection"), f.get("network"), f.get("netem"),
            f.get("threads"), f.get("cpus"), _j(f.get("params")), f.get("dataset"),
            f.get("env_id"), _j(f.get("host_state")), f.get("suite"), f.get("label"),
        ),
    )
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, **f: Any) -> None:
    json_cols = {"check_detail", "reported"}
    cols, vals = [], []
    for k, v in f.items():
        cols.append(f"{k}=?")
        vals.append(_j(v) if k in json_cols else v)
    conn.execute(f"UPDATE runs SET {', '.join(cols)} WHERE id=?", (*vals, run_id))


def add_party(conn: sqlite3.Connection, run_id: int, **f: Any) -> None:
    for k in ("reported", "mem_timeline"):
        if k in f:
            f[k] = _j(f[k])
    names = ["run_id"] + list(f)
    conn.execute(
        f"INSERT OR REPLACE INTO parties({','.join(names)}) VALUES ({','.join('?' * len(names))})",
        (run_id, *f.values()),
    )


def list_runs(conn: sqlite3.Connection, protocol: str | None = None, group: str | None = None,
              limit: int = 50, include_warmup: bool = True) -> list[sqlite3.Row]:
    q, args = "SELECT * FROM runs WHERE 1=1", []
    if protocol:
        q += " AND protocol=?"; args.append(protocol)
    if group:
        q += " AND group_id=?"; args.append(group)
    if not include_warmup:
        q += " AND warmup=0"
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    return conn.execute(q, args).fetchall()


def get_run(conn: sqlite3.Connection, run_id: int) -> tuple[sqlite3.Row | None, list[sqlite3.Row]]:
    run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    parties = conn.execute("SELECT * FROM parties WHERE run_id=? ORDER BY idx", (run_id,)).fetchall()
    return run, parties


# two-sided 95% Student t critical values, df = 1..30
_T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160,
        2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056,
        2.052, 2.048, 2.045, 2.042]


def describe(values: list[float]) -> dict:
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return {"n": 0}
    out = {"n": n, "median": statistics.median(vals), "mean": statistics.fmean(vals), "min": min(vals), "max": max(vals)}
    if n > 1:
        sd = statistics.stdev(vals)
        t = _T95[n - 2] if n - 1 <= 30 else 1.96
        out.update(stdev=sd, ci95=t * sd / math.sqrt(n))
    return out


SUMMARY_METRICS = ("wall_s", "cpu_s", "peak_rss_kb_max", "peak_rss_kb_sum", "comm_total_bytes", "comm_online_bytes")


def summarize_group(conn: sqlite3.Connection, group_id: str) -> dict:
    rows = conn.execute(
        "SELECT * FROM runs WHERE group_id=? AND warmup=0 AND status='ok' ORDER BY rep_index", (group_id,)
    ).fetchall()
    counts = conn.execute(
        "SELECT status, COUNT(*) AS n FROM runs WHERE group_id=? AND warmup=0 GROUP BY status", (group_id,)
    ).fetchall()
    return {"group_id": group_id, "runs": [r["id"] for r in rows],
            "status_counts": {c["status"]: c["n"] for c in counts},
            # None means "not checked" (e.g. PEPSI benchmark mode), never "correct"
            "all_correct": (all(r["correct"] == 1 for r in rows if r["correct"] is not None)
                            if any(r["correct"] is not None for r in rows) else None),
            **{m: describe([r[m] for r in rows]) for m in SUMMARY_METRICS}}


def export_csv(conn: sqlite3.Connection, out: Path) -> int:
    rows = conn.execute("SELECT * FROM runs ORDER BY id").fetchall()
    if not rows:
        return 0
    skip = {"host_state", "reported", "check_detail"}
    cols = [c for c in rows[0].keys() if c not in skip]
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r[c] for c in cols])
    return len(rows)
