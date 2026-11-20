import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { GroupEntry, Run, api, usePoll } from "../api";
import { fmtKbAsMB, fmtMB, fmtSeconds, fmtSizes, fmtStats } from "../format";

const PROTOCOLS = ["", "pepsi-e2e", "volepsi", "volepsi-perf", "bzs-perf", "volepsi-star", "bzs", "pepsi", "pepsi-large"];

export function CorrectBadge({ run }: { run: Pick<Run, "correct" | "status"> }) {
  if (run.status !== "ok") return <span className={`badge ${run.status}`}>{run.status}</span>;
  if (run.correct === 1) return <span className="badge correct">correct</span>;
  if (run.correct === 0) return <span className="badge wrong">WRONG</span>;
  return <span className="badge unchecked">unchecked</span>;
}

export default function History() {
  const nav = useNavigate();
  const [protocol, setProtocol] = useState("");
  const [view, setView] = useState<"groups" | "runs">("groups");
  const { data: groups, error: gErr } = usePoll(
    () => api<GroupEntry[]>(`/api/groups?limit=200${protocol ? `&protocol=${protocol}` : ""}`), 5000, [protocol]);
  const { data: runs, error: rErr } = usePoll(
    () => api<Run[]>(`/api/runs?limit=300${protocol ? `&protocol=${protocol}` : ""}`), 5000, [protocol]);
  const [picked, setPicked] = useState<string[]>([]);
  const toggle = (g: string) => setPicked((p) => (p.includes(g) ? p.filter((x) => x !== g) : [...p, g]));

  return (
    <>
      <h2>History</h2>
      <p className="lead">Every run is stored with its hardware and software snapshot. Groups are repetitions of the same experiment; select groups to compare them.</p>
      <div className="row" style={{ marginBottom: 12 }}>
        <div className="tabs" style={{ margin: 0 }}>
          <button className={view === "groups" ? "active" : ""} onClick={() => setView("groups")}>Experiments (groups)</button>
          <button className={view === "runs" ? "active" : ""} onClick={() => setView("runs")}>Individual runs</button>
        </div>
        <select style={{ width: 200 }} value={protocol} onChange={(e) => setProtocol(e.target.value)}>
          {PROTOCOLS.map((p) => <option key={p} value={p}>{p || "all protocols"}</option>)}
        </select>
        <span className="spacer" />
        {view === "groups" && (
          <button disabled={picked.length < 1} onClick={() => nav(`/compare?groups=${picked.join(",")}`)}>
            Compare {picked.length || ""} selected
          </button>
        )}
        <a className="btn secondary" href="/api/export.csv">Export CSV</a>
      </div>
      {(gErr || rErr) && <div className="note err">{gErr || rErr}</div>}

      {view === "groups" && groups && (
        <div className="tablewrap">
          <table>
            <thead>
              <tr><th></th><th>Experiment</th><th>Sizes</th><th>Net</th><th className="num">Thr</th><th className="num">Runs ok</th><th>Result</th>
                <th className="num">Wall (median ±CI)</th><th className="num">CPU s</th><th className="num">Peak RSS</th><th className="num">Comm</th></tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.group_id}>
                  <td><input type="checkbox" checked={picked.includes(g.group_id)} onChange={() => toggle(g.group_id)} /></td>
                  <td><Link to={`/runs/${g.run_ids[0]}`}>{g.label}</Link>{g.suite && <div className="help">{g.suite}</div>}</td>
                  <td>{fmtSizes(g.sizes)}</td>
                  <td>{g.network}</td>
                  <td className="num">{g.threads}</td>
                  <td className="num">{g.n_ok}/{g.n_total}</td>
                  <td>{!g.n_ok ? <span className="badge failed">failed</span> : !g.checked ? <span className="badge unchecked">unchecked</span>
                    : g.n_wrong ? <span className="badge wrong">{g.n_wrong} WRONG</span> : <span className="badge correct">correct</span>}</td>
                  <td className="num">{fmtStats(g.wall)} s</td>
                  <td className="num">{fmtStats(g.cpu, 1, 2)}</td>
                  <td className="num">{g.rss.median ? fmtKbAsMB(g.rss.median) : "-"}</td>
                  <td className="num">{fmtMB(g.comm.median)}</td>
                </tr>
              ))}
              {groups.length === 0 && <tr><td colSpan={11} className="muted">No runs yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {view === "runs" && runs && (
        <div className="tablewrap">
          <table>
            <thead><tr><th>#</th><th>Protocol</th><th>Sizes</th><th>Net</th><th className="num">Thr</th><th>Status</th>
              <th className="num">Wall</th><th className="num">CPU s</th><th className="num">Peak RSS</th><th className="num">Comm</th><th>Started</th></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="clickable" onClick={() => nav(`/runs/${r.id}`)}>
                  <td>{r.id}{r.warmup ? <span className="help"> warm-up</span> : null}</td>
                  <td>{r.protocol}</td>
                  <td>{fmtSizes(r.set_sizes ?? [])}</td>
                  <td>{r.network}</td>
                  <td className="num">{r.threads}</td>
                  <td><CorrectBadge run={r} /></td>
                  <td className="num">{fmtSeconds(r.wall_s)}</td>
                  <td className="num">{r.cpu_s?.toFixed(2) ?? "-"}</td>
                  <td className="num">{fmtKbAsMB(r.peak_rss_kb_max)}</td>
                  <td className="num">{fmtMB(r.comm_total_bytes)}</td>
                  <td>{r.started_at.replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
