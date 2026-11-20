import { useEffect, useRef, useState } from "react";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* not json */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const postJson = <T,>(path: string, body: unknown) =>
  api<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export interface ParamSpec {
  key: string;
  label: string;
  type: "bool" | "number" | "select";
  default: unknown;
  options?: string[];
  help?: string;
}
export interface ProtocolInfo {
  id: string;
  name: string;
  family: string;
  mode: "files" | "benchmark";
  summary: string;
  min_parties: number;
  max_parties: number | null;
  party_roles?: string[];
  uses_dataset: boolean;
  supports_network: boolean;
  supports_threads: boolean;
  size_rule?: string;
  check: string;
  params: ParamSpec[];
  notes?: string;
  experimental?: boolean;
}
export interface NetworkInfo {
  id: string;
  label: string;
  help: string;
}
export interface ProtocolsResponse {
  protocols: ProtocolInfo[];
  networks: NetworkInfo[];
  pinned_cpus: string;
}
export interface DatasetInfo {
  name: string;
  sizes: number[];
  common: number;
  kind: string;
  elem_bits?: number;
}
export interface Job {
  id: string;
  kind: "run" | "suite";
  title: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  total: number;
  done: number;
  run_ids: number[];
  group_id: string | null;
  error: string | null;
  created: number;
  started: number | null;
  finished: number | null;
  payload: Record<string, unknown>;
  log?: string[];
}
export interface Run {
  id: number;
  group_id: string | null;
  rep_index: number;
  warmup: number;
  started_at: string;
  protocol: string;
  n_parties: number;
  set_sizes: number[];
  true_intersection: number | null;
  network: string;
  netem: string | null;
  threads: number;
  cpus: string;
  params: Record<string, unknown>;
  status: string;
  error: string | null;
  correct: number | null;
  check_detail?: Record<string, unknown> | null;
  wall_s: number | null;
  cpu_s: number | null;
  peak_rss_kb_max: number | null;
  peak_rss_kb_sum: number | null;
  comm_total_bytes: number | null;
  comm_online_bytes: number | null;
  reported?: Record<string, any> | null;
  host_state?: Record<string, any> | null;
  suite: string | null;
  label: string | null;
  parties?: Party[];
  environment?: { hash: string; snapshot: any } | null;
}
export interface Party {
  idx: number;
  role: string;
  runtime: string;
  exit_code: number | null;
  wall_s: number | null;
  user_s: number | null;
  sys_s: number | null;
  maxrss_kb: number | null;
  cgroup_peak_kb: number | null;
  tx_bytes: number | null;
  rx_bytes: number | null;
  reported: Record<string, any> | null;
  mem_timeline: [number, number, number][] | null;
  netem_stats: string | null;
}
export interface Stats {
  n: number;
  median?: number;
  mean?: number;
  min?: number;
  max?: number;
  stdev?: number;
  ci95?: number;
}
export interface GroupEntry {
  group_id: string;
  suite: string | null;
  label: string;
  protocol: string;
  sizes: number[];
  network: string;
  threads: number;
  params: Record<string, unknown>;
  first_id: number;
  started_at: string;
  n_total: number;
  n_ok: number;
  n_wrong: number;
  checked: boolean;
  wall: Stats;
  cpu: Stats;
  rss: Stats;
  comm: Stats;
  comm_online: Stats;
  run_ids: number[];
}

/** Re-run `fn` every `ms` milliseconds; returns the latest value, error and a manual reload. */
export function usePoll<T>(fn: () => Promise<T>, ms: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    let timer: number | undefined;
    const run = async () => {
      try {
        const v = await fn();
        if (alive.current) {
          setData(v);
          setError(null);
        }
      } catch (e) {
        if (alive.current) setError((e as Error).message);
      }
      if (alive.current && ms > 0) timer = window.setTimeout(run, ms);
    };
    run();
    return () => {
      alive.current = false;
      if (timer) window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, reload: () => setTick((t) => t + 1) };
}
