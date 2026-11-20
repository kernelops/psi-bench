"""Paths, images, network profiles. Everything machine-specific lives here."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # .../psi-bench
WORKSPACE = ROOT.parent  # .../German-Project

DATA_DIR = Path(os.environ.get("PSIBENCH_DATA", ROOT / "data"))
DATASETS_DIR = DATA_DIR / "datasets"
RUNS_DIR = DATA_DIR / "runs"
DB_PATH = DATA_DIR / "history.db"

REPOS = {
    "pepsi": WORKSPACE / "pepsi",
    "volepsi": WORKSPACE / "volepsi",
    "bzs": WORKSPACE / "BZS-MPSI",
}

# Docker images built from docker/Dockerfile.* (see psi-bench/docker).
IMAGES = {"volepsi": "psi-volepsi", "bzs": "psi-bzs", "pepsi": "psi-pepsi"}
PEPSI_E2E_IN_IMAGE = "/app/pepsi/build-e2e/pepsi_e2e"
FRONTEND_IN_IMAGE = {
    "volepsi": "/app/volepsi/out/build/linux/frontend/frontend",
    "bzs": "/app/BZS-MPSI/out/build/linux/frontend/frontend",
}

PEPSI_BUILD = REPOS["pepsi"] / "build"
PEPSI_BINARIES = {"pepsi": "main-psi", "pepsi-large": "main-psi-large"}

WRAPPER_PATH = Path(__file__).resolve().parent / "psi_wrap.py"

# Dedicated bridge network with static IPs. Docker's default pools use
# 172.17-172.21 on this host, so 172.30.0.0/24 does not collide.
NET_NAME = "psibench-net"
NET_SUBNET = "172.30.0.0/24"
NET_FIRST_HOST = 10  # party i gets 172.30.0.(10+i)


def party_ip(i: int) -> str:
    return f"172.30.0.{NET_FIRST_HOST + i}"


# netem is applied on every party's egress, so each direction is shaped once.
# That gives the same one-way delay as BZS-MPSI's `tc ... dev lo` profiles.
NETWORK_PROFILES: dict[str, str | None] = {
    "none": None,
    "lan": "limit 100000 delay 0.01ms rate 10gbit",
    "wan": "limit 100000 delay 48ms rate 200mbit",
}


def performance_cores() -> str:
    """CPU list of the P-cores on hybrid Intel CPUs, else all CPUs."""
    p = Path("/sys/devices/cpu_core/cpus")
    if p.exists():
        return p.read_text().strip()
    return f"0-{(os.cpu_count() or 1) - 1}"


def ensure_dirs() -> None:
    for d in (DATA_DIR, DATASETS_DIR, RUNS_DIR):
        d.mkdir(parents=True, exist_ok=True)
