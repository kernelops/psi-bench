import { Link, useNavigate, useParams } from "react-router-dom";
import { Job, api, postJson, usePoll } from "../api";
import { fmtTime } from "../format";

function Progress({ job }: { job: Job }) {
  const pct = job.total ? Math.min(100, Math.round((job.done / job.total) * 100)) : 0;
  return (
    <div>
      <div className="progress"><div style={{ width: `${job.status === "done" ? 100 : pct}%` }} /></div>
      <span className="help">{job.done}/{job.total} runs</span>
    </div>
  );
}

export default function Jobs() {
  const { id } = useParams();
  return id ? <JobDetail id={id} /> : <JobList />;
}

function JobList() {
  const nav = useNavigate();
  const { data: jobs, error } = usePoll(() => api<Job[]>("/api/jobs"), 2000);
  return (
    <>
      <h2>Jobs</h2>
      <p className="lead">Jobs run one at a time, in the order they were queued. Jobs live in the server's memory; finished results stay in History.</p>
      {error && <div className="note err">{error}</div>}
      {jobs && jobs.length === 0 && <div className="note info">No jobs yet. <Link to="/new">Start a run</Link> or an <Link to="/experiments">experiment suite</Link>.</div>}
      {jobs && jobs.length > 0 && (
        <div className="tablewrap">
          <table>
            <thead><tr><th>Job</th><th>Kind</th><th>Status</th><th style={{ width: 220 }}>Progress</th><th>Created</th></tr></thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id} className="clickable" onClick={() => nav(`/jobs/${j.id}`)}>
                  <td>{j.title}</td>
                  <td>{j.kind}</td>
                  <td><span className={`badge ${j.status}`}>{j.status}</span></td>
                  <td><Progress job={j} /></td>
                  <td>{fmtTime(j.created)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function JobDetail({ id }: { id: string }) {
  const nav = useNavigate();
  const { data: job, error, reload } = usePoll(() => api<Job>(`/api/jobs/${id}`), 1500, [id]);
  if (error) return <div className="note err">{error}</div>;
  if (!job) return <p>Loading…</p>;
  const active = job.status === "queued" || job.status === "running";
  return (
    <>
      <p><Link to="/jobs">← all jobs</Link></p>
      <h2>{job.title}</h2>
      <p className="lead">
        <span className={`badge ${job.status}`}>{job.status}</span>{" "}
        {job.kind === "suite" ? "experiment suite" : "run"} · created {fmtTime(job.created)}
        {job.finished && job.started ? ` · took ${(job.finished - job.started).toFixed(0)} s` : ""}
      </p>
      {job.error && <div className="note err">{job.error}</div>}
      <div className="card">
        <Progress job={job} />
        <div className="row" style={{ marginTop: 12 }}>
          {active && (
            <button className="danger small" onClick={async () => { await postJson(`/api/jobs/${id}/cancel`, {}); reload(); }}>
              Cancel
            </button>
          )}
          {job.group_id && job.status !== "queued" && (
            <button className="secondary small" onClick={() => nav(`/compare?groups=${job.group_id}`)}>Open in Compare</button>
          )}
          <span className="spacer" />
        </div>
      </div>
      {job.run_ids.length > 0 && (
        <div className="card">
          <b>Runs</b>
          <div className="row" style={{ marginTop: 8 }}>
            {job.run_ids.map((r) => <Link key={r} to={`/runs/${r}`} className="badge">#{r}</Link>)}
          </div>
        </div>
      )}
      <h3>Log</h3>
      <pre>{(job.log ?? []).join("\n") || "(no output yet)"}</pre>
    </>
  );
}
