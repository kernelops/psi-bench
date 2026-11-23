"""Executes a Plan (docker containers or native processes) and records the run."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import config, db, envinfo
from .adapters import get_adapter
from .adapters.base import Collected, PartyPlan, Plan, RunSpec


class RunError(RuntimeError):
    pass


def _sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def ensure_network() -> None:
    if _sh(["docker", "network", "inspect", config.NET_NAME]).returncode != 0:
        r = _sh(["docker", "network", "create", "--subnet", config.NET_SUBNET, config.NET_NAME])
        if r.returncode != 0:
            raise RunError(f"cannot create docker network {config.NET_NAME}: {r.stderr.strip()}")


def container_name(run_id: int, idx: int) -> str:
    return f"psibench-{run_id}-p{idx}"


def kill_run_containers(run_id: int) -> None:
    ids = _sh(["docker", "ps", "-q", "--filter", f"label=psibench.run={run_id}"]).stdout.split()
    if ids:
        _sh(["docker", "kill", *ids])


def _wrapper_args(p: PartyPlan, spec: RunSpec, netem: str | None, out: str, log: str, sync: str | None) -> list[str]:
    # gate-timeout: a client may legitimately wait for the whole offline phase of a large server
    a = ["--out", out, "--log", log, "--tag", p.tag, "--timeout", str(spec.timeout_s),
         "--gate-timeout", str(spec.timeout_s)]
    if sync:
        a += ["--sync-dir", sync]
    if p.announce:
        a += ["--announce", ",".join(str(x) for x in p.announce)]
    for w in p.wait_for:
        a += ["--wait-for", w]
    if p.start_delay_ms:
        a += ["--start-delay-ms", str(p.start_delay_ms)]
    if netem and p.runtime == "docker":
        a += ["--netem", netem]
    return a


def _docker_cmd(p: PartyPlan, spec: RunSpec, run_id: int, run_dir: Path, cpus: str, netem: str | None) -> list[str]:
    pdir = run_dir / f"party_{p.idx}"
    cmd = [
        "docker", "run", "--rm", "--name", container_name(run_id, p.idx),
        "--network", config.NET_NAME, "--ip", p.ip,
        "--cap-add", "NET_ADMIN", "--cpuset-cpus", cpus,
        "--label", "psibench=1", "--label", f"psibench.run={run_id}",
        "-v", f"{config.WRAPPER_PATH}:/psi/psi_wrap.py:ro",
        "-v", f"{pdir}:/out", "-v", f"{run_dir / 'sync'}:/sync",
    ]
    if spec.dataset_dir:
        cmd += ["-v", f"{spec.dataset_dir}:/data:ro"]
    for k, v in p.env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += ["--entrypoint", "python3", p.image, "/psi/psi_wrap.py"]
    cmd += _wrapper_args(p, spec, netem, "/out/metrics.json", "/out/stdout.log", "/sync")
    cmd += ["--uid", str(os.getuid()), "--gid", str(os.getgid()), "--cwd", "/out", "--"] + p.argv
    return cmd


def _native_cmd(p: PartyPlan, spec: RunSpec, run_dir: Path, cpus: str) -> list[str]:
    pdir = run_dir / f"party_{p.idx}"
    cmd = [sys.executable, str(config.WRAPPER_PATH)]
    cmd += _wrapper_args(p, spec, None, str(pdir / "metrics.json"), str(pdir / "stdout.log"), None)
    cmd += ["--no-net", "--cpus", cpus, "--cwd", p.cwd or str(pdir), "--"] + p.argv
    return cmd


def execute_plan(plan: Plan, spec: RunSpec, run_id: int, run_dir: Path) -> dict[int, dict]:
    """Start all parties, release them together, wait, return {idx: metrics}."""
    cpus = spec.cpus or config.performance_cores()
    netem = config.NETWORK_PROFILES[spec.network]
    (run_dir / "sync").mkdir(parents=True, exist_ok=True)
    for p in plan.parties:
        (run_dir / f"party_{p.idx}").mkdir(parents=True, exist_ok=True)
    uses_docker = any(p.runtime == "docker" for p in plan.parties)
    if uses_docker:
        for image in sorted({p.image for p in plan.parties if p.runtime == "docker"}):
            if _sh(["docker", "image", "inspect", image]).returncode != 0:
                raise RunError(f"Docker image '{image}' not found. Build it with docker/build_images.sh "
                               f"(needs the protocol repositories next to psi-bench, see README.md).")
        ensure_network()
        for p in plan.parties:  # stale containers from an interrupted run
            _sh(["docker", "rm", "-f", container_name(run_id, p.idx)])

    procs: dict[int, subprocess.Popen] = {}
    errs = {}
    try:
        for p in plan.parties:
            cmd = _docker_cmd(p, spec, run_id, run_dir, cpus, netem) if p.runtime == "docker" else _native_cmd(p, spec, run_dir, cpus)
            errs[p.idx] = open(run_dir / f"party_{p.idx}" / "launcher.stderr", "w")
            env = {**os.environ, **p.env} if p.runtime == "native" else None
            procs[p.idx] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=errs[p.idx], env=env)

        # gate: wait until every docker wrapper has finished its setup, then release all at once
        if uses_docker:
            deadline = time.monotonic() + 120
            want = [run_dir / "sync" / f"ready_{p.tag}" for p in plan.parties if p.runtime == "docker"]
            while not all(w.exists() for w in want):
                dead = [i for i, pr in procs.items() if pr.poll() is not None and pr.returncode != 0]
                if dead or time.monotonic() > deadline:
                    raise RunError(f"parties {dead or 'all'} failed before start; see launcher.stderr")
                time.sleep(0.01)
            (run_dir / "sync" / "go").touch()

        deadline = time.monotonic() + spec.timeout_s + 60
        docker_parties = [p for p in plan.parties if p.runtime == "docker"]
        first_failure = None   # when the first party ended with an error
        stopped_peers = False
        while any(pr.poll() is None for pr in procs.values()):
            if time.monotonic() > deadline:
                raise RunError("run exceeded timeout")
            # A party that failed (for example a protocol abort before it listens) can leave its peers waiting
            # forever. Give them a short time to notice, then stop them instead of waiting for the full timeout.
            if first_failure is None:
                for p in plan.parties:
                    mf = run_dir / f"party_{p.idx}" / "metrics.json"
                    if mf.exists():
                        try:
                            code = json.loads(mf.read_text()).get("exit_code")
                        except ValueError:
                            continue
                        if code not in (0, None):
                            first_failure = time.monotonic()
                            break
            elif not stopped_peers and time.monotonic() - first_failure > 15:
                kill_run_containers(run_id)
                for pr in procs.values():
                    if pr.poll() is None:
                        pr.kill()
                stopped_peers = True
            # Containers linger after their party finishes (see psi_wrap step 6); release them
            # once every docker party has written its metrics or died.
            if docker_parties and not (run_dir / "sync" / "done").exists():
                if all((run_dir / f"party_{p.idx}" / "metrics.json").exists() or procs[p.idx].poll() is not None
                       for p in docker_parties):
                    (run_dir / "sync" / "done").touch()
            time.sleep(0.01)
    except BaseException:
        kill_run_containers(run_id)
        for pr in procs.values():
            if pr.poll() is None:
                pr.kill()
        raise
    finally:
        for f in errs.values():
            f.close()

    out: dict[int, dict] = {}
    for p in plan.parties:
        mf = run_dir / f"party_{p.idx}" / "metrics.json"
        if mf.exists():
            out[p.idx] = json.loads(mf.read_text())
        else:
            out[p.idx] = {"exit_code": procs[p.idx].returncode if procs[p.idx].returncode else -1, "missing_metrics": True}
    return out


def _party_row(p: PartyPlan, m: dict, run_dir: Path, collected: Collected, use_cgroup_peak: bool = False) -> dict:
    if use_cgroup_peak and m.get("cgroup_peak_kb"):
        m = {**m, "maxrss_kb": max(m.get("maxrss_kb") or 0, m["cgroup_peak_kb"])}
    net = m.get("net") or {}
    tx = sum(v["tx_bytes"] for v in net.values()) if net else None
    rx = sum(v["rx_bytes"] for v in net.values()) if net else None
    txp = sum(v["tx_packets"] for v in net.values()) if net else None
    rxp = sum(v["rx_packets"] for v in net.values()) if net else None
    return dict(
        role=p.role, runtime=p.runtime, exit_code=m.get("exit_code"),
        start_epoch=m.get("start_epoch"), end_epoch=m.get("end_epoch"), wall_s=m.get("wall_s"),
        user_s=m.get("user_s"), sys_s=m.get("sys_s"), maxrss_kb=m.get("maxrss_kb"),
        cgroup_peak_kb=m.get("cgroup_peak_kb"), tx_bytes=tx, rx_bytes=rx, tx_packets=txp, rx_packets=rxp,
        reported=collected.party_reported.get(p.idx), mem_timeline=m.get("mem_timeline"),
        netem_stats=m.get("netem_stats"), log_path=str(run_dir / f"party_{p.idx}" / "stdout.log"),
    )


_SNAP_CACHE: dict = {}


def environment() -> tuple[dict, str]:
    if "snap" not in _SNAP_CACHE:
        snap = envinfo.snapshot()
        _SNAP_CACHE["snap"] = (snap, envinfo.snapshot_hash(snap))
    return _SNAP_CACHE["snap"]


def run_once(spec: RunSpec, group_id: str | None = None, rep_index: int = 0, warmup: bool = False,
             suite: str | None = None, label: str | None = None) -> int:
    adapter = get_adapter(spec.protocol)
    adapter.validate(spec)
    if spec.network not in config.NETWORK_PROFILES:
        raise ValueError(f"unknown network profile {spec.network!r}")
    config.ensure_dirs()
    snap, h = environment()
    cpus = spec.cpus or config.performance_cores()
    meta_truth = None
    if spec.dataset_dir:
        meta_truth = len((Path(spec.dataset_dir) / "truth.csv").read_text().split())

    with db.connect() as conn:
        env_id = db.get_or_create_env(conn, h, snap)
        run_id = db.start_run(
            conn, group_id=group_id, rep_index=rep_index, warmup=warmup, protocol=spec.protocol,
            n_parties=spec.n_parties, set_sizes=spec.sizes, true_intersection=meta_truth,
            network=spec.network, netem=config.NETWORK_PROFILES[spec.network], threads=spec.threads,
            cpus=cpus, params=spec.params, dataset=str(spec.dataset_dir) if spec.dataset_dir else None,
            env_id=env_id, host_state=envinfo.host_state(cpus), suite=suite, label=label,
        )
    run_dir = config.RUNS_DIR / f"{run_id:06d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    status, error = "ok", None
    metrics: dict[int, dict] = {}
    plan = None
    collected = Collected()
    try:
        plan = adapter.plan(spec)
        metrics = execute_plan(plan, spec, run_id, run_dir)
        bad = {i: m.get("exit_code") for i, m in metrics.items() if m.get("exit_code") != 0}
        if any(m.get("timed_out") for m in metrics.values()):
            status, error = "timeout", f"exceeded {spec.timeout_s}s"
        elif bad:
            status, error = "failed", f"non-zero exit codes: {bad}"
        collected = adapter.collect(spec, plan, run_dir, metrics)
        msg = (collected.reported or {}).get("failure_message")
        if msg and status != "ok":
            error = f"{error}; {msg}"  # e.g. "PROTOCOL FAILURE: server bin overflow ..." instead of just exit codes
    except BaseException as e:  # noqa: BLE001  (record, then re-raise only Ctrl-C)
        status, error = ("failed", f"{type(e).__name__}: {e}")
        if isinstance(e, KeyboardInterrupt):
            status, error = "aborted", "interrupted"
            _record(run_id, plan, metrics, run_dir, collected, status, error)
            raise
    _record(run_id, plan, metrics, run_dir, collected, status, error)
    return run_id


def _record(run_id: int, plan: Plan | None, metrics: dict[int, dict], run_dir: Path,
            collected: Collected, status: str, error: str | None) -> None:
    with db.connect() as conn:
        fields: dict = {"status": status, "error": error, "run_dir": str(run_dir)}
        if plan and metrics:
            ms = [m for m in metrics.values() if m.get("start_epoch")]
            if ms:
                fields["wall_s"] = max(m["end_epoch"] for m in ms) - min(m["start_epoch"] for m in ms)
                fields["cpu_s"] = sum(m["user_s"] + m["sys_s"] for m in ms)
                rss = [max(m["maxrss_kb"], m.get("cgroup_peak_kb") or 0) if plan.use_cgroup_peak else m["maxrss_kb"] for m in ms]
                fields["peak_rss_kb_max"], fields["peak_rss_kb_sum"] = max(rss), sum(rss)
            # Total communication = bytes *delivered* (sum of rx over all parties, incl. TCP/IP headers).
            # tx can undercount under netem: packets still queued at process exit are not yet counted.
            wire = [sum(v["rx_bytes"] for v in m["net"].values()) for m in metrics.values() if m.get("net")]
            fields["comm_total_bytes"] = collected.comm_total_bytes if collected.comm_total_bytes is not None else (sum(wire) if wire else None)
            fields["comm_online_bytes"] = collected.comm_online_bytes
            for p in plan.parties:
                db.add_party(conn, run_id, idx=p.idx,
                             **_party_row(p, metrics.get(p.idx, {}), run_dir, collected, plan.use_cgroup_peak))
        if collected.check is not None:
            c = collected.check
            fields["correct"] = None if c.get("correct") is None else int(bool(c["correct"]))
            fields["check_detail"] = c
        fields["reported"] = collected.reported or None
        db.finish_run(conn, run_id, **fields)
