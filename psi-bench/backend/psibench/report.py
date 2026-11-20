"""Aggregate recorded runs into comparison tables and API-ready group summaries."""
from __future__ import annotations

import json

from . import db


def _fmt_bytes(b):
    return "-" if b is None else f"{b / 1e6:.2f}"


def _fmt_ci(d, scale=1.0, nd=3):
    if not d.get("n"):
        return "-"
    s = f"{d['median'] * scale:.{nd}f}"
    if "ci95" in d and d["ci95"] is not None:
        s += f" ±{d['ci95'] * scale:.{nd}f}"
    return s


def group_entry(conn, group_id: str, suite: str | None = None, label: str | None = None) -> dict | None:
    """Statistics of one group of repetitions (warm-up runs excluded)."""
    rows = conn.execute("SELECT * FROM runs WHERE group_id=? AND warmup=0 ORDER BY rep_index", (group_id,)).fetchall()
    if not rows:
        return None
    ok = [x for x in rows if x["status"] == "ok"]
    first = rows[0]
    return {
        "group_id": group_id, "suite": suite if suite is not None else first["suite"],
        "label": label if label is not None else (first["label"] or f"{first['protocol']} {first['set_sizes']}"),
        "protocol": first["protocol"], "sizes": json.loads(first["set_sizes"] or "[]"),
        "network": first["network"], "threads": first["threads"], "params": json.loads(first["params"] or "{}"),
        "first_id": min(x["id"] for x in rows), "started_at": first["started_at"],
        "n_total": len(rows), "n_ok": len(ok),
        "n_wrong": sum(1 for x in ok if x["correct"] == 0),
        "checked": any(x["correct"] is not None for x in ok),
        "wall": db.describe([x["wall_s"] for x in ok]),
        "cpu": db.describe([x["cpu_s"] for x in ok]),
        "rss": db.describe([x["peak_rss_kb_max"] for x in ok]),
        "comm": db.describe([x["comm_total_bytes"] for x in ok]),
        "comm_online": db.describe([x["comm_online_bytes"] for x in ok]),
        "run_ids": [x["id"] for x in rows],
    }


def collect(conn, suite: str | None = None, labels_like: str | None = None) -> list[dict]:
    """Most recent group of every (suite, label) experiment."""
    q = "SELECT DISTINCT suite, label FROM runs WHERE label IS NOT NULL"
    args: list = []
    if suite:
        q += " AND suite=?"
        args.append(suite)
    if labels_like:
        q += " AND label LIKE ?"
        args.append(f"%{labels_like}%")
    out = []
    for r in conn.execute(q, args).fetchall():
        g = conn.execute(
            "SELECT group_id FROM runs WHERE suite IS ? AND label=? AND warmup=0 ORDER BY id DESC LIMIT 1",
            (r["suite"], r["label"])).fetchone()
        if not g:
            continue
        e = group_entry(conn, g["group_id"], r["suite"], r["label"])
        if e:
            out.append(e)
    out.sort(key=lambda e: e["first_id"])
    return out


def list_groups(conn, limit: int = 200, protocol: str | None = None) -> list[dict]:
    """Recent groups of repetitions (any run, with or without a suite)."""
    q = "SELECT group_id, MAX(id) AS last_id FROM runs WHERE group_id IS NOT NULL AND warmup=0"
    args: list = []
    if protocol:
        q += " AND protocol=?"
        args.append(protocol)
    q += " GROUP BY group_id ORDER BY last_id DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in conn.execute(q, args).fetchall():
        e = group_entry(conn, r["group_id"])
        if e:
            out.append(e)
    return out


def markdown(rows: list[dict]) -> str:
    hdr = ("| experiment | runs ok | correct | wall s (median ±95% CI) | CPU s | peak RSS MB | comm MB | online MB |\n"
           "|---|---|---|---|---|---|---|---|\n")
    lines = []
    for e in rows:
        if not e["n_ok"]:
            correct = "-"
        elif not e["checked"]:
            correct = "n/a"
        else:
            correct = "yes" if e["n_wrong"] == 0 else f"NO ({e['n_wrong']}/{e['n_ok']} wrong)"
        lines.append(
            f"| {e['label']} | {e['n_ok']}/{e['n_total']} | {correct} | {_fmt_ci(e['wall'])} | {_fmt_ci(e['cpu'], nd=2)} | "
            f"{_fmt_ci(e['rss'], 1 / 1024, 0)} | {_fmt_bytes(e['comm'].get('median'))} | {_fmt_bytes(e['comm_online'].get('median'))} |")
    return hdr + "\n".join(lines) + "\n"


def latex(rows: list[dict]) -> str:
    """A booktabs table for the paper."""
    def esc(s: str) -> str:
        return s.replace("_", "\\_").replace("%", "\\%").replace("&", "\\&").replace("#", "\\#")
    out = ["\\begin{tabular}{lrrrrr}", "\\toprule",
           "Experiment & Runs & Wall (s) & CPU (s) & Mem (MB) & Comm (MB) \\\\", "\\midrule"]
    for e in rows:
        w = e["wall"]
        wall = "-" if not w.get("n") else f"{w['median']:.3f}" + (f" $\\pm$ {w['ci95']:.3f}" if w.get("ci95") is not None else "")
        cpu = "-" if not e["cpu"].get("n") else f"{e['cpu']['median']:.2f}"
        rss = "-" if not e["rss"].get("n") else f"{e['rss']['median'] / 1024:.0f}"
        comm = "-" if not e["comm"].get("n") else f"{e['comm']['median'] / 1e6:.2f}"
        out.append(f"{esc(e['label'])} & {e['n_ok']}/{e['n_total']} & {wall} & {cpu} & {rss} & {comm} \\\\")
    out += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(out) + "\n"
