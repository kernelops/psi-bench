"""Hardware/software snapshot stored with every run.

`snapshot()` is stable (hashable, deduplicated in the DB). `host_state()` holds
volatile values (load, free memory, CPU frequency) that are stored per run.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path

from . import config


def _run(cmd: list[str], timeout: float = 20.0, cwd: Path | None = None) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return (r.stdout or r.stderr).strip()
    except Exception as e:  # missing tool, timeout, ...
        return f"unavailable ({type(e).__name__})"


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def _lscpu() -> dict[str, str]:
    out = {}
    for line in _run(["lscpu"]).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _os_pretty() -> str:
    for line in (_read("/etc/os-release") or "").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip('"')
    return platform.platform()


def _cpu_flags() -> list[str]:
    info = _read("/proc/cpuinfo") or ""
    m = re.search(r"^flags\s*:\s*(.*)$", info, re.M)
    flags = set(m.group(1).split()) if m else set()
    interesting = ["avx", "avx2", "avx512f", "avx_vnni", "aes", "pclmulqdq", "bmi2", "sha_ni"]
    return [f for f in interesting if f in flags]


def _git(repo: Path) -> dict:
    if (repo / ".git").exists():  # a separate clone of the protocol
        commit = _run(["git", "rev-parse", "HEAD"], cwd=repo)
        dirty = bool(_run(["git", "status", "--porcelain"], cwd=repo))
        return {"commit": commit, "dirty": dirty, "subject": _run(["git", "log", "-1", "--format=%s"], cwd=repo)}
    if not repo.exists():
        return {"commit": None, "dirty": None}
    # The protocol lives inside a larger repository, imported with `git subtree add`: the import merge commit's second
    # parent is the upstream commit (imported commits keep their original paths, so a path search cannot find them).
    merge = _run(["git", "log", "-1", "--merges", "--format=%H", "--", "."], cwd=repo)
    if not re.fullmatch(r"[0-9a-f]{40}", merge):
        return {"commit": None, "dirty": None}
    upstream = _run(["git", "rev-parse", f"{merge}^2"], cwd=repo)
    if not re.fullmatch(r"[0-9a-f]{40}", upstream):
        return {"commit": None, "dirty": None}
    later = _run(["git", "rev-list", "--no-merges", f"{merge}..HEAD", "--", "."], cwd=repo).split()
    return {"commit": upstream, "dirty": bool(_run(["git", "status", "--porcelain", "--", "."], cwd=repo)),
            "subject": _run(["git", "log", "-1", "--format=%s", upstream], cwd=repo),
            "local_commits_on_top": len(later)}


def _image_info(image: str) -> dict:
    image_id = _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
    if image_id.startswith("unavailable") or "Error" in image_id:
        return {"image_id": None}
    gcc = _run(["docker", "run", "--rm", "--entrypoint", "g++", image, "--version"]).splitlines()
    cmake = _run(["docker", "run", "--rm", "--entrypoint", "cmake", image, "--version"]).splitlines()
    os_rel = _run(["docker", "run", "--rm", "--entrypoint", "sh", image, "-c", ". /etc/os-release; echo $PRETTY_NAME"])
    return {
        "image_id": image_id.replace("sha256:", "")[:12],
        "os": os_rel,
        "gcc": gcc[0] if gcc else None,
        "cmake": cmake[0] if cmake else None,
    }


def _pepsi_build() -> dict:
    cache = config.PEPSI_BUILD / "CMakeCache.txt"
    out: dict = {"built": cache.exists()}
    if not cache.exists():
        return out
    text = cache.read_text(errors="replace")
    for key in ("CMAKE_BUILD_TYPE", "CMAKE_CXX_FLAGS", "CMAKE_CXX_FLAGS_RELEASE", "SEAL_USE_INTEL_HEXL", "CMAKE_CXX_COMPILER"):
        m = re.search(rf"^{key}(?::\w+)?=(.*)$", text, re.M)
        if m:
            out[key] = m.group(1)
    seal_cfg = config.PEPSI_BUILD / "_deps" / "seal-build" / "native" / "src" / "seal" / "util" / "config.h"
    m = re.search(r'#define SEAL_VERSION "([^"]+)"', seal_cfg.read_text(errors="replace")) if seal_cfg.exists() else None
    out["seal_version"] = m.group(1) if m else None
    return out


def snapshot(include_images: bool = True) -> dict:
    lscpu = _lscpu()
    topo = {}
    for name, path in (("p_cores", "cpu_core"), ("e_cores", "cpu_atom"), ("lp_e_cores", "cpu_lowpower")):
        v = _read(f"/sys/devices/{path}/cpus")
        if v:
            topo[name] = v
    mem_kb = 0
    for line in (_read("/proc/meminfo") or "").splitlines():
        if line.startswith("MemTotal:"):
            mem_kb = int(line.split()[1])
    snap = {
        "cpu": {
            "model": lscpu.get("Model name"),
            "logical_cpus": os.cpu_count(),
            "threads_per_core": lscpu.get("Thread(s) per core"),
            "l2_cache": lscpu.get("L2 cache"),
            "l3_cache": lscpu.get("L3 cache"),
            "topology": topo,
            "flags": _cpu_flags(),
        },
        "memory_total_gb": round(mem_kb / 1024 / 1024, 1),
        "os": _os_pretty(),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "docker": _run(["docker", "version", "--format", "{{.Server.Version}}"]),
        "host_gcc": (_run(["g++", "--version"]).splitlines() or [None])[0],
        "repos": {name: _git(path) for name, path in config.REPOS.items()},
        "pepsi_build": _pepsi_build(),
        "pinned_cpus_default": config.performance_cores(),
    }
    if include_images:
        snap["images"] = {name: _image_info(img) for name, img in config.IMAGES.items()}
    return snap


def snapshot_hash(snap: dict) -> str:
    return hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()[:16]


def host_state(cpus: str | None = None) -> dict:
    """Volatile conditions at run start; useful to explain outliers."""
    load = os.getloadavg()
    mem = {}
    for line in (_read("/proc/meminfo") or "").splitlines():
        if line.startswith(("MemAvailable:", "MemFree:")):
            k, v = line.split(":")
            mem[k] = int(v.split()[0])
    freqs = {}
    for cpu in _expand_cpus(cpus or config.performance_cores()):
        v = _read(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq")
        if v:
            freqs[cpu] = int(v) // 1000
    return {
        "loadavg": [round(x, 2) for x in load],
        "mem_available_mb": mem.get("MemAvailable", 0) // 1024,
        "governor": _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
        "cur_mhz": freqs,
        "running_containers": len(_run(["docker", "ps", "-q"]).split()),
    }


def _expand_cpus(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part.strip():
            out.append(int(part))
    return out
