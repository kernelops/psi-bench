import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Run, api, usePoll } from "../api";
import { fmtKbAsMB, fmtMB, fmtSeconds, fmtSizes } from "../format";
import { CorrectBadge } from "./History";

const COLORS = ["#2563eb", "#d1495b", "#3a9e5f", "#7a5195", "#f2a65a", "#0891b2", "#9333ea", "#64748b"];

interface IntersectionResp {
  count: number;
  shown: number;
  party: number;
  mapped: boolean;
  cardinality_only: boolean;
  dataset_gone?: boolean;
  elements: { value: string; hash: string | null }[];
}

/** The elements the protocol found. Hidden for runs that produce no result (benchmark modes, failed runs). */
function Intersection({ runId, status }: { runId: number; status: string }) {
  const [data, setData] = useState<IntersectionResp | null>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let alive = true;
    setData(null);
    if (status !== "ok") return;
    fetch(`/api/runs/${runId}/intersection?limit=1000`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => alive && setData(d))
      .catch(() => undefined);
    return () => { alive = false; };
  }, [runId, status]);
  if (!data) return null;
  const copy = async () => {
    await navigator.clipboard.writeText(data.elements.map((e) => e.value).join("\n"));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return (
    <>
      <h3>Intersection found: {data.count.toLocaleString()} element{data.count === 1 ? "" : "s"}</h3>
      <div className="card">
        {data.cardinality_only ? (
          <p style={{ margin: 0 }}>Only the number of shared elements was requested, so there is no list. The count is {data.count}.</p>
        ) : (
          <>
            <p className="help" style={{ marginTop: 0 }}>
              Learned by party {data.party}.{" "}
              {data.mapped
                ? "Shown as the original text from your upload; the protocol itself worked on 128-bit hashes of these."
                : data.dataset_gone
                  ? "The dataset is no longer on disk, so the original text is not available: these are the 128-bit values the protocol works with."
                  : "These are the 128-bit values the protocols work with (this dataset was generated, not uploaded as text)."}
            </p>
            {data.count === 0 ? <p style={{ margin: 0 }}>The sets have no element in common.</p> : (
              <pre style={{ maxHeight: 260, margin: "0 0 10px" }}>{data.elements.map((e) => e.value).join("\n")}</pre>
            )}
            {data.count > data.shown && <p className="help">Showing the first {data.shown.toLocaleString()} of {data.count.toLocaleString()}; the download has all of them.</p>}
            <div className="row">
              <a className="btn secondary small" href={`/api/runs/${runId}/intersection.txt`}>Download as .txt</a>
              {data.count > 0 && <button className="secondary small" onClick={copy}>{copied ? "Copied" : "Copy"}</button>}
            </div>
          </>
        )}
      </div>
    </>
  );
}

function Stat({ k, v, s }: { k: string; v: string; s?: string }) {
  return <div className="stat"><div className="k">{k}</div><div className="v">{v}</div>{s && <div className="s">{s}</div>}</div>;
}

