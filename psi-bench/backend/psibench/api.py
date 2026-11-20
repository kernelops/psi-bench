"""HTTP API for the UI. Run with:  ./serve   (uvicorn psibench.api:app)

Benchmarks are executed one at a time by a single worker thread, because concurrent runs would compete for the
same CPU cores and distort each other's timings.
"""
from __future__ import annotations

import csv
import io
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, datasets, db, envinfo, protocols_info, report, runner, suites
from .adapters import SYNTHETIC_ONLY, get_adapter
from .adapters.base import RunSpec

app = FastAPI(title="psibench", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

SUITES_DIR = config.ROOT / "suites"
FRONTEND_DIST = config.ROOT / "frontend" / "dist"


# ------------------------------------------------------------------ helpers
def _loads(v):
    if v is None or v == "":
        return None
    try:
        return json.loads(v)
    except (TypeError, json.JSONDecodeError):
        return v


RUN_JSON = ("set_sizes", "params", "host_state", "check_detail", "reported")
PARTY_JSON = ("reported", "mem_timeline")


def run_row(r, brief: bool = False) -> dict:
    d = dict(r)
    for k in RUN_JSON:
        d[k] = _loads(d.get(k))
    if brief:
        for k in ("host_state", "reported", "check_detail"):
            d.pop(k, None)
    return d


def party_row(p, timeline: bool = True) -> dict:
    d = dict(p)
    for k in PARTY_JSON:
        d[k] = _loads(d.get(k))
    if not timeline:
        d.pop("mem_timeline", None)
    return d


# ------------------------------------------------------------------ job queue
class Job:
    def __init__(self, kind: str, title: str, total: int, payload: dict):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.title = kind, title
        self.spec = payload.pop("_spec", None)   # internal object, never part of the API payload
        self.payload = payload
        self.status = "queued"          # queued | running | done | failed | cancelled
        self.total, self.done = total, 0
        self.run_ids: list[int] = []
        self.group_id: str | None = None
        self.error: str | None = None
        self.log: list[str] = []
        self.created = time.time()
        self.started: float | None = None
        self.finished: float | None = None
        self.cancel = threading.Event()

    def say(self, line: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')} {line}")
        del self.log[:-300]

    def to_dict(self, with_log: bool = False) -> dict:
        d = {"id": self.id, "kind": self.kind, "title": self.title, "status": self.status, "total": self.total,
             "done": self.done, "run_ids": self.run_ids, "group_id": self.group_id, "error": self.error,
             "created": self.created, "started": self.started, "finished": self.finished,
             "payload": self.payload}
        if with_log:
            d["log"] = self.log
        return d


JOBS: dict[str, Job] = {}
_QUEUE: list[Job] = []
_COND = threading.Condition()


def _spec_from_request(req: "RunRequest") -> tuple[RunSpec, str]:
    info = protocols_info.by_id(req.protocol)
    if not info:
        raise HTTPException(400, f"unknown protocol {req.protocol}")
    sizes = req.sizes
    dataset_dir = None
    if req.protocol in SYNTHETIC_ONLY:
        if not sizes:
            raise HTTPException(400, "sizes are required")
        if req.dataset:
            raise HTTPException(400, f"{req.protocol} generates its own inputs and cannot use an uploaded dataset")
    else:
        if req.dataset:
            d = config.DATASETS_DIR / req.dataset
            if not (d / "meta.json").exists():
                raise HTTPException(404, f"dataset {req.dataset} not found")
            meta = datasets.load_meta(d)
            sizes, dataset_dir = meta["sizes"], d.resolve()
        else:
            if not sizes:
                raise HTTPException(400, "give sizes or choose a dataset")
            try:
                dataset_dir = datasets.generate(sizes, req.common, req.seed, elem_bits=req.elem_bits).resolve()
            except ValueError as e:
                raise HTTPException(400, str(e))
    n = len(sizes)
    if n < info["min_parties"] or (info["max_parties"] and n > info["max_parties"]):
        raise HTTPException(400, f"{req.protocol} supports {info['min_parties']}..{info['max_parties'] or 'many'} parties, got {n}")
    if req.network not in config.NETWORK_PROFILES:
        raise HTTPException(400, f"unknown network {req.network}")
    try:
        params = protocols_info.coerce_params(req.protocol, req.params)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"bad parameters: {e}")
    spec = RunSpec(protocol=req.protocol, sizes=[int(s) for s in sizes], common=req.common, seed=req.seed,
                   dataset_dir=dataset_dir, network=req.network, threads=req.threads, cpus=req.cpus or None,
                   params=params, timeout_s=req.timeout)
    try:  # validates sizes/parties against the adapter before queueing
        get_adapter(req.protocol).validate(spec)
        if req.protocol in ("bzs-perf", "volepsi-perf"):
            get_adapter(req.protocol)._nn(spec)  # type: ignore[attr-defined]
    except ValueError as e:
        raise HTTPException(400, str(e))
    return spec, ("synthetic" if req.protocol in SYNTHETIC_ONLY else (req.dataset or dataset_dir.name))


def _execute_run_job(job: Job) -> None:
    spec: RunSpec = job.spec
    reps, warmup = job.payload["reps"], job.payload["warmup"]
    job.group_id = uuid.uuid4().hex[:8]
    for i in range(reps + warmup):
        if job.cancel.is_set():
            job.status = "cancelled"
            return
        warm = i < warmup
        job.say(f"{'warm-up' if warm else 'repetition'} {i + 1 if warm else i - warmup + 1}/{warmup if warm else reps} ...")
        rid = runner.run_once(spec, group_id=job.group_id, rep_index=i if warm else i - warmup, warmup=warm,
                              suite=None, label=job.title)
        job.run_ids.append(rid)
        job.done += 1
        with db.connect() as conn:
            row, _ = db.get_run(conn, rid)
            if job.cancel.is_set() and row["status"] != "ok":
                # killed by the user: record as aborted, not as a protocol failure
                db.finish_run(conn, rid, status="aborted", error="cancelled by user")
                row, _ = db.get_run(conn, rid)
        job.say(f"run {rid}: {row['status']}, correct={row['correct']}, wall={row['wall_s'] or 0:.3f}s"
                + (f", error: {row['error']}" if row["error"] else ""))


def _execute_suite_job(job: Job) -> None:
    path = SUITES_DIR / job.payload["file"]
    # suites.run_suite does its own loop; give it a log hook and let cancel stop between experiments via exception
    def log(line: str) -> None:
        if job.cancel.is_set():
            raise RuntimeError("cancelled")
        job.say(line.strip())
        if line.strip().startswith("run "):
            job.done += 1
    try:
        suites.run_suite(path, skip_done=job.payload.get("skip_done", True), log=log)
    except RuntimeError as e:
        if str(e) == "cancelled":
            job.status = "cancelled"
            return
        raise


def _worker() -> None:
    while True:
        with _COND:
            while not _QUEUE:
                _COND.wait()
            job = _QUEUE.pop(0)
        if job.cancel.is_set():
            job.status, job.finished = "cancelled", time.time()
            continue
        job.status, job.started = "running", time.time()
        try:
            (_execute_run_job if job.kind == "run" else _execute_suite_job)(job)
            if job.status == "running":
                job.status = "done"
        except Exception as e:  # noqa: BLE001
            job.status, job.error = "failed", f"{type(e).__name__}: {e}"
            job.say(f"FAILED: {job.error}")
        job.finished = time.time()


threading.Thread(target=_worker, daemon=True, name="psibench-worker").start()


def _enqueue(job: Job) -> Job:
    JOBS[job.id] = job
    with _COND:
        _QUEUE.append(job)
        _COND.notify()
    return job


# ------------------------------------------------------------------ request models
class RunRequest(BaseModel):
    protocol: str
    sizes: list[int] | None = None
    dataset: str | None = None
    common: int = 100
    seed: int = 1
    elem_bits: int = 128
    network: str = "none"
    threads: int = Field(1, ge=1, le=64)
    cpus: str | None = None
    reps: int = Field(1, ge=1, le=100)
    warmup: int = Field(0, ge=0, le=5)
    timeout: int = Field(1800, ge=10, le=86400)
    params: dict[str, Any] = {}
    title: str | None = None


class GenerateRequest(BaseModel):
    sizes: list[int]
    common: int
    seed: int = 1
    elem_bits: int = 128


class SuiteRequest(BaseModel):
    file: str
    skip_done: bool = True


# ------------------------------------------------------------------ routes: static info
@app.get("/api/health")
def health():
    return {"ok": True, "queue": len(_QUEUE), "running": [j.id for j in JOBS.values() if j.status == "running"]}


@app.get("/api/protocols")
def protocols():
    return {"protocols": protocols_info.PROTOCOLS, "networks": protocols_info.NETWORKS,
            "pinned_cpus": config.performance_cores()}


_ENV_CACHE: dict = {}


@app.get("/api/env")
def env(refresh: bool = False):
    if refresh or "snap" not in _ENV_CACHE:
        snap, h = runner.environment()
        _ENV_CACHE["snap"], _ENV_CACHE["hash"] = snap, h
    return {"snapshot": _ENV_CACHE["snap"], "hash": _ENV_CACHE["hash"], "host_state": envinfo.host_state()}


# ------------------------------------------------------------------ datasets
@app.get("/api/datasets")
def list_datasets():
    out = []
    if config.DATASETS_DIR.exists():
        for d in sorted(config.DATASETS_DIR.iterdir()):
            if (d / "meta.json").exists():
                meta = datasets.load_meta(d)
                out.append({"name": d.name, **meta})
    return out


@app.post("/api/datasets/generate")
def generate_dataset(req: GenerateRequest):
    try:
        d = datasets.generate(req.sizes, req.common, req.seed, elem_bits=req.elem_bits)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"name": d.name, **datasets.load_meta(d)}


