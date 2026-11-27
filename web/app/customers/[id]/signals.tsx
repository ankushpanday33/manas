"use client";

import { pretty } from "@/lib/api";

/** In-app events and the transparent predictions built on them. */
export default function SignalsPanel({ brain }: { brain: any }) {
  const p = brain.predictions ?? {};
  const fv: Record<string, any> = Object.fromEntries(brain.facts.map((f: any) => [f.id, f.value]));
  const emi = brain.pack === "emi_collection";
  const preds: [string, string][] = [
    ["purchase_propensity_7d", emi ? "Pays in the next 7 days" : "Renews or buys in 7 days"],
    ["churn_risk_14d", "Goes quiet for 14 days"],
    ["login_completion", "Finishes login"],
  ];

  return (
    <section className="panel" style={{ marginBottom: 16 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>Events and predictions</h3>
        <span className="badge gray">{p.rule_version ?? "events"}</span>
      </div>
      <div className="grid g3" style={{ marginTop: 12 }}>
        {preds.map(([k, label]) => {
          const x = p[k] ?? { status: "insufficient_evidence" };
          return (
            <div key={k} className="tile" style={{ borderTopColor: k === "churn_risk_14d" && (x.value ?? 0) > 0.5 ? "#F59E0B" : "#FF6623" }}>
              <div className="k">{label}</div>
              <div className="v">{x.value == null ? "–" : `${Math.round(x.value * 100)}%`}</div>
              {x.status !== "ok" ? <div className="n">{x.note ?? "not enough events yet"}</div> : (
                <div className="n">
                  {x.drivers.slice(0, 4).map((d: any) => (
                    <div key={d.feature}>{d.effect > 0 ? "▲" : "▼"} {pretty(d.feature)} = {String(d.value)} ({d.effect > 0 ? "+" : ""}{d.effect})</div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <ul className="sq" style={{ fontSize: 14, marginTop: 12 }}>
        <li>{fv.events_30d ?? 0} events in 30 days · {fv.cta_clicks_7d ?? 0} CTA clicks this week{fv.top_cta ? ` · most clicked: ${pretty(fv.top_cta)}` : ""}</li>
        <li>{fv.abandoned_checkout ? <>Left <b>{pretty(fv.abandoned_checkout)}</b> halfway in the app</> : emi ? "No unfinished payment" : "No unfinished checkout"}</li>
        <li>{fv.login_dropoff ? "Started login without finishing at least once" : "No login drop-off"}</li>
      </ul>
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>Each prediction is a transparent logistic score over named event features; the drivers are exactly what moved it.</p>
    </section>
  );
}
