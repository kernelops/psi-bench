# psibench

A benchmark harness and web UI for comparing three private set intersection (PSI) protocols under the same conditions:

| Protocol | Paper | Setting | Code |
|---|---|---|---|
| PEPSI | USENIX Security 2024 | two parties, unbalanced, homomorphic encryption | [RasoulAM/pepsi](https://github.com/RasoulAM/pepsi) |
| VOLE-PSI | EUROCRYPT 2021 | two parties, OKVS + subfield VOLE | [ladnir/volepsi](https://github.com/ladnir/volepsi) |
| BZS-MPSI | ACM CCS 2024 | three or more parties | [orzcy/BZS-MPSI](https://github.com/orzcy/BZS-MPSI) |

For every run it records wall time, CPU time, peak memory per party, bytes on the wire, correctness against a ground-truth
intersection, and a hardware/software snapshot, and stores everything in a SQLite history. It can run a single experiment from
the web UI or a whole suite of experiments from the command line.

The `psi-bench/` folder itself contains no code from the three protocols; it runs them from sibling folders. In the published
repository ([kernelops/psi-bench](https://github.com/kernelops/psi-bench)) the three projects are included next to it with their
original commit history (see `NOTICE` at the repository root).

## Layout

```
psi-bench/
  backend/psibench/   runner, metrics wrapper, adapters (one per protocol), SQLite history, FastAPI server
  frontend/           React + TypeScript web UI (Vite)
  suites/             experiment suites (JSON) used for the comparison
  docker/             Dockerfiles and build scripts for the three protocol images
  scripts/            run_comparison.sh, export_results.py, gen_smoke.py
  results/            exported results of the comparison suites (tables, CSV, environment)
  psibench            command line launcher        serve   web UI launcher
```

## Setup

The harness expects the three protocol folders **next to this folder** with exactly these names:

```
<repository root>/
  psi-bench/               <- this folder
  pepsi/                   <- RasoulAM/pepsi (+ the end-to-end driver in pepsi/e2e)
  volepsi/                 <- ladnir/volepsi
  BZS-MPSI/                <- orzcy/BZS-MPSI
```

If you cloned `kernelops/psi-bench`, this layout is already in place. If you use `psi-bench/` on its own, clone the three
projects next to it.

The results in `results/` were produced with these commits: `pepsi` d9cf35e, `volepsi` 1ecfe79, `BZS-MPSI` 096d4ad
(plus the end-to-end driver in `pepsi/e2e/`, see below). The harness records the commit of each protocol with every run.

What needs the sibling folders:

- **Building the Docker images** (below) needs all three. After that, runs only use the images.
- **The native PEPSI benchmark** (protocols `pepsi`, `pepsi-large`) runs the binaries in `pepsi/build/`.
- Viewing results, the UI, history and comparisons work without them.

Requirements: Linux, Docker (with permission to run it), Python 3.10 or newer (tested with 3.14), Node.js (tested with 24).
Network shaping uses `tc netem` inside the containers, so no root access on the host is needed beyond Docker.

```bash
# 1. Python environment for the API server
python3 -m venv .tools/venv
.tools/venv/bin/pip install -r requirements.txt

# 2. Docker images (VOLE-PSI, BZS-MPSI, and the PEPSI end-to-end driver). First build takes several minutes.
docker/build_images.sh            # or: docker/build_images.sh volepsi   (one at a time)

# 3. Web UI
cd frontend && npm install && npm run build && cd ..

# 4. (optional) upstream PEPSI benchmark binaries, only for the protocols "pepsi" and "pepsi-large"
cd ../pepsi && PATH="$PWD/../psi-bench/.tools/venv/bin:$PATH" cmake -S src -B build -G Ninja && cmake --build build && cd ../psi-bench
```

The PEPSI end-to-end driver is a new C++ program in `pepsi/e2e/` (new files only, nothing upstream is modified). It is
built inside Docker by step 2; it has to exist in your `pepsi/` checkout for the `pepsi-e2e` protocol to work.

## Use

Web UI (listens on 127.0.0.1:8765; chosen to avoid port 8080):

```bash
./serve                   # then open http://127.0.0.1:8765
```

Pages: **New run** (choose protocol, inputs, network, threads, repetitions), **Jobs** (queue, live log, cancel), **History**,
**Compare** (charts with 95% confidence intervals), **Experiments** (run and review suites), **Hardware** (environment snapshot).
Runs execute one at a time so they do not disturb each other's timings.

Command line:

```bash
./psibench env                                                    # hardware/software snapshot
./psibench run --protocol volepsi --sizes 1024,1048576 --elem-bits 32 --reps 5 --warmup 1
./psibench run --protocol pepsi-e2e --sizes 1024,1048576 --elem-bits 32 --threads 6 --param hash_index=1
./psibench run --protocol bzs-perf --sizes 65536x4 --network wan   # "65536x4" = 4 parties of 65536 elements
./psibench suite suites/two_party_32bit.json --skip-done           # a whole experiment suite
./psibench report --suite two-party-32bit                          # markdown comparison table
./psibench history        ./psibench show <run-id> -v
```

Your own data: `./psibench import --name mydata a.txt b.txt` (one element per line, one file per party; non-hex elements are
hashed to 128 bits and the true intersection is computed) or use *Upload my files* in the UI.

### Protocols

| id | what it runs | notes |
|---|---|---|
| `pepsi-e2e` | PEPSI driver on real files, client and server in separate containers | plain PSI only; `hash_index=1` is needed for correctness with 32-bit elements |
| `volepsi` | VOLE-PSI file mode, two containers | single-threaded |
| `volepsi-perf` | VOLE-PSI authors' benchmark: both parties in one process, in-memory socket | no real network; no correctness check |
| `bzs-perf` | BZS-MPSI authors' benchmark mode, one container per party | equal power-of-two set sizes; intersection size checked |
| `volepsi-star` | baseline: leader runs n-1 parallel VOLE-PSI instances | leader learns each pairwise intersection (weaker privacy) |
| `bzs` | BZS-MPSI file mode | **unreliable**: crashes intermittently, and always under WAN shaping, including in the authors' own setup |
| `pepsi`, `pepsi-large` | upstream PEPSI benchmark binaries | synthetic data, one process plays both roles, no result decoding |

### What is measured

- **Wall time:** first party start to last party finish, inside the containers (Docker startup is excluded; all parties are
  released together).
- **CPU time:** user + system of all parties. **Peak memory:** largest resident set size of any party.
- **Communication:** bytes delivered on the network interfaces of all parties, including TCP/IP headers (about 0.5% above
  the payload). For the native PEPSI benchmark, which has no network, the protocol's own serialized sizes are used.
- **Correctness:** the output is compared with the ground-truth intersection; wrong results are recorded and flagged.
- **Network profiles** (applied to every party's outgoing traffic, same numbers as the BZS-MPSI paper): `lan` = 10 Gbit/s,
  0.01 ms one-way; `wan` = 200 Mbit/s, 48 ms one-way.
- **CPU pinning:** containers are pinned to the P-cores (autodetected; all cores on non-hybrid CPUs).

Not measured: energy (the RAPL counters need root) and hardware performance counters.

## Results

`results/` has the tables (`*.md`, `*.tex`), every individual run (`runs_suites.csv`), the environment
(`environment.json`) and the conditions during measurement (`CONDITIONS.md`). Regenerate them from the database with
`python3 scripts/export_results.py`. **Read `CONDITIONS.md` first:** the measurements were taken on a machine that was not
idle, so they are indicative.

Summary of what the data shows (details and caveats in `results/`):

- VOLE-PSI is faster and lighter than PEPSI in every two-party setting tested, including the small-client, large-server
  case PEPSI targets; PEPSI uses less communication once the server set is around 2^20 elements or larger.
- Against a naive star of two-party VOLE-PSI runs, BZS-MPSI uses less CPU and memory as parties are added, but was slower
  under WAN shaping.
- Two findings about PEPSI as described in the paper: without the hash-function index in the stored value, the 32-bit setting
  produced false positives; and dividing by h! on the server exhausted the noise budget with the parameters in the code.

## Known limitations

- Linux only (uses Docker, `/proc`, cgroups v2).
- The three protocols are built with different compilers (GCC 13, GCC 13, GCC 11) because their pinned dependencies require
  it; this is recorded in the environment snapshot.
- The PEPSI driver implements plain PSI only (no labelled PSI, sum or cardinality), is semi-honest, and does not implement
  circuit privacy (noise flooding), like the upstream code. Sizes above 2^22 for the server were not tested.
- Results depend on the machine; compare protocols only within one set of runs.

## License and attribution

The harness (`psi-bench/`) and the PEPSI end-to-end driver (`pepsi/e2e/`) are released under the MIT license (see `LICENSE`
at the repository root). The three protocols keep their own licenses: VOLE-PSI and BZS-MPSI are MIT; the upstream PEPSI
repository has no license file (see `NOTICE`). Cite the original papers when using results from this harness.
