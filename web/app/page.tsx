"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ACTION_LABEL, api, ddmmyyyy, inr, pretty } from "@/lib/api";
import { useSettings } from "@/lib/settings";

type Customer = {
  customer_id: string; alias: string; display_name: string; pack: string; language: string; city: string; mood: string;
  beliefs: Record<string, { value: string | null; status: string }>;
  headline: Record<string, any>;
  decision: { action: string; channel: string | null; window: string | null; tone: string | null; send_at: string | null; arm: string; confidence: number | null } | null;
};

const BELIEF_ORDER = ["high", "medium", "low", "needs_review", "insufficient_evidence"];
const BELIEF_COLOR: Record<string, string> = { high: "#FF6623", medium: "#FFB089", low: "#E5E7EB", needs_review: "#F59E0B", insufficient_evidence: "#FFFFFF" };

export default function Dashboard() {
  const { sys } = useSettings();
  const router = useRouter();
  const [packs, setPacks] = useState<any[]>([]);
  const [pack, setPack] = useState("emi_collection");
  const [stats, setStats] = useState<any>(null);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [q, setQ] = useState("");

  const refresh = async () => {
    const [s, c] = await Promise.all([api("/stats"), api("/customers")]);
    setStats(s);
    setCustomers(c);
    setPack(s.pack);
  };

  useEffect(() => {
    api("/packs").then(setPacks).catch((e) => setError(String(e.message)));
    refresh().catch((e) => setError(`Cannot reach the brain engine on port 8000 (${e.message}). Start the backend first.`));
  }, []);

  const run = async (label: string, fn: () => Promise<any>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const runAll = () =>
    run("Running the whole pipeline", async () => {
      await api("/demo/load", { pack, customers: 120 });
      await api("/brains/build", { pack });
      await api("/decide/all", { use_llm: false });
      await api("/outcomes/simulate", {});
    });

  const shown = useMemo(
    () =>
      customers.filter(
        (c) =>
          (filter === "all" || c.decision?.action === filter) &&
          (!q || `${c.display_name} ${c.customer_id} ${c.city} ${c.language}`.toLowerCase().includes(q.toLowerCase())),
      ),
    [customers, filter, q],
  );

  const activePack = packs.find((p) => p.id === pack);
  const actions = stats?.actions ?? {};
  const up = stats?.uplift;

  return (
    <main className="wrap">
      <section className="hero">
        <h1>
          Every customer gets a <em>brain</em>. Every decision shows its receipts.
        </h1>
        <p>
          Manas joins your scattered tables into one living brain per customer: a graph, a dated memory of what they said, facts computed in code,
          beliefs checked by an independent judge, and a digital twin that rehearses each message before it is sent. Three agents argue, a moderator
          decides, and a 10% holdout proves whether it worked.
        </p>
      </section>

      {error && <div className="notice" style={{ marginBottom: 16 }}>{error}</div>}

      <section className="panel" style={{ marginBottom: 16 }}>
        <h3>Goal pack</h3>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="row">
            <select value={pack} onChange={(e) => setPack(e.target.value)}>
              {packs.map((p) => (
                <option key={p.id} value={p.id}>{p.title}</option>
              ))}
            </select>
            <button className="btn" disabled={!!busy} onClick={runAll}>Load demo data and run everything</button>
            <button className="btn ghost" disabled={!!busy} onClick={() => run("Building brains", () => api("/brains/build", { pack }))}>Rebuild brains</button>
            <button className="btn ghost" disabled={!!busy} onClick={() => run("Deciding", () => api("/decide/all", { use_llm: false }))}>Decide for all</button>
          </div>
          <div className="row muted" style={{ fontSize: 13 }}>
            {stats?.llm?.enabled ? <span className="badge">Claude on · {stats.llm.model}</span> : <span className="badge gray">Rules only</span>}
            {busy && <span className="orange">{busy}…</span>}
          </div>
        </div>
        {activePack && (
          <div className="grid g3" style={{ marginTop: 14, fontSize: 13 }}>
            <div><span className="muted">Objects</span><br /><span className="ink">{activePack.objects.join(" · ")}</span></div>
            <div><span className="muted">Beliefs it forms</span><br /><span className="ink">{activePack.beliefs.map(pretty).join(" · ")}</span></div>
            <div><span className="muted">Counts as converted</span><br /><span className="ink">{activePack.conversion}</span></div>
          </div>
        )}
      </section>

      <section className="grid g5" style={{ marginBottom: 16 }}>
        <div className="tile"><div className="k">Brains</div><div className="v">{stats?.brains ?? 0}</div><div className="n">one per customer</div></div>
        <div className="tile"><div className="k">Contact</div><div className="v">{actions.contact ?? 0}</div><div className="n">rehearsed on the twin first</div></div>
        <div className="tile"><div className="k">No message needed</div><div className="v">{actions.no_action ?? 0}</div><div className="n">would convert anyway</div></div>
        <div className="tile"><div className="k">Hold / Human</div><div className="v">{(actions.hold ?? 0) + " / " + (actions.human_review ?? 0)}</div><div className="n">promise, cap, dispute, hardship</div></div>
        <div className="tile">
          <div className="k">Uplift vs holdout {up?.simulated && <span className="badge" style={{ marginLeft: 4 }}>Simulated</span>}</div>
          <div className="v">{up?.uplift_pts == null ? "–" : `${up.uplift_pts > 0 ? "+" : ""}${up.uplift_pts} pts`}</div>
          <div className="n">
            {up?.treatment?.rate != null ? `${Math.round(up.treatment.rate * 100)}% treated vs ${Math.round((up.holdout.rate ?? 0) * 100)}% holdout` : "no outcomes yet"}
          </div>
        </div>
      </section>

      {stats?.beliefs && Object.keys(stats.beliefs).length > 0 && (
        <section className="panel" style={{ marginBottom: 16 }}>
          <h3>What the brains believe</h3>
          <div className="grid g2">
            {Object.entries(stats.beliefs as Record<string, Record<string, number>>).map(([id, dist]) => {
              const total = Object.values(dist).reduce((a, b) => a + b, 0);
              return (
                <div key={id}>
                  <div className="row" style={{ justifyContent: "space-between", fontSize: 13 }}>
                    <span className="ink" style={{ textTransform: "capitalize" }}>{pretty(id)}</span>
                    <span className="muted">
                      {BELIEF_ORDER.filter((k) => dist[k]).map((k) => `${pretty(k)} ${dist[k]}`).join(" · ")}
                    </span>
                  </div>
                  <div className="bar" style={{ border: "1px solid #E5E7EB" }}>
                    {BELIEF_ORDER.filter((k) => dist[k]).map((k) => (
                      <div key={k} title={`${pretty(k)}: ${dist[k]}`} style={{ width: `${(dist[k] / total) * 100}%`, background: BELIEF_COLOR[k] }} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section className="panel" id="customers">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
          <h2>Customers</h2>
          <div className="row">
            <input type="text" placeholder="Search name, city, language" value={q} onChange={(e) => setQ(e.target.value)} />
            <select value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="all">All decisions</option>
              {Object.keys(ACTION_LABEL).map((a) => (
                <option key={a} value={a}>{ACTION_LABEL[a]} ({actions[a] ?? 0})</option>
              ))}
            </select>
          </div>
        </div>
        {customers.length === 0 ? (
          <p className="muted">No brains yet. Pick a goal pack and press “Load demo data and run everything”.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>{pack === "emi_collection" ? "Overdue" : "Plan"}</th>
                  <th>Beliefs</th>
                  <th>Decision</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {shown.slice(0, 200).map((c) => (
                  <tr key={c.customer_id} className="click" onClick={() => router.push(`/customers/${c.customer_id}`)}>
                    <td>
                      <Link href={`/customers/${c.customer_id}`} className="ink" style={{ fontWeight: 600 }}>{c.display_name}</Link>
                      <div className="muted" style={{ fontSize: 12 }}>{c.customer_id} · {c.language} · {c.city}</div>
                    </td>
                    <td>
                      {pack === "emi_collection" ? (
                        <>
                          <div className="ink">{inr(c.headline.overdue_amount, sys)}</div>
                          <div className="muted" style={{ fontSize: 12 }}>{c.headline.days_past_due} days past due</div>
                        </>
                      ) : (
                        <>
                          <div className="ink">{c.headline.plan}</div>
                          <div className="muted" style={{ fontSize: 12 }}>{inr(c.headline.price, sys)} · renews in {c.headline.days_to_renewal} days</div>
                        </>
                      )}
                    </td>
                    <td style={{ maxWidth: 360 }}>
                      {Object.entries(c.beliefs).map(([id, b]) => (
                        <span key={id} className={`chip ${b.status === "formed" ? b.value : b.status}`}>
                          {pretty(id)}: {b.status === "formed" ? b.value : pretty(b.status)}
                        </span>
                      ))}
                    </td>
                    <td>
                      {c.decision ? (
                        <>
                          <span className={`status ${c.decision.action}`}>{ACTION_LABEL[c.decision.action]}</span>
                          {c.decision.channel && (
                            <div className="muted" style={{ fontSize: 12 }}>
                              {c.decision.channel} · {c.decision.window} · {pretty(c.decision.tone)}
                            </div>
                          )}
                          {c.decision.arm === "holdout" && <span className="badge gray">holdout</span>}
                        </>
                      ) : (
                        <span className="muted">–</span>
                      )}
                    </td>
                    <td className="muted" style={{ fontSize: 13 }}>{ddmmyyyy(c.decision?.send_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
