const LAYERS = [
  ["World", "One graph per customer, joined from your own tables: customers, loans, payments, promises, messages, subscriptions, usage."],
  ["Memory", "Notes and replies read in time, in English, Hindi and Hinglish. “Kal pay karunga” written on 02/10 means 03/10. Every signal points to its row."],
  ["Facts", "Twenty-odd answers computed in code (overdue, promise keep rate, read rate by channel, best slot), each with its formula and cited rows."],
  ["Beliefs", "Judgements like willingness to pay or renewal intent. Each cites its facts. Too little evidence returns insufficient_evidence; an independent judge can send a belief to human review."],
  ["Persona", "A portrait of the person built from the brain, the way MiroFish builds agent profiles. The model only ever sees a pseudonym."],
  ["Digital twin", "Every candidate (channel × window × tone) is scored on a metric ladder from the customer’s own outcomes, then rehearsed on the twin when Claude is on."],
  ["Council", "Outcome Analyst, Customer Advocate and Cost Strategist argue from the same facts, the way BettaFish’s forum works. A moderator decides; dissent is kept."],
  ["Guards", "Consent, DND, RBI 08:00 to 19:00 recovery hours, frequency caps, open promises and disputes are checked before any candidate is scored."],
  ["Uplift guard", "People who would convert anyway get no message. That saves money and is what makes uplift real."],
  ["Holdout", "A fixed 10% is never messaged. Treatment minus holdout is the only number that proves the engine works."],
];

export default function How() {
  return (
    <main className="wrap">
      <section className="hero">
        <h1>How Manas <em>decides</em></h1>
        <p>Ten layers, each traceable to the one below. Runs fully on deterministic rules; Claude adds reading, judging, role-play and debate when a key is set.</p>
      </section>
      <section className="grid g2">
        {LAYERS.map(([t, d], i) => (
          <div key={t} className="panel">
            <h3>{String(i + 1).padStart(2, "0")} · {t}</h3>
            <p style={{ margin: 0 }}>{d}</p>
          </div>
        ))}
      </section>
    </main>
  );
}
