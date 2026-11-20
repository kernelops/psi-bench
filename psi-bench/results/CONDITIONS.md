# Measurement conditions

Recorded for 256 suite runs (including warm-ups). Values are read at the start of each run.

- 1-minute load average at run start: median 8.1, min 3.7, max 13.8
- other Docker containers running at run start: min 6, max 6
- CPU frequency governor: powersave
- instantaneous frequency of the pinned P-cores: min 400 MHz, max 4700 MHz

The load average includes the benchmark runs that came just before (a 6-thread PEPSI run alone adds about 6),
so it overstates outside load. The outside factor is the other running containers (here an unrelated
Airflow stack) plus the `powersave` governor, which lets the core frequency swing widely. The machine was
therefore not quiet: timings are indicative and absolute numbers will differ on an idle machine.
To replace them, stop other workloads, set the governor to `performance` if possible, and re-run a suite
without `--skip-done` (the report always uses the most recent group of each experiment).

Protocol builds differ in compiler (VOLE-PSI and PEPSI driver: GCC 13 on Ubuntu 24.04; BZS-MPSI: GCC 11 on
Ubuntu 22.04) because the pinned dependencies require it. See environment.json.