export default function RunDetail() {
  const { id } = useParams();
  const { data: run, error } = usePoll(() => api<Run>(`/api/runs/${id}`), 0, [id]);
  const [logParty, setLogParty] = useState<number | null>(null);
  const { data: log } = usePoll(
    () => (logParty === null ? Promise.resolve("") : fetch(`/api/runs/${id}/log/${logParty}`).then((r) => r.text())), 0, [id, logParty]);
  if (error) return <div className="note err">{error}</div>;
  if (!run) return <p>Loading…</p>;

  const parties = run.parties ?? [];
  // merge the per-party memory timelines onto one time axis
  const series = parties.filter((p) => p.mem_timeline && p.mem_timeline.length > 1);
  const maxLen = Math.max(0, ...series.map((p) => p.mem_timeline!.length));
  const rows: Record<string, number>[] = [];
  for (let i = 0; i < maxLen; i++) {
    const row: Record<string, number> = {};
    series.forEach((p) => {
      const pt = p.mem_timeline![Math.min(i, p.mem_timeline!.length - 1)];
      row[`t${p.idx}`] = pt[0];
      row[`p${p.idx}`] = pt[1] / 1024;
    });
    row.t = series.length ? row[`t${series[0].idx}`] : i;
    rows.push(row);
  }
  const rep = run.reported ?? {};
  const env = run.environment?.snapshot;
  return (
    <>
      <p><Link to="/history">← history</Link></p>
      <h2>Run #{run.id}: {run.protocol}</h2>
      <p className="lead">
        <CorrectBadge run={run} /> {run.warmup ? <span className="badge">warm-up</span> : null}{" "}
        {fmtSizes(run.set_sizes ?? [])} · network {run.network} · {run.threads} thread(s) · CPUs {run.cpus} · {run.started_at.replace("T", " ")}
        {run.label ? ` · ${run.label}` : ""}
      </p>
      {run.error && <div className="note err">{run.error}</div>}
      {run.status === "ok" && run.correct === 0 && (
        <div className="note err">The output does not match the ground truth: {JSON.stringify(run.check_detail)}</div>
      )}
      {run.protocol === "volepsi-perf" && <div className="note info">Both parties ran in one process with an in-memory socket; CPU and memory cover both parties together.</div>}

      <div className="grid cols4">
        <Stat k="Wall time" v={fmtSeconds(run.wall_s)} s="first start to last finish" />
        <Stat k="CPU time" v={run.cpu_s !== null ? `${run.cpu_s.toFixed(2)} s` : "-"} s="user + system, all parties" />
        <Stat k="Peak memory" v={fmtKbAsMB(run.peak_rss_kb_max)} s={`largest party (sum ${fmtKbAsMB(run.peak_rss_kb_sum)})`} />
        <Stat k="Communication" v={fmtMB(run.comm_total_bytes)} s={run.comm_online_bytes ? `online ${fmtMB(run.comm_online_bytes)}` : "bytes delivered, incl. headers"} />
      </div>

      <Intersection runId={run.id} status={run.status} />

      <h3>Parties</h3>
      <div className="tablewrap">
        <table>
          <thead><tr><th>#</th><th>Role</th><th>Exit</th><th className="num">Wall</th><th className="num">User</th><th className="num">Sys</th>
            <th className="num">Peak RSS</th><th className="num">Sent</th><th className="num">Received</th><th></th></tr></thead>
          <tbody>
            {parties.map((p) => (
              <tr key={p.idx}>
                <td>{p.idx}</td><td>{p.role}</td>
                <td><span className={`badge ${p.exit_code === 0 ? "ok" : "failed"}`}>{p.exit_code}</span></td>
                <td className="num">{fmtSeconds(p.wall_s)}</td>
                <td className="num">{p.user_s?.toFixed(2) ?? "-"}</td><td className="num">{p.sys_s?.toFixed(2) ?? "-"}</td>
                <td className="num">{fmtKbAsMB(p.maxrss_kb)}</td>
                <td className="num">{fmtMB(p.tx_bytes)}</td><td className="num">{fmtMB(p.rx_bytes)}</td>
                <td><button className="secondary small" onClick={() => setLogParty(logParty === p.idx ? null : p.idx)}>log</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {logParty !== null && <pre>{log || "(empty)"}</pre>}

      {rows.length > 1 && (
        <>
          <h3>Memory over time (resident set size)</h3>
          <div className="card" style={{ height: 300 }}>
            <ResponsiveContainer>
              <LineChart data={rows}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="t" type="number" domain={[0, "dataMax"]} tickFormatter={(v) => `${Number(v).toFixed(1)}s`} />
                <YAxis tickFormatter={(v) => `${Math.round(Number(v))} MB`} width={70} />
                <Tooltip formatter={(v: number) => `${v.toFixed(0)} MB`} labelFormatter={(l) => `${Number(l).toFixed(2)} s`} />
                <Legend />
                {series.map((p, i) => (
                  <Line key={p.idx} dataKey={`p${p.idx}`} name={`party ${p.idx} (${p.role})`} dot={false} stroke={COLORS[i % COLORS.length]} strokeWidth={2} isAnimationActive={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}

      {Object.keys(rep).length > 0 && (
        <>
          <h3>Protocol-reported values</h3>
          <pre>{JSON.stringify(rep, null, 2)}</pre>
        </>
      )}
      {run.check_detail && (<><h3>Correctness check</h3><pre>{JSON.stringify(run.check_detail, null, 2)}</pre></>)}
      {run.host_state && (<><h3>Host state at start</h3><pre>{JSON.stringify(run.host_state, null, 2)}</pre></>)}
      {env && (
        <>
          <h3>Environment (hash {run.environment?.hash})</h3>
          <div className="card">
            {env.cpu?.model} · {env.memory_total_gb} GB RAM · {env.os} · kernel {env.kernel} · Docker {env.docker}
          </div>
        </>
      )}
    </>
  );
}
