import { api, usePoll } from "../api";

interface EnvResponse { snapshot: any; hash: string; host_state: any }

function KV({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <table>
      <tbody>
        {rows.map(([k, v]) => (
          <tr key={k}><th style={{ width: 190, textTransform: "none", letterSpacing: 0, fontSize: 13 }}>{k}</th><td>{v}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Hardware() {
  const { data, error, reload } = usePoll(() => api<EnvResponse>("/api/env"), 0);
  if (error) return <div className="note err">{error}</div>;
  if (!data) return <p>Collecting the environment snapshot (queries the Docker images, a few seconds)…</p>;
  const s = data.snapshot;
  const h = data.host_state;
  const topo = s.cpu.topology ?? {};
  return (
    <>
      <div className="row">
        <div><h2>Hardware and software</h2>
          <p className="lead" style={{ marginBottom: 6 }}>The baseline stored with every run (environment hash <code>{data.hash}</code>). Cite this in the paper.</p></div>
        <span className="spacer" />
        <button className="secondary small" onClick={async () => { await api("/api/env?refresh=true"); reload(); }}>Refresh</button>
      </div>
      {(h.running_containers > 0 || h.governor === "powersave") && (
        <div className="note">
          Noise sources right now: {h.running_containers} other container(s) running, CPU governor <code>{h.governor}</code>
          {h.governor === "powersave" ? " (frequency varies a lot between runs; `performance` gives steadier numbers)" : ""}, load average {h.loadavg?.join(" / ")}.
          Both are recorded with every run.
        </div>
      )}
      <div className="grid cols2">
        <div>
          <h3>Machine</h3>
          <KV rows={[
            ["CPU", s.cpu.model],
            ["Logical CPUs", `${s.cpu.logical_cpus} (threads per core: ${s.cpu.threads_per_core})`],
            ["Core types", `P-cores ${topo.p_cores ?? "-"} · E-cores ${topo.e_cores ?? "-"} · LP-E ${topo.lp_e_cores ?? "-"}`],
            ["Benchmarks pinned to", <code>{s.pinned_cpus_default}</code>],
            ["Caches", `L2 ${s.cpu.l2_cache} · L3 ${s.cpu.l3_cache}`],
            ["CPU features", (s.cpu.flags ?? []).join(", ")],
            ["Memory", `${s.memory_total_gb} GB`],
            ["OS / kernel", `${s.os} · ${s.kernel}`],
            ["Docker", s.docker],
            ["Host compiler", s.host_gcc],
          ]} />
        </div>
        <div>
          <h3>Right now</h3>
          <KV rows={[
            ["Load average", h.loadavg?.join(" / ")],
            ["Memory available", `${h.mem_available_mb} MB`],
            ["CPU governor", h.governor],
            ["Frequency of pinned cores", Object.entries(h.cur_mhz ?? {}).map(([c, f]) => `cpu${c}: ${f} MHz`).join(" · ")],
            ["Other containers running", h.running_containers],
          ]} />
        </div>
      </div>
      <h3>Protocol builds</h3>
      <div className="tablewrap">
        <table>
          <thead><tr><th>Protocol</th><th>Source commit</th><th>Built with</th></tr></thead>
          <tbody>
            {[["PEPSI", "pepsi", `${s.images?.pepsi?.gcc ?? "-"} (e2e driver, image ${s.images?.pepsi?.image_id ?? "-"}); upstream benchmark: host ${s.host_gcc}, SEAL ${s.pepsi_build?.seal_version}`],
              ["VOLE-PSI", "volepsi", `${s.images?.volepsi?.gcc ?? "-"} on ${s.images?.volepsi?.os ?? "-"} (image ${s.images?.volepsi?.image_id ?? "-"})`],
              ["BZS-MPSI", "bzs", `${s.images?.bzs?.gcc ?? "-"} on ${s.images?.bzs?.os ?? "-"} (image ${s.images?.bzs?.image_id ?? "-"})`]].map(([name, key, built]) => (
              <tr key={name}>
                <td>{name}</td>
                <td><code>{s.repos?.[key]?.commit?.slice(0, 10) ?? "-"}</code> {s.repos?.[key]?.dirty ? <span className="badge unchecked">uncommitted changes</span> : null}
                  <div className="help">{s.repos?.[key]?.subject}</div></td>
                <td>{built}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="help">The three protocols are built with different compilers because their pinned dependencies require it (VOLE-PSI's libOTe needs C++20 &lt;format&gt;, GCC 13+). This is recorded, not hidden.</p>
    </>
  );
}