@app.post("/api/datasets/import")
async def import_dataset(name: str = Form(...), hash_elements: bool = Form(True), files: list[UploadFile] = File(...)):
    if not name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "name may only contain letters, digits, - and _")
    if len(files) < 2:
        raise HTTPException(400, "upload one file per party (at least 2)")
    tmp = config.DATA_DIR / "uploads" / uuid.uuid4().hex[:8]
    tmp.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, f in enumerate(files):
        p = tmp / f"in_{i}.txt"
        p.write_bytes(await f.read())
        paths.append(p)
    try:
        d = datasets.import_files(paths, name, hash_elements=hash_elements)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"name": d.name, **datasets.load_meta(d)}


# ------------------------------------------------------------------ jobs
@app.post("/api/jobs/run")
def create_run_job(req: RunRequest):
    spec, dataset_name = _spec_from_request(req)
    title = req.title or f"{req.protocol} {'x'.join(str(s) for s in spec.sizes)} {req.network} t{req.threads}"
    job = Job("run", title, req.reps + req.warmup, {
        "protocol": req.protocol, "sizes": spec.sizes, "dataset": dataset_name, "network": req.network,
        "threads": req.threads, "reps": req.reps, "warmup": req.warmup, "params": spec.params,
        "_spec": spec})
    _enqueue(job)
    return job.to_dict()


