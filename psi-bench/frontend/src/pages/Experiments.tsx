import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { GroupEntry, api, postJson, usePoll, Job } from "../api";
import { fmtMB, fmtSizes, fmtStats } from "../format";

interface SuiteInfo { file: string; name: string; description: string; experiments: number; runs: number; protocols: string[] }
interface Exps { suites: string[]; experiments: GroupEntry[] }

export default function Experiments() {
  const nav = useNavigate();
  const [suite, setSuite] = useState<string>("");
  const [picked, setPicked] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const { data: suites } = usePoll(() => api<SuiteInfo[]>("/api/suites"), 0);
  const { data: exps, error } = usePoll(() => api<Exps>(`/api/experiments${suite ? `?suite=${suite}` : ""}`), 8000, [suite]);

  async function launch(s: SuiteInfo) {
    setMsg(null);
    try {
      const job = await postJson<Job>("/api/jobs/suite", { file: s.file, skip_done: true });
      nav(`/jobs/${job.id}`);
    } catch (e) {
      setMsg((e as Error).message);
    }
  }
  const toggle = (g: string) => setPicked((p) => (p.includes(g) ? p.filter((x) => x !== g) : [...p, g]));

  return (
    <>
      <h2>Experiments</h2>
      <p className="lead">
        Predefined comparison suites (JSON files in <code>psi-bench/suites</code>). Running a suite skips experiments that already have enough
        successful runs, so you can re-run a whole suite after changing the machine state (for example after stopping other containers).
      </p>
      {msg && <div className="note err">{msg}</div>}
      <div className="grid cols3">
        {suites?.map((s) => (
          <div className="card" key={s.file}>
            <b>{s.name}</b>
            <p className="help" style={{ minHeight: 70 }}>{s.description}</p>
            <p className="help">{s.experiments} experiments · {s.runs} runs · {s.protocols.join(", ")}</p>
            <div className="row">
              <button className="small" onClick={() => launch(s)}>Run (skip finished)</button>
              <button className="secondary small" onClick={() => setSuite(s.name)}>Show results</button>
            </div>
          </div>
        ))}
      </div>

      <div className="row" style={{ margin: "18px 0 8px" }}>
        <h3 style={{ margin: 0 }}>Results</h3>
        <select style={{ width: 220 }} value={suite} onChange={(e) => setSuite(e.target.value)}>
          <option value="">all suites</option>
          {exps?.suites.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <span className="spacer" />
        <button disabled={!picked.length} onClick={() => nav(`/compare?groups=${picked.join(",")}`)}>Compare {picked.length || ""} selected</button>
        <a className="btn secondary" href={`/api/report.md${suite ? `?suite=${suite}` : ""}`} target="_blank" rel="noreferrer">Markdown</a>
        <a className="btn secondary" href={`/api/report.tex${suite ? `?suite=${suite}` : ""}`} target="_blank" rel="noreferrer">LaTeX</a>
      </div>
      {error && <div className="note err">{error}</div>}
      <div className="tablewrap">
        <table>
          <thead><tr><th></th><th>Experiment</th><th>Sizes</th><th className="num">Runs ok</th><th>Result</th>
            <th className="num">Wall s (±95% CI)</th><th className="num">CPU s</th><th className="num">Peak RSS</th><th className="num">Comm</th><th className="num">Online</th></tr></thead>
          <tbody>
            {exps?.experiments.map((g) => (
              <tr key={g.group_id}>
                <td><input type="checkbox" checked={picked.includes(g.group_id)} onChange={() => toggle(g.group_id)} /></td>
                <td>{g.label}<div className="help">{g.suite}</div></td>
                <td>{fmtSizes(g.sizes)}</td>
                <td className="num">{g.n_ok}/{g.n_total}</td>
                <td>{!g.n_ok ? <span className="badge failed">failed</span> : !g.checked ? <span className="badge unchecked">n/a</span>
                  : g.n_wrong ? <span className="badge wrong">{g.n_wrong} WRONG</span> : <span className="badge correct">correct</span>}</td>
                <td className="num">{fmtStats(g.wall)}</td><td className="num">{fmtStats(g.cpu, 1, 2)}</td>
                <td className="num">{g.rss.median ? `${(g.rss.median / 1024).toFixed(0)} MB` : "-"}</td>
                <td className="num">{fmtMB(g.comm.median)}</td><td className="num">{fmtMB(g.comm_online.median)}</td>
              </tr>
            ))}
            {exps && exps.experiments.length === 0 && <tr><td colSpan={10} className="muted">No suite results yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
