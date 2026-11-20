import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ErrorBar, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell } from "recharts";
import { GroupEntry, api, usePoll } from "../api";
import { colorOf, fmtMB, fmtSizes, fmtStats } from "../format";

type MetricKey = "wall" | "cpu" | "rss" | "comm";
const METRICS: { key: MetricKey; title: string; unit: string; scale: number }[] = [
  { key: "wall", title: "Wall time", unit: "s", scale: 1 },
  { key: "cpu", title: "CPU time (all parties)", unit: "s", scale: 1 },
  { key: "rss", title: "Peak memory (largest party)", unit: "MB", scale: 1 / 1024 },
  { key: "comm", title: "Communication", unit: "MB", scale: 1e-6 },
];

export function useGroups(ids: string[]) {
  return usePoll(() => (ids.length ? api<GroupEntry[]>(`/api/compare?groups=${ids.join(",")}`) : Promise.resolve([])), 0, [ids.join(",")]);
}

export function MetricChart({ rows, metric, log }: { rows: GroupEntry[]; metric: (typeof METRICS)[number]; log: boolean }) {
  const data = rows.map((g) => {
    const s = g[metric.key];
    const med = s.median !== undefined ? s.median * metric.scale : null;
    const ci = s.ci95 !== undefined ? s.ci95 * metric.scale : 0;
    return { name: g.label, value: med, err: ci, protocol: g.protocol, label: g.label };
  });
  const positive = data.filter((d) => d.value && d.value > 0);
  return (
    <div className="card" style={{ height: 120 + rows.length * 34 }}>
      <b>{metric.title} ({metric.unit}){log ? ", log scale" : ""}</b>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ left: 10, right: 30, top: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis type="number" scale={log ? "log" : "auto"} domain={log ? [positive.length ? Math.min(...positive.map((d) => d.value!)) / 2 : 0.001, "auto"] : [0, "auto"]}
            allowDataOverflow tickFormatter={(v) => (v >= 100 ? Math.round(v).toString() : Number(v).toPrecision(2))} />
          <YAxis type="category" dataKey="name" width={290} tick={{ fontSize: 11 }} />
          <Tooltip formatter={(v: number) => `${Number(v).toPrecision(4)} ${metric.unit}`} />
          <Bar dataKey="value" name={metric.title} isAnimationActive={false}>
            {data.map((d, i) => <Cell key={i} fill={colorOf(d.protocol, d.label)} />)}
            <ErrorBar dataKey="err" width={4} stroke="#333" direction="x" />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Compare() {
  const [params, setParams] = useSearchParams();
  const selected = useMemo(() => (params.get("groups") ?? "").split(",").filter(Boolean), [params]);
  const [log, setLog] = useState(true);
  const [filter, setFilter] = useState("");
  const { data: all } = usePoll(() => api<GroupEntry[]>("/api/groups?limit=300"), 0);
  const { data: rows, error } = useGroups(selected);

  useEffect(() => { document.title = "Compare · psibench"; }, []);
  const setSel = (ids: string[]) => setParams(ids.length ? { groups: ids.join(",") } : {});
  const toggle = (g: string) => setSel(selected.includes(g) ? selected.filter((x) => x !== g) : [...selected, g]);
  const shown = (all ?? []).filter((g) => !filter || g.label.toLowerCase().includes(filter.toLowerCase()));
  const ordered = selected.map((id) => rows?.find((r) => r.group_id === id)).filter(Boolean) as GroupEntry[];

  return (
    <>
      <h2>Compare</h2>
      <p className="lead">
        Pick experiment groups to compare side by side. Bars show the median, whiskers the 95% confidence interval over the repetitions.
        Only runs that succeeded are included; the run count is shown in the table.
      </p>
      <div className="grid cols2" style={{ gridTemplateColumns: "minmax(300px, 380px) 1fr" }}>
        <div className="card" style={{ maxHeight: 640, overflow: "auto" }}>
          <input type="text" placeholder="filter by label…" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <div style={{ marginTop: 10 }}>
            {shown.map((g) => (
              <label key={g.group_id} className="check" style={{ marginBottom: 6 }}>
                <input type="checkbox" checked={selected.includes(g.group_id)} onChange={() => toggle(g.group_id)} />
                <span><b style={{ fontWeight: 500 }}>{g.label}</b><span className="help">{g.n_ok}/{g.n_total} ok · {g.suite ?? "ad hoc"}</span></span>
              </label>
            ))}
            {shown.length === 0 && <span className="help">No groups yet. <Link to="/new">Start a run.</Link></span>}
          </div>
          {selected.length > 0 && <button className="secondary small" onClick={() => setSel([])}>Clear selection</button>}
        </div>
        <div>
          {error && <div className="note err">{error}</div>}
          {ordered.length === 0 && <div className="note info">Select one or more groups on the left.</div>}
          {ordered.length > 0 && (
            <>
              <div className="row" style={{ marginBottom: 10 }}>
                <label className="check" style={{ margin: 0 }}>
                  <input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} />
                  <span>Logarithmic axes (values differ by orders of magnitude)</span>
                </label>
              </div>
              {METRICS.map((m) => <MetricChart key={m.key} rows={ordered} metric={m} log={log} />)}
              <h3>Table</h3>
              <div className="tablewrap">
                <table>
                  <thead><tr><th>Experiment</th><th>Sizes</th><th className="num">Runs ok</th><th className="num">Wall s (±95% CI)</th>
                    <th className="num">CPU s</th><th className="num">Peak RSS</th><th className="num">Comm</th><th className="num">Online comm</th></tr></thead>
                  <tbody>
                    {ordered.map((g) => (
                      <tr key={g.group_id}>
                        <td>{g.label}</td><td>{fmtSizes(g.sizes)}</td><td className="num">{g.n_ok}/{g.n_total}</td>
                        <td className="num">{fmtStats(g.wall)}</td><td className="num">{fmtStats(g.cpu, 1, 2)}</td>
                        <td className="num">{g.rss.median ? `${(g.rss.median / 1024).toFixed(0)} MB` : "-"}</td>
                        <td className="num">{fmtMB(g.comm.median)}</td><td className="num">{fmtMB(g.comm_online.median)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