@app.get("/api/suites")
def list_suites():
    out = []
    for f in sorted(SUITES_DIR.glob("*.json")):
        s = json.loads(f.read_text())
        n = suites.expand(s)
        out.append({"file": f.name, "name": s["name"], "description": s.get("description", ""),
                    "experiments": len(n), "runs": sum(e["reps"] + e["warmup"] for e in n),
                    "protocols": sorted({e["protocol"] for e in n})})
    return out


@app.post("/api/jobs/suite")
def create_suite_job(req: SuiteRequest):
    f = SUITES_DIR / req.file
    if not f.exists() or f.suffix != ".json" or f.parent != SUITES_DIR:
        raise HTTPException(404, "unknown suite file")
    s = json.loads(f.read_text())
    total = sum(e["reps"] + e["warmup"] for e in suites.expand(s))
    job = _enqueue(Job("suite", f"suite {s['name']}", total, {"file": req.file, "skip_done": req.skip_done}))
    return job.to_dict()


@app.get("/api/jobs")
def list_jobs():
    return [j.to_dict() for j in sorted(JOBS.values(), key=lambda j: -j.created)]


def _public(job: Job, with_log: bool) -> dict:
    return job.to_dict(with_log)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404, "no such job")
    return _public(j, True)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404, "no such job")
    j.cancel.set()
    if j.status == "queued":
        with _COND:
            if j in _QUEUE:
                _QUEUE.remove(j)
        j.status, j.finished = "cancelled", time.time()
    elif j.status == "running":
        j.say("cancel requested: killing the running containers, remaining repetitions are skipped")

        def kill_until_stopped() -> None:
            # containers may not exist yet (still starting) when the request arrives, so keep trying
            # until the job has left the running state; only one job runs at a time
            for _ in range(240):
                if j.status != "running":
                    return
                ids = subprocess.run(["docker", "ps", "-q", "--filter", "label=psibench=1"],
                                     capture_output=True, text=True).stdout.split()
                if ids:
                    subprocess.run(["docker", "kill", *ids], capture_output=True)
                time.sleep(0.25)

        threading.Thread(target=kill_until_stopped, daemon=True).start()
    return _public(j, True)


