"use client";

import { useEffect, useState } from "react";
import { api, pretty } from "@/lib/api";

const MCP_TOOLS = [
  ["list_users", "Users and their next action, filter by action"],
  ["get_user_brain", "Chart, persona, beliefs, predictions, key facts (no birth details)"],
  ["get_next_action", "Offer, channel, platform and why, fallback, language, ready message"],
  ["decide_now", "Re-run the decision for one user"],
  ["explain_decision", "The decision path, layer by layer"],
  ["ask_brain", "Plain-language question about one user"],
  ["ingest_events", "Store events (generic, Mixpanel or PostHog shape)"],
  ["sync_analytics", "Pull recent events from Mixpanel or PostHog"],
  ["push_decisions", "Write next actions to Mixpanel or PostHog"],
  ["rebuild_and_decide", "Rebuild brains after new events and decide again"],
  ["messaging_platforms", "Platforms per channel and their status"],
];

export default function IntegrationsPage() {
  const [data, setData] = useState<any>(null);
  const [out, setOut] = useState<Record<string, any>>({});
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => { api("/integrations").then(setData).catch(() => {}); }, []);

  const run = async (key: string, path: string, body: any) => {
    setBusy(key);
    try { setOut((o) => ({ ...o, [key]: null })); const r = await api(path, body); setOut((o) => ({ ...o, [key]: r })); }
    catch (e: any) { setOut((o) => ({ ...o, [key]: { error: e.message } })); }
    finally { setBusy(null); }
  };

  const mcpJson = JSON.stringify({ mcpServers: { "manas": { command: "uv", args: ["run", "--directory", "backend", "python", "-m", "app.mcp_server"] } } }, null, 2);

  return (
    <main className="wrap">
      <section className="hero">
        <h1>Integrations: <em>events in, decisions out</em></h1>
        <p>Collect events from Mixpanel or PostHog, push each user's next action back as profile properties, see which messaging platform serves
          each channel, and plug the brain into Claude through MCP. Without keys every call is a dry run that shows the exact request.</p>
      </section>
      {!data ? <p className="muted">Loading…</p> : (
        <>
          <section className="grid g2" style={{ marginBottom: 16 }}>
            {(["mixpanel", "posthog"] as const).map((p) => {
              const st = data.analytics[p];
              return (
                <div key={p} className="panel">
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <h2 style={{ textTransform: "capitalize" }}>{p === "posthog" ? "PostHog" : "Mixpanel"}</h2>
                    <span className="row" style={{ gap: 6 }}>
                      <span className={`status ${st.can_sync ? "contact" : "hold"}`}>sync {st.can_sync ? "ready" : "dry run"}</span>
                      <span className={`status ${st.can_push ? "contact" : "hold"}`}>push {st.can_push ? "ready" : "dry run"}</span>
                    </span>
                  </div>
                  <p className="mono" style={{ margin: "6px 0" }}>{p === "mixpanel" ? `region ${st.region} · ${st.export_host} · ${st.api_host}` : `${st.host} · ${st.ingest_host}`}</p>
                  <div style={{ fontSize: 13 }}><span className="muted">Env vars: </span>{st.env.map((e: string) => <span key={e} className="chip mono">{e}</span>)}</div>
                  <div className="row" style={{ marginTop: 10 }}>
                    <button className="btn ghost" disabled={!!busy} onClick={() => run(`${p}-sync`, `/integrations/${p}/sync`, { days: 7 })}>Sync last 7 days</button>
                    <button className="btn ghost" disabled={!!busy} onClick={() => run(`${p}-push`, `/integrations/${p}/push`, {})}>Push next actions</button>
                  </div>
                  {["sync", "push"].map((k) => out[`${p}-${k}`] && (
                    <pre key={k} className="mono" style={{ background: "#F9FAFB", border: "1px solid #E5E7EB", padding: 10, marginTop: 10, maxHeight: 240, overflow: "auto" }}>
                      {JSON.stringify(out[`${p}-${k}`], null, 2)}
                    </pre>
                  ))}
                </div>
              );
            })}
          </section>

          <section className="panel" style={{ marginBottom: 16 }}>
            <h3>Live collection (webhook)</h3>
            <p style={{ margin: "0 0 6px" }}>Point a PostHog webhook destination, a Mixpanel data pipeline or your own backend at:</p>
            <p className="mono">POST {typeof window !== "undefined" ? window.location.origin : ""}/api/collect/posthog · /api/collect/mixpanel · /api/collect/generic
              {data.analytics.collect.secret_required ? " · header X-Manas-Secret required" : " · set MANAS_COLLECT_SECRET to require a shared secret"}</p>
            <details style={{ fontSize: 13 }}><summary className="muted" style={{ cursor: "pointer" }}>Event name mapping ({Object.keys(data.event_map).length})</summary>
              <div style={{ marginTop: 6 }}>{Object.entries(data.event_map).map(([a, b]) => <span key={a} className="chip mono">{a} → {String(b)}</span>)}</div>
            </details>
            <p style={{ fontSize: 13, marginBottom: 0 }}><span className="muted">Pushed as user properties: </span>{data.pushed_properties.map((p: string) => <span key={p} className="chip mono">{p}</span>)}</p>
            <p style={{ fontSize: 13, margin: "4px 0 0" }}><span className="muted">Never pushed: </span>{data.never_pushed.join(", ")}.</p>
          </section>

          <section className="panel" style={{ marginBottom: 16 }}>
            <h3>Messaging platforms</h3>
            <table>
              <thead><tr><th>Channel</th><th>Platform</th><th>Status</th><th>Switch on with</th><th>Cost (illustrative)</th></tr></thead>
              <tbody>{data.platforms.map((p: any) => (
                <tr key={p.id}>
                  <td className="ink">{pretty(p.channel)}</td><td>{p.name}</td>
                  <td><span className={`status ${p.configured ? "contact" : "hold"}`}>{p.configured ? "configured" : "not configured"}</span></td>
                  <td>{p.env.length ? p.env.map((e: string) => <span key={e} className="chip mono">{e}</span>) : <span className="muted">built in</span>}</td>
                  <td>₹{Number(p.cost_inr).toFixed(2)}</td>
                </tr>
              ))}</tbody>
            </table>
            <p className="muted" style={{ fontSize: 12 }}>Platform choice per message: configured first, then your measured delivery rate per platform, then cost. Override the list with MANAS_PROVIDERS_JSON.</p>
          </section>

          <section className="panel">
            <h3>MCP: use the brain from Claude</h3>
            <p style={{ margin: "0 0 6px" }}>This repo ships an MCP server. Claude Code picks up <span className="mono">.mcp.json</span> in the repo root; for Claude Desktop, add the same block to its config with the full path to <span className="mono">backend</span>.</p>
            <pre className="mono" style={{ background: "#F9FAFB", border: "1px solid #E5E7EB", padding: 10 }}>{mcpJson}</pre>
            <table><tbody>{MCP_TOOLS.map(([t, d]) => <tr key={t}><td className="mono ink">{t}</td><td>{d}</td></tr>)}</tbody></table>
          </section>
        </>
      )}
    </main>
  );
}
