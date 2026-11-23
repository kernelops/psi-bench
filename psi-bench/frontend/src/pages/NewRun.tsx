import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { DatasetInfo, Job, ParamSpec, ProtocolInfo, ProtocolsResponse, api, postJson, usePoll } from "../api";
import { fmtSizes, parseSizes } from "../format";

type DataSource = "generate" | "existing" | "upload";
type Mode = "files" | "benchmark";

const DEFAULT_PROTOCOL: Record<Mode, string> = { files: "pepsi-e2e", benchmark: "bzs-perf" };

function defaultSizes(p: ProtocolInfo): string {
  if (p.id === "volepsi-perf") return "2^16, 2^16";
  if (p.min_parties >= 3) return "2^16, 2^16, 2^16";
  return "1024, 2^20";
}

export default function NewRun() {
  const nav = useNavigate();
  const [query] = useSearchParams();
  const { data: cat, error: catErr } = usePoll(() => api<ProtocolsResponse>("/api/protocols"), 0);
  const { data: datasets, reload: reloadDatasets } = usePoll(() => api<DatasetInfo[]>("/api/datasets"), 0);

  const [protocolId, setProtocolId] = useState(query.get("protocol") ?? DEFAULT_PROTOCOL.files);
  const [source, setSource] = useState<DataSource>("generate");
  const [sizesText, setSizesText] = useState("1024, 2^20");
  const [common, setCommon] = useState("100");
  const [elemBits, setElemBits] = useState("128");
  const [seed, setSeed] = useState("1");
  const [datasetName, setDatasetName] = useState("");
  const [network, setNetwork] = useState("none");
  const [threads, setThreads] = useState("1");
  const [reps, setReps] = useState("3");
  const [warmup, setWarmup] = useState("1");
  const [timeout, setTimeoutS] = useState("1800");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [uploadName, setUploadName] = useState("my-data");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [hashUpload, setHashUpload] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "err" | "info"; text: string } | null>(null);

  const proto = useMemo(() => cat?.protocols.find((p) => p.id === protocolId), [cat, protocolId]);
  const mode: Mode = proto?.mode ?? "files";

  // reset protocol-specific options when the protocol changes
  useEffect(() => {
    if (!proto) return;
    const d: Record<string, unknown> = {};
    proto.params.forEach((p) => (d[p.key] = p.default));
    setParams(d);
    if (!proto.uses_dataset && source !== "generate") setSource("generate");
    if (!proto.supports_network) setNetwork("none");
    if (!proto.supports_threads) setThreads("1");
    setSizesText(defaultSizes(proto));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proto?.id]);

  if (catErr) return <div className="note err">Cannot reach the API: {catErr}. Start it with <code>./serve</code>.</div>;
  if (!cat || !proto) return <p>Loading…</p>;

  const sizes = parseSizes(sizesText);
  const sizesValid = sizes.length > 0 && sizes.every((s) => Number.isFinite(s) && s > 0 && Number.isInteger(s));
  const existing = datasets?.find((d) => d.name === datasetName);
  const usesFiles = proto.uses_dataset;
  const setParam = (k: string, v: unknown) => setParams((p) => ({ ...p, [k]: v }));

  const inMode = cat.protocols.filter((p) => p.mode === mode);
  const mainList = inMode.filter((p) => !p.advanced);
  const advancedList = inMode.filter((p) => p.advanced);

  const canRun = usesFiles
    ? source === "generate" ? sizesValid : source === "existing" ? Boolean(datasetName) : uploadFiles.length >= 2
    : sizesValid;

  async function submit() {
    setBusy(true);
    setMsg(null);
    try {
      let dataset: string | undefined;
      if (usesFiles && source === "upload") {
        if (uploadFiles.length < 2) throw new Error("choose at least two files (one per party)");
        const fd = new FormData();
        fd.append("name", uploadName);
        fd.append("hash_elements", String(hashUpload));
        uploadFiles.forEach((f) => fd.append("files", f));
        const r = await fetch("/api/datasets/import", { method: "POST", body: fd });
        if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText);
        dataset = uploadName;
        reloadDatasets();
      } else if (usesFiles && source === "existing") {
        if (!datasetName) throw new Error("choose a dataset");
        dataset = datasetName;
      }
      const body: Record<string, unknown> = {
        protocol: proto!.id,
        network,
        threads: Number(threads),
        reps: Number(reps),
        warmup: Number(warmup),
        timeout: Number(timeout),
        params,
        common: Number(common),
        seed: Number(seed),
        elem_bits: Number(elemBits),
      };
      if (dataset) body.dataset = dataset;
      else body.sizes = sizes;
      const job = await postJson<Job>("/api/jobs/run", body);
      nav(`/jobs/${job.id}`);
    } catch (e) {
      setMsg({ kind: "err", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const runs = Number(reps) + Number(warmup);

  return (
    <>
      <h2>New run</h2>
      <p className="lead">
        Choose what to run, give it inputs, and start it. Runs are queued and executed one at a time on the pinned P-cores (CPUs{" "}
        <code>{cat.pinned_cpus}</code>), so they do not disturb each other.
      </p>

      <div className="grid cols2">
        <div>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>1. What do you want to run?</h3>
            <div className="choices">
              <button className={`choice ${mode === "files" ? "active" : ""}`} onClick={() => setProtocolId(DEFAULT_PROTOCOL.files)}>
                <b>On my data</b>
                <span>Real input files: upload your own, or generate test files. You get the actual intersection and a correctness check.</span>
              </button>
              <button className={`choice ${mode === "benchmark" ? "active" : ""}`} onClick={() => setProtocolId(DEFAULT_PROTOCOL.benchmark)}>
                <b>Authors' benchmark</b>
                <span>The authors' own test program with random data. Nothing to upload. To reproduce their setup, or for BZS-MPSI with 3+ parties.</span>
              </button>
            </div>
            <label className="field">
              <span>Protocol</span>
              <select value={protocolId} onChange={(e) => setProtocolId(e.target.value)}>
                {advancedList.length > 0 ? (
                  <>
                    <optgroup label="Used for the comparison">
                      {mainList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </optgroup>
                    <optgroup label="Advanced: reproduce the paper">
                      {advancedList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </optgroup>
                  </>
                ) : (
                  mainList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)
                )}
              </select>
            </label>
            <p className="help" style={{ marginTop: -6 }}>{proto.summary}</p>
            <p className="help">
              Parties: {proto.min_parties}
              {proto.max_parties === proto.min_parties ? "" : proto.max_parties ? `–${proto.max_parties}` : "+"} · {proto.check}
            </p>
            {proto.notes && <p className="help">{proto.notes}</p>}
            {proto.experimental && (
              <div className="note err">Experimental: this mode crashes intermittently (and always under WAN shaping). Failed runs are recorded, not hidden.</div>
            )}
          </div>

          <div className="card">
            <h3 style={{ marginTop: 0 }}>2. Inputs</h3>
            {usesFiles && (
              <div className="tabs">
                {(["generate", "existing", "upload"] as DataSource[]).map((s) => (
                  <button key={s} className={source === s ? "active" : ""} onClick={() => setSource(s)}>
                    {s === "generate" ? "Generate test files" : s === "existing" ? "Existing dataset" : "Upload my files"}
                  </button>
                ))}
              </div>
            )}
            {usesFiles && proto.file_order && <p className="help" style={{ marginTop: 0 }}><b>Which file is which party:</b> {proto.file_order}</p>}

            {!usesFiles && (
              <div className="note info">
                <b>No input files in this mode.</b> {proto.input_note}
              </div>
            )}

            {(!usesFiles || source === "generate") && (
              <>
                <label className="field">
                  <span>{usesFiles ? "Set size per party" : "Size of each party's random set"} (comma separated; 2^20 allowed)</span>
                  <input type="text" value={sizesText} onChange={(e) => setSizesText(e.target.value)} />
                  <small>
                    {sizesValid ? `${sizes.length} parties: ${fmtSizes(sizes)}.` : "Enter positive integers."}
                    {" "}The number of sizes is the number of parties.
                    {proto.size_rule ? ` Rule: ${proto.size_rule}.` : ""}
                  </small>
                </label>
                <div className="grid cols3">
                  {proto.uses_common && (
                    <label className="field">
                      <span>{usesFiles ? "Intersection size" : "Shared elements planted"}</span>
                      <input type="number" value={common} onChange={(e) => setCommon(e.target.value)} />
                      <small>How many elements all parties have in common.</small>
                    </label>
                  )}
                  {usesFiles && (
                    <label className="field">
                      <span>Element domain</span>
                      <select value={elemBits} onChange={(e) => setElemBits(e.target.value)}>
                        <option value="128">128-bit random</option>
                        <option value="32">32-bit integers</option>
                      </select>
                    </label>
                  )}
                  {usesFiles && (
                    <label className="field">
                      <span>Seed</span>
                      <input type="number" value={seed} onChange={(e) => setSeed(e.target.value)} />
                    </label>
                  )}
                </div>
              </>
            )}

            {usesFiles && source === "existing" && (
              <label className="field">
                <span>Dataset</span>
                <select value={datasetName} onChange={(e) => setDatasetName(e.target.value)}>
                  <option value="">choose…</option>
                  {datasets?.map((d) => (
                    <option key={d.name} value={d.name}>
                      {d.name} ({fmtSizes(d.sizes)}, ∩ {d.common})
                    </option>
                  ))}
                </select>
                {existing && <small>{existing.sizes.length} parties, {existing.kind}</small>}
              </label>
            )}
            {usesFiles && source === "upload" && (
              <>
                <label className="field">
                  <span>Dataset name</span>
                  <input type="text" value={uploadName} onChange={(e) => setUploadName(e.target.value)} />
                </label>
                <label className="field">
                  <span>One file per party, one element per line</span>
                  <input type="file" multiple onChange={(e) => setUploadFiles(Array.from(e.target.files ?? []))} />
                  <small>
                    The order below is the party order. Browsers often sort files alphabetically, so name them
                    <code>1_client.txt</code>, <code>2_server.txt</code> and so on.
                  </small>
                </label>
                {uploadFiles.length > 0 && (
                  <ol className="help" style={{ marginTop: 0 }}>
                    {uploadFiles.map((f, i) => <li key={f.name}>party {i}: {f.name}</li>)}
                  </ol>
                )}
                <label className="check">
                  <input type="checkbox" checked={hashUpload} onChange={(e) => setHashUpload(e.target.checked)} />
                  <span>
                    <b>Hash elements to 128 bits</b>
                    <span className="help">Needed for arbitrary strings; uncheck only if every line is already 32 hex characters. The true intersection is computed on upload.</span>
                  </span>
                </label>
              </>
            )}
          </div>
        </div>

        <div>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>3. Conditions</h3>
            <div className="grid cols2">
              <label className="field">
                <span>Network</span>
                <select value={network} disabled={!proto.supports_network} onChange={(e) => setNetwork(e.target.value)}>
                  {cat.networks.map((n) => (
                    <option key={n.id} value={n.id}>{n.label}</option>
                  ))}
                </select>
                {!proto.supports_network && <small>No real network in this mode.</small>}
              </label>
              <label className="field">
                <span>Threads per party</span>
                <input type="number" min={1} max={16} value={threads} disabled={!proto.supports_threads} onChange={(e) => setThreads(e.target.value)} />
                {!proto.supports_threads && <small>This mode is single-threaded.</small>}
              </label>
              <label className="field">
                <span>Repetitions</span>
                <input type="number" min={1} max={100} value={reps} onChange={(e) => setReps(e.target.value)} />
              </label>
              <label className="field">
                <span>Warm-up runs (not counted)</span>
                <input type="number" min={0} max={5} value={warmup} onChange={(e) => setWarmup(e.target.value)} />
              </label>
            </div>
            <label className="field">
              <span>Timeout per run (seconds)</span>
              <input type="number" value={timeout} onChange={(e) => setTimeoutS(e.target.value)} />
            </label>
          </div>

          {proto.params.length > 0 && (
            <div className="card">
              <h3 style={{ marginTop: 0 }}>4. {proto.family} options</h3>
              {proto.params.map((p) => (
                <ParamInput key={p.key} spec={p} value={params[p.key]} onChange={(v) => setParam(p.key, v)} />
              ))}
            </div>
          )}

          {msg && <div className={`note ${msg.kind === "err" ? "err" : "info"}`}>{msg.text}</div>}
          <div className="row">
            <button disabled={busy || !canRun} onClick={submit}>
              {busy ? "Submitting…" : `Run ${runs} time${runs === 1 ? "" : "s"}`}
            </button>
            <span className="help">Pinned to CPUs {cat.pinned_cpus}. Results are stored in the history.</span>
          </div>
        </div>
      </div>
    </>
  );
}

function ParamInput({ spec, value, onChange }: { spec: ParamSpec; value: unknown; onChange: (v: unknown) => void }) {
  if (spec.type === "bool") {
    return (
      <label className="check">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        <span>
          <b>{spec.label}</b>
          {spec.help && <span className="help">{spec.help}</span>}
        </span>
      </label>
    );
  }
  return (
    <label className="field">
      <span>{spec.label}</span>
      {spec.type === "select" ? (
        <select value={String(value ?? spec.default)} onChange={(e) => onChange(e.target.value)}>
          {spec.options?.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      ) : (
        <input type="number" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />
      )}
      {spec.help && <small>{spec.help}</small>}
    </label>
  );
}