# ------------------------------------------------------------------ runs, groups, compare
@app.get("/api/runs")
def list_runs(protocol: str | None = None, group: str | None = None, suite: str | None = None, limit: int = 100,
              include_warmup: bool = True):
    with db.connect() as conn:
        q, a = "SELECT * FROM runs WHERE 1=1", []
        if protocol:
            q += " AND protocol=?"; a.append(protocol)
        if group:
            q += " AND group_id=?"; a.append(group)
        if suite:
            q += " AND suite=?"; a.append(suite)
        if not include_warmup:
            q += " AND warmup=0"
        q += " ORDER BY id DESC LIMIT ?"
        a.append(min(limit, 1000))
        return [run_row(r, brief=True) for r in conn.execute(q, a).fetchall()]


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    with db.connect() as conn:
        run, parties = db.get_run(conn, run_id)
        if not run:
            raise HTTPException(404, "no such run")
        env_row = conn.execute("SELECT hash, snapshot FROM environments WHERE id=?", (run["env_id"],)).fetchone()
    d = run_row(run)
    d["parties"] = [party_row(p) for p in parties]
    d["environment"] = {"hash": env_row["hash"], "snapshot": _loads(env_row["snapshot"])} if env_row else None
    return d


@app.get("/api/runs/{run_id}/log/{party}", response_class=PlainTextResponse)
def run_log(run_id: int, party: int):
    with db.connect() as conn:
        row = conn.execute("SELECT log_path FROM parties WHERE run_id=? AND idx=?", (run_id, party)).fetchone()
    if not row or not row["log_path"] or not Path(row["log_path"]).exists():
        raise HTTPException(404, "no log")
    return Path(row["log_path"]).read_text(errors="replace")[-200_000:]


@app.get("/api/groups")
def groups(limit: int = 100, protocol: str | None = None):
    with db.connect() as conn:
        return report.list_groups(conn, limit, protocol)


@app.get("/api/groups/{group_id}")
def group(group_id: str):
    with db.connect() as conn:
        e = report.group_entry(conn, group_id)
        if not e:
            raise HTTPException(404, "no such group")
        rows = conn.execute("SELECT * FROM runs WHERE group_id=? ORDER BY id", (group_id,)).fetchall()
    return {**e, "runs": [run_row(r, brief=True) for r in rows]}


@app.get("/api/compare")
def compare(groups: str):
    with db.connect() as conn:
        out = [report.group_entry(conn, g) for g in groups.split(",") if g]
    return [e for e in out if e]


@app.get("/api/experiments")
def experiments(suite: str | None = None):
    """Latest group of every suite experiment (for the comparison tables)."""
    with db.connect() as conn:
        rows = report.collect(conn, suite)
        names = [r["suite"] for r in conn.execute("SELECT DISTINCT suite FROM runs WHERE suite IS NOT NULL").fetchall()]
    return {"suites": names, "experiments": rows}


@app.get("/api/report.md", response_class=PlainTextResponse)
def report_md(suite: str | None = None):
    with db.connect() as conn:
        return report.markdown(report.collect(conn, suite))


@app.get("/api/report.tex", response_class=PlainTextResponse)
def report_tex(suite: str | None = None):
    with db.connect() as conn:
        return report.latex(report.collect(conn, suite))


@app.get("/api/export.csv", response_class=PlainTextResponse)
def export_csv():
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY id").fetchall()
    if not rows:
        return ""
    skip = {"host_state", "reported", "check_detail"}
    cols = [c for c in rows[0].keys() if c not in skip]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] for c in cols])
    return buf.getvalue()


# ------------------------------------------------------------------ static frontend (production build)
from fastapi.responses import FileResponse  # noqa: E402

if (FRONTEND_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """Serve the built UI; unknown paths fall back to index.html so client-side routes survive a refresh."""
        if path.startswith("api/"):
            raise HTTPException(404, "no such API route")
        f = (FRONTEND_DIST / path).resolve()
        if path and f.is_file() and FRONTEND_DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
