#!/usr/bin/env python3
"""Per-party measurement wrapper. Runs inside a container (or natively).

Standard library only and Python 3.10 compatible, because it is executed with
the container's own python3 (Ubuntu 22.04: 3.10, 24.04: 3.12).

What it does, in order:
  1. optionally shapes egress traffic with `tc netem` (needs NET_ADMIN + root),
  2. optionally announces listening ports by writing marker files in a shared
     sync dir (so peers can connect without probing the port),
  3. signals `ready_<tag>` and waits for the orchestrator's `go` file, then for
     every `--wait-for` marker file,
  4. forks the real command (dropping to --uid/--gid, pinned to --cpus),
  5. measures it: exact wall time, rusage (user/sys CPU, peak RSS), an RSS and
     CPU timeline, and the byte/packet counters of every non-loopback interface,
  6. writes everything to --out as JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time

CLK_TCK = os.sysconf("SC_CLK_TCK")


def parse_cpus(spec: str) -> set[int]:
    cpus: set[int] = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            cpus.update(range(int(a), int(b) + 1))
        elif part.strip():
            cpus.add(int(part))
    return cpus


def read_netdev() -> dict:
    out = {}
    with open("/proc/net/dev") as f:
        for line in f.readlines()[2:]:
            name, data = line.split(":", 1)
            p = data.split()
            out[name.strip()] = {
                "rx_bytes": int(p[0]), "rx_packets": int(p[1]),
                "tx_bytes": int(p[8]), "tx_packets": int(p[9]),
            }
    return out


def net_delta(before: dict, after: dict) -> dict:
    res = {}
    for iface, a in after.items():
        if iface == "lo":
            continue
        b = before.get(iface, {k: 0 for k in a})
        res[iface] = {k: a[k] - b[k] for k in a}
    return res


def listening_ports() -> set[int]:
    ports = set()
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path) as f:
                next(f)
                for line in f:
                    cols = line.split()
                    if cols[3] == "0A":  # LISTEN
                        ports.add(int(cols[1].rsplit(":", 1)[1], 16))
        except OSError:
            pass
    return ports


def proc_sample(pid: int):
    """(rss_kb, cpu_seconds, threads) of pid, or None if it is gone."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            stat = f.read()
        rest = stat[stat.rindex(")") + 2:].split()
        cpu = (int(rest[11]) + int(rest[12])) / CLK_TCK  # utime + stime
        rss = threads = None
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1])
                elif line.startswith("Threads:"):
                    threads = int(line.split()[1])
        return rss or 0, cpu, threads or 0
    except (OSError, ValueError, IndexError):
        return None


def chown_if(path: str, uid, gid) -> None:
    if uid is not None:
        try:
            os.chown(path, uid, gid if gid is not None else -1)
        except OSError:
            pass


