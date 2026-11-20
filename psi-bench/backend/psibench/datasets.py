"""Input sets, ground truth and result checking.

A dataset is a directory with `party_<i>.csv` (one 32-hex-char element per
line, the format VOLE-PSI and BZS-MPSI read), `truth.csv` (the true
intersection of all parties) and `meta.json`.

Party 0 is always the smallest set / the PSI client / receiver. For BZS-MPSI the
last party is the Leader (it learns the result).
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from pathlib import Path

from . import config

HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")


def dataset_name(sizes: list[int], common: int, seed: int, elem_bits: int = 128) -> str:
    name = "syn_" + "-".join(str(s) for s in sizes) + f"_c{common}_s{seed}"
    return name if elem_bits == 128 else name + f"_b{elem_bits}"


def generate(sizes: list[int], common: int, seed: int = 1, root: Path | None = None, elem_bits: int = 128) -> Path:
    """Create (or reuse) a synthetic dataset. By default elements are random 128-bit values, so the
    all-party intersection is exactly the `common` planted elements. With elem_bits < 128, elements
    are distinct random integers below 2**elem_bits (zero-padded to 32 hex chars), e.g. the paper's
    32-bit setting; they are sampled without replacement so the intersection is still exact."""
    if common > min(sizes):
        raise ValueError("common must be <= the smallest set size")
    if not 8 <= elem_bits <= 128:
        raise ValueError("elem_bits must be in [8, 128]")
    root = root or config.DATASETS_DIR
    out = root / dataset_name(sizes, common, seed, elem_bits)
    if (out / "meta.json").exists():
        return out
    tmp = out.with_suffix(".tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    if elem_bits == 128:
        def draw(k: int) -> list[str]:
            return [rng.randbytes(16).hex() for _ in range(k)]
        shared = draw(common)
        parts = [shared + draw(size - common) for size in sizes]
    else:
        total = common + sum(size - common for size in sizes)
        if total > 2 ** elem_bits:
            raise ValueError(f"need {total} distinct elements but only 2**{elem_bits} exist")
        vals = rng.sample(range(2 ** elem_bits), total)
        hexs = [f"{v:032x}" for v in vals]
        shared, pos, parts = hexs[:common], common, []
        for size in sizes:
            parts.append(shared + hexs[pos:pos + size - common])
            pos += size - common
    for i, elems in enumerate(parts):
        rng.shuffle(elems)
        (tmp / f"party_{i}.csv").write_text("\n".join(elems) + "\n")
    (tmp / "truth.csv").write_text("\n".join(sorted(shared)) + ("\n" if shared else ""))
    meta = {"kind": "synthetic", "sizes": sizes, "common": common, "seed": seed, "elem_bits": elem_bits,
            "parties": len(sizes), "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (tmp / "meta.json").write_text(json.dumps(meta, indent=2))
    tmp.rename(out)
    return out


def element_to_hex(raw: str) -> str:
    """Map an arbitrary string to a 128-bit hex element (SHA-256, truncated)."""
    return hashlib.sha256(raw.encode()).digest()[:16].hex()


def import_files(paths: list[Path], name: str, hash_elements: bool = True, root: Path | None = None) -> Path:
    """Register user files (one element per line) as a dataset.

    Non-hex elements are hashed to 128 bits; `mapping.tsv` keeps hash -> original
    so results can be shown in the original form. Ground truth is computed here.
    """
    root = root or config.DATASETS_DIR
    out = root / name
    out.mkdir(parents=True, exist_ok=True)
    sets: list[set[str]] = []
    mapping: dict[str, str] = {}
    sizes = []
    for i, p in enumerate(paths):
        elems: list[str] = []
        seen: set[str] = set()
        for line in Path(p).read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            h = line.lower() if HEX32.match(line) else (element_to_hex(line) if hash_elements else None)
            if h is None:
                raise ValueError(f"{p}: element {line!r} is not 32 hex chars (use hashing)")
            if h in seen:
                continue  # sets, not multisets
            seen.add(h)
            elems.append(h)
            if h != line.lower():
                mapping[h] = line
        (out / f"party_{i}.csv").write_text("\n".join(elems) + "\n")
        sets.append(seen)
        sizes.append(len(elems))
    truth = set.intersection(*sets) if sets else set()
    (out / "truth.csv").write_text("\n".join(sorted(truth)) + ("\n" if truth else ""))
    if mapping:
        (out / "mapping.tsv").write_text("\n".join(f"{h}\t{o}" for h, o in mapping.items()) + "\n")
    meta = {"kind": "imported", "sizes": sizes, "common": len(truth), "parties": len(paths), "sources": [str(p) for p in paths], "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return out


def load_meta(dataset_dir: Path) -> dict:
    return json.loads((Path(dataset_dir) / "meta.json").read_text())


def _norm(s: str) -> str:
    s = s.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    return s.zfill(32) if re.fullmatch(r"[0-9a-f]{1,32}", s) else s


def check_result(dataset_dir: Path, result_file: Path, cardinality_only: bool = False) -> dict:
    """Compare a protocol's output with the ground truth."""
    truth = {_norm(l) for l in (Path(dataset_dir) / "truth.csv").read_text().split() if l.strip()}
    if not Path(result_file).exists():
        return {"correct": False, "reason": "no output file"}
    text = Path(result_file).read_text().split()
    if cardinality_only:
        got = int(text[0]) if text else -1
        return {"correct": got == len(truth), "reported_cardinality": got, "true_cardinality": len(truth)}
    got_list = [_norm(l) for l in text]
    got = set(got_list)
    tp = len(got & truth)
    fp = len(got - truth)
    fn = len(truth - got)
    return {
        "correct": fp == 0 and fn == 0,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": tp / len(got) if got else (1.0 if not truth else 0.0),
        "recall": tp / len(truth) if truth else 1.0,
        "duplicates_in_output": len(got_list) - len(got),
    }
