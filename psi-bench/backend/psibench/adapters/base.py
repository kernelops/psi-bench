"""Common types and the adapter interface every protocol implements."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RunSpec:
    protocol: str                      # volepsi | bzs | pepsi | pepsi-large
    sizes: list[int]                   # set size per party (party 0 = client/receiver)
    common: int = 0                    # planted intersection size (synthetic datasets)
    seed: int = 1
    dataset_dir: Path | None = None    # None for protocols that generate their own inputs (PEPSI)
    network: str = "none"              # none | lan | wan
    threads: int = 1
    cpus: str | None = None            # None -> P-cores
    params: dict = field(default_factory=dict)
    timeout_s: int = 1800

    @property
    def n_parties(self) -> int:
        return len(self.sizes)


@dataclass
class PartyPlan:
    idx: int
    role: str
    runtime: str                       # "docker" | "native"
    argv: list[str]
    image: str | None = None
    ip: str | None = None
    env: dict = field(default_factory=dict)
    announce: list[int] = field(default_factory=list)   # ports this party LISTENs on
    wait_for: list[str] = field(default_factory=list)   # marker files, e.g. "listen_p0_1212"
    start_delay_ms: int = 0                             # extra delay after the gate (stagger experiments)
    cwd: str | None = None             # native only
    result_file: str | None = None     # path of the output file relative to the party's out dir

    @property
    def tag(self) -> str:
        return f"p{self.idx}"


@dataclass
class Plan:
    parties: list[PartyPlan]
    cardinality_only: bool = False
    checkable: bool = True             # False when the protocol can't produce a real intersection
    use_cgroup_peak: bool = False      # a party runs several processes: take the container's memory peak


@dataclass
class Collected:
    """What an adapter extracts from a finished run."""
    reported: dict = field(default_factory=dict)             # run-level, protocol-reported values
    party_reported: dict = field(default_factory=dict)       # idx -> dict
    check: dict | None = None
    comm_total_bytes: int | None = None                      # overrides wire counters when set
    comm_online_bytes: int | None = None


class Adapter:
    name = ""
    min_parties = 2
    max_parties: int | None = 2

    def validate(self, spec: RunSpec) -> None:
        n = spec.n_parties
        if n < self.min_parties or (self.max_parties is not None and n > self.max_parties):
            hi = self.max_parties if self.max_parties is not None else "many"
            raise ValueError(f"{spec.protocol} supports {self.min_parties}..{hi} parties, got {n}")

    def plan(self, spec: RunSpec) -> Plan:  # pragma: no cover - interface
        raise NotImplementedError

    def collect(self, spec: RunSpec, plan: Plan, run_dir: Path, metrics: dict[int, dict]) -> Collected:  # pragma: no cover
        raise NotImplementedError