def wait_for_file(path: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.0005)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--log")
    ap.add_argument("--tag", default="p")
    ap.add_argument("--sync-dir")
    ap.add_argument("--announce", default="", help="comma list of ports this party will LISTEN on")
    ap.add_argument("--wait-for", action="append", default=[], help="marker file names in sync dir")
    ap.add_argument("--netem", default="")
    ap.add_argument("--uid", type=int)
    ap.add_argument("--gid", type=int)
    ap.add_argument("--cpus")
    ap.add_argument("--sample-ms", type=int, default=50)
    ap.add_argument("--timeout", type=float, default=0)
    ap.add_argument("--gate-timeout", type=float, default=120)
    ap.add_argument("--no-net", action="store_true", help="do not record interface counters (native runs share the host netns)")
    ap.add_argument("--start-delay-ms", type=int, default=0, help="extra delay after the gate, before launching")
    ap.add_argument("--cwd")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not cmd:
        print("psi_wrap: no command", file=sys.stderr)
        return 2

    result: dict = {"tag": args.tag, "cmd": cmd, "netem": args.netem or None, "cpus": args.cpus,
                    "start_delay_ms": args.start_delay_ms}

    # 1. traffic shaping (egress) on every non-loopback interface
    if args.netem:
        stats = []
        for iface in [i for i in read_netdev() if i != "lo"]:
            r = subprocess.run(["tc", "qdisc", "add", "dev", iface, "root", "netem"] + shlex.split(args.netem),
                               capture_output=True, text=True)
            if r.returncode != 0:
                result["netem_error"] = r.stderr.strip()
                print("psi_wrap: tc failed: " + r.stderr, file=sys.stderr)
                json.dump(result, open(args.out, "w"))
                return 3
            stats.append(iface)
        result["netem_ifaces"] = stats

    # 2. listening-port announcer
    stop_announce = threading.Event()
    if args.announce and args.sync_dir:
        want = {int(p) for p in args.announce.split(",") if p}

        def announce() -> None:
            done: set[int] = set()
            while not stop_announce.is_set() and done != want:
                for p in listening_ports() & want - done:
                    path = os.path.join(args.sync_dir, f"listen_{args.tag}_{p}")
                    open(path, "w").close()
                    done.add(p)
                time.sleep(0.001)

        threading.Thread(target=announce, daemon=True).start()

    # 3. start gate
    if args.sync_dir:
        open(os.path.join(args.sync_dir, f"ready_{args.tag}"), "w").close()
        if not wait_for_file(os.path.join(args.sync_dir, "go"), args.gate_timeout):
            print("psi_wrap: gate timeout waiting for go", file=sys.stderr)
            return 4
        for name in args.wait_for:
            if not wait_for_file(os.path.join(args.sync_dir, name), args.gate_timeout):
                print(f"psi_wrap: gate timeout waiting for {name}", file=sys.stderr)
                return 4

    # 4. launch
    if args.start_delay_ms > 0:
        time.sleep(args.start_delay_ms / 1000.0)
    net_before = read_netdev()
    t0 = time.monotonic()
    start_epoch = time.time()
    pid = os.fork()
    if pid == 0:
        try:
            if args.log:
                fd = os.open(args.log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
                chown_if(args.log, args.uid, args.gid)
                os.dup2(fd, 1)
                os.dup2(fd, 2)
            if args.cwd:
                os.chdir(args.cwd)
            if args.cpus:
                os.sched_setaffinity(0, parse_cpus(args.cpus))
            if args.gid is not None:
                os.setgroups([])
                os.setgid(args.gid)
            if args.uid is not None:
                os.setuid(args.uid)
            os.execvp(cmd[0], cmd)
        except Exception as e:  # noqa: BLE001
            os.write(2, f"psi_wrap: exec failed: {e}\n".encode())
        os._exit(127)

    # 5. measure
    samples: list[list[float]] = []
    peak_threads = 0
    stop = threading.Event()
    timed_out = threading.Event()

    def sampler() -> None:
        nonlocal peak_threads
        interval = args.sample_ms / 1000.0
        while not stop.is_set():
            s = proc_sample(pid)
            if s:
                samples.append([round(time.monotonic() - t0, 4), s[0], round(s[1], 3)])
                peak_threads = max(peak_threads, s[2])
            stop.wait(interval)

    threading.Thread(target=sampler, daemon=True).start()
    if args.timeout > 0:
        def kill_later() -> None:
            if not stop.wait(args.timeout):
                timed_out.set()
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        threading.Thread(target=kill_later, daemon=True).start()

    _, status, ru = os.wait4(pid, 0)
    wall = time.monotonic() - t0
    end_epoch = time.time()
    stop.set()
    stop_announce.set()
    net_after = read_netdev()

    if len(samples) > 1000:  # keep the stored timeline small
        step = len(samples) // 1000 + 1
        samples = samples[::step]

    cg_peak = None
    for p in ("/sys/fs/cgroup/memory.peak",):
        try:
            cg_peak = int(open(p).read()) // 1024
        except (OSError, ValueError):
            pass

    netem_stats = None
    if args.netem:
        r = subprocess.run(["tc", "-s", "qdisc", "show"], capture_output=True, text=True)
        netem_stats = r.stdout.strip()

    result.update({
        "exit_code": os.waitstatus_to_exitcode(status),
        "timed_out": timed_out.is_set(),
        "start_epoch": start_epoch,
        "end_epoch": end_epoch,
        "wall_s": wall,
        "user_s": ru.ru_utime,
        "sys_s": ru.ru_stime,
        "maxrss_kb": ru.ru_maxrss,
        "cgroup_peak_kb": cg_peak,
        "minor_faults": ru.ru_minflt,
        "major_faults": ru.ru_majflt,
        "vol_ctx_switches": ru.ru_nvcsw,
        "invol_ctx_switches": ru.ru_nivcsw,
        "peak_threads": peak_threads,
        "net": {} if args.no_net else net_delta(net_before, net_after),
        "mem_timeline": samples,  # [t_s, rss_kb, cpu_s]
        "netem_stats": netem_stats,
    })
    tmp = args.out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(result, f)
    os.replace(tmp, args.out)
    chown_if(args.out, args.uid, args.gid)

    # 6. linger until every party is done. Destroying the network namespace discards packets still
    # queued in netem (delay/rate), so a peer waiting for our last message would hang forever.
    # Metrics were captured above, so this does not affect any measurement.
    if args.sync_dir:
        wait_for_file(os.path.join(args.sync_dir, "done"), args.gate_timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
