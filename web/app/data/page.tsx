"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, pretty } from "@/lib/api";

type Source = { source: string; description: string; id_field: string; required: string[]; columns: string[]; rows_now: number };
type Schema = { pack: string; sources: Source[]; formats: string[]; dates: string };

async function upload(source: string, file: File, mode: string, pack: string) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("mode", mode);
  fd.append("pack", pack);
  const res = await fetch(`/api/ingest/${source}`, { method: "POST", body: fd });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  return body;
}

export default function DataPage() {
  const [packs, setPacks] = useState<any[]>([]);
  const [pack, setPack] = useState<string>("");
  const [schema, setSchema] = useState<Schema | null>(null);
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [mode, setMode] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Record<string, any>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const loadSchema = (pk?: string) => api(`/ingest/schema${pk ? `?pack=${pk}` : ""}`).then((s: Schema) => { setSchema(s); setPack(s.pack); });
  useEffect(() => {
    api("/packs").then(setPacks).catch(() => {});
    loadSchema().catch((e) => setMsg(`Cannot reach the backend: ${e.message}`));
  }, []);

  const doUpload = async (src: string) => {
    const f = files[src];
    if (!f) return;
    setBusy(src); setMsg(null);
    try {
      const r = await upload(src, f, mode[src] ?? "append", pack);
      setResult((x) => ({ ...x, [src]: r }));
      await loadSchema(pack);
    } catch (e: any) {
      setResult((x) => ({ ...x, [src]: { error: e.message } }));
    } finally { setBusy(null); }
  };

  const buildAll = async () => {
    setBusy("build"); setMsg(null);
    try {
      const b = await api("/brains/build", { pack });
      const d = await api("/decide/all", { use_llm: false });
      setMsg(`Built ${b.built} brains and made ${d.decided} decisions from your data.`);
    } catch (e: any) { setMsg(e.message); } finally { setBusy(null); }
  };

  const resetAll = async () => {
    if (!window.confirm("Delete ALL uploaded data, brains and decisions in this app? This cannot be undone.")) return;
    setBusy("reset");
    try { await api("/data/reset", { confirm: true }); setResult({}); setMsg("All data deleted."); await loadSchema(pack); }
    catch (e: any) { setMsg(e.message); } finally { setBusy(null); }
  };

  return (
    <main className="wrap">
      <section className="hero">
        <h1>Upload <em>your data</em></h1>
        <p>Drop in your own files, with your own column names. We match the columns, convert DD/MM/YYYY dates, check every row and tell you
          exactly what loaded and what did not. Then build a brain for every person in them.</p>
      </section>

      {msg && <div className="notice" style={{ marginBottom: 16 }}>{msg}</div>}

      <section className="panel" style={{ marginBottom: 16 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="row">
            {packs.length > 1 && (
              <select value={pack} onChange={(e) => loadSchema(e.target.value)}>
                {packs.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
              </select>
            )}
            <span className="muted" style={{ fontSize: 13 }}>Formats: {schema?.formats.join(" · ")}. Dates: {schema?.dates}.</span>
          </div>
          <div className="row">
            <button className="btn" disabled={!!busy} onClick={buildAll}>{busy === "build" ? "Building…" : "Build brains and decide"}</button>
            <button className="btn ghost" disabled={!!busy} onClick={resetAll}>Delete all data</button>
          </div>
        </div>
        <p className="sub" style={{ margin: "10px 0 0" }}>
          Start with the people file; every other file links to it through <span className="mono">customer_id</span>. “Append” adds and updates rows by id;
          “Replace” clears that file’s old rows first.
        </p>
      </section>

      <section className="grid g2">
        {schema?.sources.map((s) => {
          const r = result[s.source];
          return (
            <div key={s.source} className="panel">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h2 style={{ textTransform: "capitalize" }}>{pretty(s.source)}</h2>
                <span className="badge gray">{s.rows_now} rows now</span>
              </div>
              <p className="sub">{s.description}</p>
              <div style={{ fontSize: 13, marginBottom: 8 }}>
                <span className="muted">Required: </span>{s.required.map((c) => <span key={c} className="chip high mono">{c}</span>)}
              </div>
              <details style={{ fontSize: 13, marginBottom: 10 }}>
                <summary className="muted" style={{ cursor: "pointer" }}>All columns we understand ({s.columns.length})</summary>
                <div style={{ marginTop: 6 }}>{s.columns.map((c) => <span key={c} className="chip mono">{c}</span>)}</div>
              </details>
              <div className="row">
                <input type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm,.json,.ndjson,.jsonl"
                  onChange={(e) => setFiles((x) => ({ ...x, [s.source]: e.target.files?.[0] ?? null }))} />
                <select value={mode[s.source] ?? "append"} onChange={(e) => setMode((x) => ({ ...x, [s.source]: e.target.value }))}>
                  <option value="append">Append</option>
                  <option value="replace">Replace</option>
                </select>
                <button className="btn" disabled={!files[s.source] || !!busy} onClick={() => doUpload(s.source)}>
                  {busy === s.source ? "Uploading…" : "Upload"}
                </button>
                <a className="btn ghost" href={`/api/ingest/template/${s.source}?pack=${pack}`}>Template</a>
              </div>

              {r && (
                <div style={{ marginTop: 12, fontSize: 13 }}>
                  {r.error ? <div className="notice" style={{ borderColor: "#EF4444" }}>{r.error}</div> : (
                    <>
                      <div className="row" style={{ gap: 14 }}>
                        <span className="status contact">{r.loaded} loaded</span>
                        {r.skipped > 0 && <span className="status human_review">{r.skipped} skipped</span>}
                        <span className="muted">{r.rows_in_file} rows in {r.file}</span>
                      </div>
                      {Object.keys(r.column_mapping).length > 0 && (
                        <div style={{ marginTop: 6 }}><span className="muted">Matched: </span>
                          {Object.entries(r.column_mapping).map(([a, b]) => <span key={a} className="chip mono">{a} → {String(b)}</span>)}</div>
                      )}
                      {r.unrecognised_columns.length > 0 && (
                        <div style={{ marginTop: 6 }}><span className="muted">Kept but not used by the brain yet: </span>
                          {r.unrecognised_columns.map((c: string) => <span key={c} className="chip low mono">{c}</span>)}</div>
                      )}
                      {r.missing_required_columns.length > 0 && (
                        <div className="notice" style={{ marginTop: 6 }}>Missing required column: {r.missing_required_columns.join(", ")}</div>
                      )}
                      {r.skipped_rows.length > 0 && (
                        <ul className="sq" style={{ marginTop: 6 }}>
                          {r.skipped_rows.slice(0, 6).map((x: any) => <li key={x.row}>Row {x.row}: {x.reason}</li>)}
                          {r.skipped > 6 && <li className="muted">and {r.skipped - 6} more</li>}
                        </ul>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </section>

      <p className="muted" style={{ fontSize: 13, marginTop: 16 }}>
        After building, open the <Link href="/">dashboard</Link> to see every brain. Your files stay on this server; nothing is sent anywhere else
        {" "}unless Claude is switched on, and then only pseudonymised text.
      </p>
    </main>
  );
}
