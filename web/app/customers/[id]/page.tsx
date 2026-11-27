"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ACTION_LABEL, api, ddmmyyyy, inr, pretty } from "@/lib/api";
import { useSettings } from "@/lib/settings";
import Graph from "./graph";
import SignalsPanel from "./signals";
import DeliveryCard from "@/components/DeliveryCard";

const STAGES = ["world", "memory", "facts", "beliefs", "twin", "council", "decision"] as const;
type Stage = (typeof STAGES)[number];
const AGENT_NAME: Record<string, string> = { outcome_analyst: "Outcome Analyst", customer_advocate: "Customer Advocate", cost_strategist: "Cost Strategist" };

export default function CustomerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { sys } = useSettings();
  const [data, setData] = useState<any>(null);
  const [stage, setStage] = useState<Stage>("decision");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<any>(null);

  const load = () => api(`/customers/${id}`).then(setData).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [id]);

  const act = async (label: string, fn: () => Promise<any>) => {
    setBusy(label); setError(null);
    try { await fn(); await load(); } catch (e: any) { setError(e.message); } finally { setBusy(null); }
  };

  if (error && !data) return <main className="wrap"><div className="notice">{error}</div></main>;
  if (!data) return <main className="wrap muted">Loading brain…</main>;

  const brain = data.brain;
  const d = data.decision;
  const facts: any[] = brain.facts;
  const factById = Object.fromEntries(facts.map((f) => [f.id, f]));
  const persona = brain.persona;
  const llmOn = brain.llm?.enabled;

  const fmt = (f: any) => {
    if (f.value === null || f.value === undefined) return <span className="muted">–</span>;
    if (f.unit === "INR") return inr(f.value, sys);
    if (typeof f.value === "boolean") return f.value ? "yes" : "no";
    if (typeof f.value === "number" && f.value <= 1 && f.id.endsWith("rate")) return `${Math.round(f.value * 100)}%`;
    return `${f.value}${f.unit && f.unit !== "INR" ? " " + f.unit : ""}`;
  };

  return (
    <main className="wrap">
      <div className="muted" style={{ fontSize: 13, marginBottom: 8 }}><Link href="/">Dashboard</Link> / {brain.customer_id}</div>
      <section className="hero">
        <h1>{brain.display_name} <span className="muted" style={{ fontSize: 16, fontWeight: 400 }}>{brain.customer_id} · model sees only <span className="mono">{brain.alias}</span></span></h1>
        <p>{persona.narrative}</p>
        <div className="row" style={{ marginTop: 10 }}>
          <span className="chip">{persona.language}</span>
          {persona.city && <span className="chip">{persona.city}</span>}
          <span className="chip">mood: {persona.mood}</span>
          {persona.traits?.map((t: string) => <span key={t} className="chip">{t}</span>)}
          <span className="chip">persona by {persona.method}</span>
        </div>
      </section>

      {error && <div className="notice" style={{ marginBottom: 16 }}>{error}</div>}

      <section className="grid g2" style={{ marginBottom: 16, gridTemplateColumns: "1.3fr 1fr" }}>
        <div className="panel">
          <h3>Decision</h3>
          {d ? (
            <>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className={`status ${d.action}`} style={{ fontSize: 18 }}>{ACTION_LABEL[d.action]}</span>
                <span className="row" style={{ gap: 6 }}>
                  {d.arm === "holdout" && <span className="badge gray">holdout</span>}
                  <span className="badge gray">council: {d.council.method}</span>
                </span>
              </div>
              {d.channel && (
                <div className="grid g4" style={{ marginTop: 12 }}>
                  <div><div className="muted" style={{ fontSize: 12 }}>Channel</div><div className="ink" style={{ textTransform: "capitalize" }}>{d.channel}</div></div>
                  <div><div className="muted" style={{ fontSize: 12 }}>Send at</div><div className="ink">{ddmmyyyy(d.send_at)}</div></div>
                  <div><div className="muted" style={{ fontSize: 12 }}>Tone · language</div><div className="ink">{pretty(d.tone)} · {d.language}</div></div>
                  <div><div className="muted" style={{ fontSize: 12 }}>Confidence</div><div className="ink" title={d.confidence_meaning}>{d.confidence ?? "–"}</div></div>
                </div>
              )}
              {d.message_preview && <div className="quote" style={{ marginTop: 12 }}>{d.message_preview}</div>}
              <p style={{ marginTop: 12, marginBottom: 0 }}>{d.reason}</p>
              {d.holdout_note && <p className="muted" style={{ fontSize: 13 }}>{d.holdout_note}</p>}
              <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>Decided {ddmmyyyy(d.created_at)}</div>
            </>
          ) : <p className="muted">No decision yet.</p>}
          <div className="row" style={{ marginTop: 14 }}>
            <button className="btn" disabled={!!busy} onClick={() => act("Deciding", () => api(`/customers/${id}/decide`, { use_llm: true }))}>
              {llmOn ? "Decide again with Claude council" : "Decide again"}
            </button>
            <Link className="btn ghost" href={`/customers/${id}/brain`}>Open the brain graph</Link>
            <button className="btn ghost" disabled={!!busy} onClick={() => act("Rebuilding", () => api(`/customers/${id}/rebuild`, {}))}>Rebuild brain</button>
            {busy && <span className="orange">{busy}…</span>}
          </div>
        </div>

        <div className="panel">
          <h3>Ask this brain</h3>
          <p className="sub">Plain-language questions. Answers cite fact and belief ids{llmOn ? "" : " (rules mode matches facts; turn on Claude for open questions)"}.</p>
          <form className="row" onSubmit={async (e) => {
            e.preventDefault();
            if (!question.trim()) return;
            setAnswer({ answer: "Thinking…", cites: [] });
            setAnswer(await api(`/customers/${id}/ask`, { question }).catch((err) => ({ answer: err.message, cites: [] })));
          }}>
            <input type="text" style={{ flex: 1, minWidth: 200 }} placeholder={brain.pack === "emi_collection" ? "Will they pay this week? When do they reply?" : "Will they renew? What do they watch?"} value={question} onChange={(e) => setQuestion(e.target.value)} />
            <button className="btn ghost">Ask</button>
          </form>
          {answer && (
            <div style={{ marginTop: 12 }}>
              <div className="quote">{answer.answer}</div>
              <div style={{ marginTop: 6 }}>{answer.cites?.map((c: string) => <span key={c} className="chip mono">{c}</span>)}</div>
            </div>
          )}
          <h3 style={{ marginTop: 18 }}>Profile</h3>
          <table><tbody>
            {Object.entries(brain.profile).map(([k, v]) => <tr key={k}><td className="muted">{pretty(k)}</td><td className="ink">{String(v ?? "–")}</td></tr>)}
          </tbody></table>
        </div>
      </section>

      <DeliveryCard delivery={d?.delivery} />

      <SignalsPanel brain={brain} />

      <section className="panel">
        <h3>The knowledge chain: ask why, get receipts</h3>
        <div className="chain" style={{ marginBottom: 16 }}>
          {STAGES.map((s, i) => (
            <button key={s} className={stage === s ? "on" : ""} onClick={() => setStage(s)}>
              <div className="i">0{i + 1}</div>
              <div className="t">{s}</div>
              <div className="i">{stageCount(s, brain, d)}</div>
            </button>
          ))}
        </div>

        {stage === "world" && (
          <div>
            <p className="sub">One graph per customer, joined from your own tables. {brain.world.summary}.</p>
            <Graph world={brain.world} />
          </div>
        )}

        {stage === "memory" && (
          <div>
            <p className="sub">Free text read in time: “kal” means the day after it was written, not the day we read it.</p>
            {brain.memory.length === 0 ? <p className="muted">No signals in any note or reply.</p> : (
              <table>
                <thead><tr><th>Written</th><th>Signal</th><th>Refers to</th><th>Source</th><th>Read by</th></tr></thead>
                <tbody>{brain.memory.map((m: any) => (
                  <tr key={m.id}>
                    <td>{ddmmyyyy(m.written_on)}</td>
                    <td className="ink" style={{ textTransform: "capitalize" }}>{pretty(m.kind)}{m.detail ? `: ${m.detail}` : ""}</td>
                    <td>{m.resolved_date ? ddmmyyyy(m.resolved_date) : <span className="muted">–</span>}</td>
                    <td className="mono">{m.ref.source}:{m.ref.row_id}</td>
                    <td><span className="chip">{m.method}</span></td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </div>
        )}

        {stage === "facts" && (
          <div style={{ overflowX: "auto" }}>
            <p className="sub">Computed in code, never guessed. Each fact shows its formula and the rows it read.</p>
            <table>
              <thead><tr><th>Question</th><th>Answer</th><th>How</th><th>Cites</th></tr></thead>
              <tbody>{facts.map((f) => (
                <tr key={f.id}>
                  <td><div className="ink">{f.question}</div><div className="mono">{f.id}</div></td>
                  <td className="ink" style={{ fontWeight: 600, whiteSpace: "nowrap" }}>{fmt(f)}</td>
                  <td className="muted" style={{ fontSize: 13 }}>{f.formula}{f.kind === "extracted" && <span className="chip" style={{ marginLeft: 6 }}>from text</span>}</td>
                  <td className="mono" title={f.citations.map((c: any) => `${c.source}:${c.row_id}`).join(", ")}>
                    {f.citations.length ? `${f.citations.length} row${f.citations.length > 1 ? "s" : ""} · ${f.citations[0].source}:${f.citations[0].row_id}${f.citations.length > 1 ? "…" : ""}` : "–"}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}

        {stage === "beliefs" && (
          <div className="grid g2">
            {brain.beliefs.map((b: any) => (
              <div key={b.id} className="panel">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <h2 style={{ textTransform: "capitalize" }}>{pretty(b.id)}</h2>
                  <span className={`chip ${b.status === "formed" ? b.value : b.status}`}>{b.status === "formed" ? b.value : pretty(b.status)}</span>
                </div>
                <p style={{ margin: "6px 0" }}>{b.reasoning}</p>
                <div className="muted" style={{ fontSize: 13 }}>
                  score {b.score ?? "–"} · confidence {b.confidence} (sample adequacy, n = {b.evidence_n})
                </div>
                <div style={{ marginTop: 8 }}>
                  {b.cites.map((c: string) => (
                    <span key={c} className="chip mono" title={factById[c] ? `${factById[c].question} = ${JSON.stringify(factById[c].value)}` : ""}>
                      {c}{factById[c] ? ` = ${JSON.stringify(factById[c].value)}` : ""}
                    </span>
                  ))}
                </div>
                {b.judge && (
                  <div className="quote" style={{ marginTop: 8, borderColor: b.judge.agrees ? "#22C55E" : "#EF4444", background: "#fff" }}>
                    <b>Independent judge {b.judge.agrees ? "agrees" : "disagrees: sent to human review"}.</b> {b.judge.note}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {stage === "twin" && d && (
          <div>
            <p className="sub">
              The message is rehearsed on {brain.alias}’s digital twin first. {d.twin.note} Ladder, most outcome-proximate first:{" "}
              {d.twin.ladder.map((r: any) => `${pretty(r.rung)} ×${r.weight}`).join(", ")}.
              {d.twin.simulation_used && ` Persona role-play blended in at ${d.twin.sim_weight * 100}%.`}
            </p>
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead><tr><th>#</th><th>Candidate</th><th>Score</th><th>Evidence</th><th>Persona fit</th><th>Twin reaction</th></tr></thead>
                <tbody>{d.twin.candidates.slice(0, 8).map((c: any, i: number) => (
                  <tr key={i} style={i === 0 ? { background: "#FFF3EE" } : undefined}>
                    <td className="muted">{i + 1}</td>
                    <td className="ink" style={{ whiteSpace: "nowrap" }}>{c.channel} · {c.window} · {pretty(c.tone)}</td>
                    <td className="ink" style={{ fontWeight: 600 }}>{c.score}</td>
                    <td style={{ fontSize: 13 }}><span className="chip">{c.empirical.source}</span>{c.empirical.detail}</td>
                    <td style={{ fontSize: 13 }}>{c.modifiers.length ? c.modifiers.map((m: any) => <div key={m.why}>{m.delta > 0 ? "+" : ""}{m.delta} {m.why}</div>) : <span className="muted">–</span>}</td>
                    <td style={{ fontSize: 13 }}>{c.simulated ? <><b>{Math.round(c.simulated.probability * 100)}%</b> “{c.simulated.reaction}”</> : <span className="muted">{llmOn ? "not simulated" : "needs Claude"}</span>}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </div>
        )}

        {stage === "council" && d && (
          <div>
            <p className="sub">Three agents with different goals argue from the same facts. Dissent is recorded, not hidden.</p>
            <div className="grid g3">
              {d.council.stances.map((s: any) => (
                <div key={s.speaker} className={`speaker ${s.veto ? "veto" : ""}`}>
                  <div className="who">{AGENT_NAME[s.speaker] ?? s.speaker}</div>
                  <div className="muted" style={{ fontSize: 13, margin: "4px 0 8px" }}>
                    backs {d.twin.candidates[s.choice] ? `${d.twin.candidates[s.choice].channel} · ${d.twin.candidates[s.choice].window} · ${pretty(d.twin.candidates[s.choice].tone)}` : "–"}
                  </div>
                  {s.veto && <div style={{ color: "#EF4444", fontWeight: 600, marginBottom: 6 }}>Veto: {s.veto}</div>}
                  <div>{s.argument}</div>
                  <div style={{ marginTop: 8 }}>{s.cites?.map((c: string) => <span key={c} className="chip mono">{c}</span>)}</div>
                </div>
              ))}
            </div>
            <div className="quote" style={{ marginTop: 14 }}><b>Moderator:</b> {d.council.moderator.summary}</div>
          </div>
        )}

        {stage === "decision" && d && (
          <div className="grid g2">
            <div>
              <h3>Checked before every send</h3>
              <table><tbody>{d.policy_checks.map((c: any, i: number) => (
                <tr key={i}>
                  <td><span className={`status ${c.passed ? "contact" : "human_review"}`}>{c.passed ? "pass" : "stop"}</span></td>
                  <td className="ink">{c.check}{c.channel ? ` · ${c.channel}` : ""}</td>
                  <td className="muted" style={{ fontSize: 13 }}>{c.detail}</td>
                </tr>
              ))}</tbody></table>
            </div>
            <div>
              <h3>Receipts</h3>
              {d.receipts.map((r: any) => (
                <div key={r.stage} style={{ marginBottom: 10 }}>
                  <div className="ink" style={{ fontWeight: 700, textTransform: "capitalize" }}>{r.stage}</div>
                  <ul className="sq" style={{ fontSize: 13 }}>
                    {r.items.length ? r.items.slice(0, 6).map((it: string, i: number) => <li key={i}>{it}</li>) : <li className="muted">nothing</li>}
                    {r.items.length > 6 && <li className="muted">and {r.items.length - 6} more</li>}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </main>
  );
}

function stageCount(s: Stage, brain: any, d: any): string {
  switch (s) {
    case "world": return `${brain.world.edges.length} links`;
    case "memory": return `${brain.memory.length} signals`;
    case "facts": return `${brain.facts.length} facts`;
    case "beliefs": return `${brain.beliefs.length} judgements`;
    case "twin": return d ? `${d.twin.candidates.length} rehearsed` : "–";
    case "council": return d ? `3 agents` : "–";
    case "decision": return d ? ACTION_LABEL[d.action] : "–";
  }
}
