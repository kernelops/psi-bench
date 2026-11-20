"""Catalogue of the protocols for the UI: what each one is, how it runs, and which options it accepts.

The UI renders the run form from this description, so adding a protocol option only needs an entry here
(plus handling in the adapter).
"""
from __future__ import annotations

NETWORKS = [
    {"id": "none", "label": "No shaping (local bridge)", "help": "Containers on a Docker bridge, no added delay."},
    {"id": "lan", "label": "LAN: 10 Gbit/s, 0.01 ms one-way", "help": "Same profile as the BZS-MPSI paper."},
    {"id": "wan", "label": "WAN: 200 Mbit/s, 48 ms one-way", "help": "Same profile as the BZS-MPSI paper (96 ms RTT)."},
]

PROTOCOLS = [
    {
        "id": "pepsi-e2e",
        "name": "PEPSI (end-to-end driver)",
        "family": "PEPSI",
        "mode": "files",
        "summary": "Unbalanced two-party PSI from homomorphic encryption (USENIX Security 2024). Real input files, client and server in separate containers.",
        "min_parties": 2, "max_parties": 2,
        "party_roles": ["client (smaller set, learns the result)", "server (larger set)"],
        "uses_dataset": True, "supports_network": True, "supports_threads": True,
        "check": "Result compared with the ground-truth intersection.",
        "params": [
            {"key": "hash_index", "label": "Include hash-function index in stored value", "type": "bool", "default": True,
             "help": "Needed for correctness with 32-bit elements; off reproduces the paper literally (false positives). Costs ~10% more communication."},
            {"key": "lambda", "label": "Element bit length", "type": "select", "default": "auto", "options": ["auto", "32"],
             "help": "auto = Lemma 1 (alpha + log2(bins*mu)) for large elements; 32 = the paper's 32-bit setting. A 32-bit dataset selects 32 automatically."},
            {"key": "hw", "label": "Hamming weight", "type": "select", "default": "auto", "options": ["auto", "8", "16", "23"],
             "help": "auto: 8 for 32-bit elements, 16 for large elements."},
            {"key": "alpha", "label": "Statistical failure exponent alpha", "type": "number", "default": 40},
            {"key": "cmax", "label": "Maximum client set size (public)", "type": "number", "default": 4096,
             "help": "Fixes the number of bins; the server preprocesses for this bound."},
            {"key": "precompute", "label": "Precompute server plaintexts", "type": "select", "default": "auto", "options": ["auto", "0", "1"],
             "help": "Offline phase stores all encoded plaintexts (memory heavy for large servers)."},
            {"key": "server_scale", "label": "Divide by h! on the server (paper Algorithm 1)", "type": "bool", "default": False,
             "help": "Exhausts the noise budget with the code's parameters; leave off."},
        ],
    },
    {
        "id": "volepsi",
        "name": "VOLE-PSI (file mode, two containers)",
        "family": "VOLE-PSI",
        "mode": "files",
        "summary": "Two-party PSI from OKVS + subfield VOLE (Rindal and Rosulek). Real input files over TCP, one container per party.",
        "min_parties": 2, "max_parties": 2,
        "party_roles": ["receiver (learns the result)", "sender"],
        "uses_dataset": True, "supports_network": True, "supports_threads": False,
        "check": "Result compared with the ground-truth intersection.",
        "params": [
            {"key": "malicious", "label": "Malicious security", "type": "bool", "default": False},
            {"key": "okvs", "label": "OKVS", "type": "select", "default": "baxos", "options": ["baxos", "ribbon"]},
            {"key": "receiver", "label": "Receiver party", "type": "select", "default": "0", "options": ["0", "1"],
             "help": "Which input file plays the receiver (the party that learns the intersection)."},
        ],
        "notes": "File mode is single-threaded.",
    },
    {
        "id": "volepsi-perf",
        "name": "VOLE-PSI (authors' benchmark mode)",
        "family": "VOLE-PSI",
        "mode": "benchmark",
        "summary": "The authors' -perf -psi benchmark: both parties in one process with an in-memory socket, random equal-size sets.",
        "min_parties": 2, "max_parties": 2,
        "uses_dataset": False, "supports_network": False, "supports_threads": True,
        "size_rule": "equal sizes, power of two",
        "check": "No correctness check (random sets, intersection undefined).",
        "params": [
            {"key": "malicious", "label": "Malicious security", "type": "bool", "default": False},
            {"key": "okvs", "label": "OKVS", "type": "select", "default": "baxos", "options": ["baxos", "ribbon"]},
            {"key": "fakeBase", "label": "Fake base OTs", "type": "bool", "default": False},
        ],
        "notes": "No real network: the network profile has no effect. CPU and memory cover both parties together.",
    },
    {
        "id": "bzs-perf",
        "name": "BZS-MPSI (authors' benchmark mode)",
        "family": "BZS-MPSI",
        "mode": "benchmark",
        "summary": "Multi-party PSI from bicentric zero-sharing (CCS 2024) in the authors' -perf mode: one container per party over TCP, random sets with a planted intersection.",
        "min_parties": 3, "max_parties": None,
        "party_roles": ["clients ... pivot, leader (last party learns the result)"],
        "uses_dataset": False, "supports_network": True, "supports_threads": True,
        "size_rule": "equal sizes, power of two",
        "check": "The leader's reported intersection size must equal the planted size.",
        "params": [
            {"key": "ca", "label": "Cardinality only (MPSI-CA)", "type": "bool", "default": False},
            {"key": "bc", "label": "Leader broadcasts the result", "type": "bool", "default": False},
            {"key": "la", "label": "Statistical security parameter", "type": "number", "default": 40},
        ],
    },
    {
        "id": "bzs",
        "name": "BZS-MPSI (file mode, experimental)",
        "family": "BZS-MPSI",
        "mode": "files",
        "summary": "BZS-MPSI on real input files. Unreliable: crashes intermittently, and always under WAN shaping, even in the authors' own setup.",
        "min_parties": 3, "max_parties": None,
        "uses_dataset": True, "supports_network": True, "supports_threads": True,
        "check": "Leader's output compared with the ground-truth intersection.",
        "experimental": True,
        "params": [
            {"key": "ca", "label": "Cardinality only (MPSI-CA)", "type": "bool", "default": False},
            {"key": "bc", "label": "Leader broadcasts the result", "type": "bool", "default": False},
        ],
    },
    {
        "id": "volepsi-star",
        "name": "Baseline: star of two-party VOLE-PSI",
        "family": "VOLE-PSI",
        "mode": "files",
        "summary": "Naive multi-party reference: the leader runs one VOLE-PSI per other party in parallel and intersects the results. The leader learns every pairwise intersection.",
        "min_parties": 3, "max_parties": None,
        "uses_dataset": True, "supports_network": True, "supports_threads": False,
        "check": "Leader's output compared with the ground-truth intersection.",
        "params": [],
    },
    {
        "id": "pepsi",
        "name": "PEPSI (upstream benchmark, synthetic)",
        "family": "PEPSI",
        "mode": "benchmark",
        "summary": "The released PEPSI benchmark (main-psi): synthetic inputs, one process plays both roles, no result decoding.",
        "min_parties": 2, "max_parties": 2,
        "uses_dataset": False, "supports_network": False, "supports_threads": True,
        "check": "None (benchmark only).",
        "params": [
            {"key": "task", "label": "Task", "type": "select", "default": "PSI",
             "options": ["PSI", "LabelledPSI", "PSICardinality", "PSISum"]},
            {"key": "label_bytes", "label": "Label size (bytes)", "type": "number", "default": 1},
        ],
        "notes": "Communication comes from PEPSI's own report. Native run (no container).",
    },
    {
        "id": "pepsi-large",
        "name": "PEPSI large elements (upstream benchmark, synthetic)",
        "family": "PEPSI",
        "mode": "benchmark",
        "summary": "The released main-psi-large benchmark (N=16384, h=16, lambda from Lemma 1), synthetic inputs.",
        "min_parties": 2, "max_parties": 2,
        "uses_dataset": False, "supports_network": False, "supports_threads": True,
        "check": "None (benchmark only).",
        "params": [
            {"key": "task", "label": "Task", "type": "select", "default": "PSISum",
             "options": ["PSI", "LabelledPSI", "PSICardinality", "PSISum"]},
        ],
        "notes": "Native run (no container).",
    },
]


def by_id(pid: str) -> dict | None:
    return next((p for p in PROTOCOLS if p["id"] == pid), None)


def coerce_params(pid: str, raw: dict) -> dict:
    """Convert UI values to the types adapters expect; drop unknown or default 'auto' values."""
    info = by_id(pid)
    if not info:
        raise ValueError(f"unknown protocol {pid}")
    out: dict = {}
    spec = {p["key"]: p for p in info["params"]}
    for k, v in (raw or {}).items():
        p = spec.get(k)
        if not p or v is None or v == "":
            continue
        if p["type"] == "bool":
            out[k] = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "yes", "on")
        elif p["type"] == "number":
            out[k] = int(float(v))
        else:
            if v == "auto":
                continue
            out[k] = int(v) if isinstance(v, str) and v.isdigit() and k in ("hw", "lambda", "receiver") else v
    return out
