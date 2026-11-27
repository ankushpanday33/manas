"""Decision pipeline: brain -> policy -> twin -> council -> one decision with its receipts.

Every customer is assigned once, deterministically, to treatment or a 10% holdout that gets no message.
Comparing the two is the only honest way to claim uplift, so it is built in from day one.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, time, timedelta
from typing import Any

from . import council, privacy, store, twin
from .packs import get_pack

HOLDOUT_PCT = 10


def arm_for(customer_id: str) -> str:
    return "holdout" if int(hashlib.sha256(customer_id.encode()).hexdigest(), 16) % 100 < HOLDOUT_PCT else "treatment"


def policy_checks(brain: dict[str, Any], pack: dict[str, Any], today: date) -> tuple[set[str], list[dict[str, Any]], str | None]:
    """Returns (allowed channels, checks, blocking action or None). Checks run before any candidate is scored."""
    prof = brain["profile"]
    fv = {f["id"]: f["value"] for f in brain["facts"]}
    checks, allowed = [], set()

    def yes(v: Any) -> bool:
        return str(v).strip().lower() in {"1", "true", "yes", "y"}

    for ch in pack["channels"]:
        key = {"whatsapp": "consent_whatsapp", "sms": "consent_sms", "voice": "consent_voice", "push": "consent_whatsapp"}.get(ch)
        ok = yes(prof.get(key)) if ch != "push" else True
        if ch == "voice" and yes(prof.get("dnd")):
            ok = False
            checks.append({"check": "DND registry", "channel": ch, "passed": False, "detail": "number is on DND: no calls"})
        checks.append({"check": "consent", "channel": ch, "passed": ok, "detail": f"{key or 'app install'} = {prof.get(key, 'n/a')}"})
        if ok:
            allowed.add(ch)

    cap = pack["frequency_cap"]
    week = fv.get("contacts_last_7d") or 0
    capped = week >= cap["per_week"]
    checks.append({"check": "frequency cap", "passed": not capped, "detail": f"{week} contacts in 7 days, cap {cap['per_week']}"})
    checks.append({"check": "quiet hours", "passed": True, "detail": pack["quiet_hours_note"]})

    block = None
    open_promise = fv.get("open_promise_date")
    if open_promise and date.fromisoformat(open_promise) >= today:
        block = "hold"
        checks.append({"check": "open promise", "passed": False, "detail": f"customer promised to pay on {open_promise}: messages held until then"})
    if fv.get("dispute_flag"):
        block = "human_review"
        checks.append({"check": "dispute", "passed": False, "detail": "dispute on record: contact stops, a person resolves it"})
    if capped and not block:
        block = "hold"
    if not allowed and not block:
        block = "hold"
        checks.append({"check": "reachable channel", "passed": False, "detail": "no channel has consent"})
    return allowed, checks, block


def converts_anyway(brain: dict[str, Any]) -> str | None:
    """Uplift guard: a message only earns its cost if it changes the outcome. Skip people who convert on their own."""
    fv = {f["id"]: f["value"] for f in brain["facts"]}
    b = {x["id"]: x for x in brain["beliefs"]}
    if brain["pack"] == "emi_collection":
        if (fv.get("on_time_rate") or 0) >= 0.9 and (fv.get("days_past_due") or 99) <= 5 and (fv.get("payments_12m") or 0) >= 6:
            return f"pays on their own: on time {fv['on_time_rate']:.0%} of the time and only {fv['days_past_due']} days late. Re-check in 3 days."
    else:
        if fv.get("auto_renew") and b.get("renewal_intent", {}).get("value") == "high" and (fv.get("days_since_last_use") or 99) <= 7:
            return "auto-renew is on, renewal intent is high and they used the app this week: a message would not change the outcome."
    return None


def _fmt_inr(v: Any) -> str:
    try:
        return "₹" + f"{int(float(v)):,}"
    except (TypeError, ValueError):
        return "₹0"


def render_values(brain: dict[str, Any], scrub: bool = False) -> dict[str, Any]:
    fv = {f["id"]: f["value"] for f in brain["facts"]}
    renews = fv.get("days_to_renewal")
    return dict(
        name="{name}" if scrub else brain.get("display_name", "").split(" ")[0],
        amount=_fmt_inr(fv.get("overdue_amount")), dpd=fv.get("days_past_due", ""), link="pay.link/xyz",
        plan=fv.get("plan", ""), minutes=fv.get("minutes_30d", ""), top_content=fv.get("top_content", "your favourites"),
        date=(date.fromisoformat(brain["as_of"]) + timedelta(days=renews)).strftime("%d/%m/%Y") if isinstance(renews, int) else "",
    )


def make_renderer(brain: dict[str, Any], pack: dict[str, Any]):
    def render(tone: str, scrub: bool = False) -> str:
        return pack["templates"][tone].format(**render_values(brain, scrub))
    return render


def delivery_plan(brain: dict[str, Any], chosen: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    """Platform, fallback, language, script and channel-shaped copy for the chosen action."""
    from . import llm, messaging

    recs = store.records_for(brain["customer_id"])
    texts = [l.get("collections_note", "") for l in recs.get("loans", [])] + \
            [c.get("reply_text", "") for c in recs.get("communications", []) if c.get("direction") == "in"]
    plan = messaging.plan(chosen["channel"], chosen["tone"], brain["profile"].get("preferred_language"), [t for t in texts if t],
                          render_values(brain), recs.get("communications", []), allowed)
    msg = plan["message"]
    if msg["translation_needed"] and llm.enabled():
        out = llm.ask_json("Translate this short customer message into the target language, natural and respectful. Keep names, amounts, "
                           "dates and the link exactly. No new claims, no threats.",
                           f"Target: {plan['language']['template_language']}\nText: {msg['body']}",
                           {"type": "object", "properties": {"text": {"type": "string"}}}, max_tokens=600)
        if out and out.get("text"):
            msg.update(body=out["text"], template_language=plan["language"]["template_language"], translation_needed=False,
                       note=f"translated by {llm.MODEL}; review before registering the template")
    return plan


def next_slot(window: str, pack: dict[str, Any], now: datetime, not_before: date | None = None) -> datetime:
    start, end = pack["windows"][window]
    day = max(now.date(), not_before or now.date())
    candidate = datetime.combine(day, time(start, 30 if start == 17 else 40 if start >= 18 else 15))
    if day == now.date() and now >= datetime.combine(day, time(end - 1, 0)):
        candidate += timedelta(days=1)
    elif day == now.date() and now > candidate:
        candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=10)
    return candidate


def decide(customer_id: str, use_llm: bool = True, now: datetime | None = None, pop: dict[str, Any] | None = None) -> dict[str, Any]:
    """`pop` (population stats) can be passed in by batch callers so it is computed once, not once per customer."""
    brain = store.get_brain(customer_id)
    if not brain:
        raise KeyError(customer_id)
    now = now or datetime.now()
    pack = get_pack(brain["pack"])
    today = date.fromisoformat(brain["as_of"])
    arm = arm_for(customer_id)
    render = make_renderer(brain, pack)

    allowed, checks, block = policy_checks(brain, pack, today)
    anyway = converts_anyway(brain)
    checks.append({"check": "uplift guard", "passed": anyway is None, "detail": anyway or "a message is expected to change the outcome"})
    if anyway and not block:
        block = "no_action"
    pop =pop if pop is not None else twin.population_stats(store.all_brains())
    sim = twin.simulate(brain, pack, pop, render, allowed=allowed)
    debate = council.deliberate(brain, sim, use_llm=use_llm and not block)

    mod = debate["moderator"]
    action = block or mod["action"]
    chosen = sim["candidates"][mod["choice"]] if action == "contact" and mod.get("choice") is not None else None
    if action == "contact" and sim["status"] == "insufficient_evidence":
        action, chosen = "human_review", None

    fv = {f["id"]: f["value"] for f in brain["facts"]}
    decision: dict[str, Any] = {
        "customer_id": customer_id, "alias": brain["alias"], "pack": brain["pack"],
        "created_at": now.isoformat(timespec="seconds"), "arm": arm,
        "action": action, "sent": False,
        "channel": chosen["channel"] if chosen else None, "window": chosen["window"] if chosen else None,
        "tone": chosen["tone"] if chosen else None,
        "language": brain["persona"].get("language"),
        "send_at": None, "message_preview": None,
        "confidence": None, "confidence_meaning": "sample adequacy: how much of this customer's own evidence backs the choice",
        "policy_checks": checks, "twin": sim, "council": debate,
    }
    if chosen:
        hold_until = fv.get("open_promise_date")
        decision["send_at"] = next_slot(chosen["window"], pack, now, date.fromisoformat(hold_until) if hold_until else None).isoformat(timespec="minutes")
        decision["delivery"] = delivery_plan(brain, chosen, allowed)
        decision["message_preview"] = decision["delivery"]["message"]["body"] or render(chosen["tone"])
        decision["confidence"] = round(min(1.0, chosen["empirical"]["evidence_n"] / 12), 2) if chosen["empirical"]["source"] == "customer" else 0.15
    if arm == "holdout":
        decision["holdout_note"] = "Holdout arm: decided but deliberately not sent, so uplift can be measured against it."

    decision["reason"] = _reason(decision, brain, chosen, mod)
    decision["receipts"] = _receipts(brain, decision, chosen)
    did = store.save_decision(customer_id, decision["created_at"], arm, decision)
    decision["decision_id"] = did
    return decision


def _reason(decision: dict[str, Any], brain: dict[str, Any], chosen: dict[str, Any] | None, mod: dict[str, Any]) -> str:
    if decision["action"] == "no_action":
        return "No message: " + next(c["detail"] for c in decision["policy_checks"] if c["check"] == "uplift guard")
    if decision["action"] == "hold":
        failing = [c["detail"] for c in decision["policy_checks"] if not c["passed"]]
        return "Hold: " + ("; ".join(failing) if failing else "no evidenced channel")
    if decision["action"] == "human_review":
        return "Human review: " + mod.get("summary", "not enough evidence to act alone")
    mods = "; ".join(m["why"] for m in chosen["modifiers"]) if chosen else ""
    sim = f" Twin reaction: \"{chosen['simulated']['reaction']}\"." if chosen and chosen.get("simulated") else ""
    dl = decision.get("delivery") or {}
    via = f" via {dl['provider']['name']}" if dl.get("provider") else ""
    lang = dl.get("language", {}).get("template_language") or decision["language"]
    return (f"{chosen['channel'].title()}{via} in the {chosen['window']}, {chosen['tone'].replace('_', ' ')} tone, in {lang}. "
            f"{chosen['empirical']['detail']}.{(' ' + mods + '.') if mods else ''}{sim} {mod.get('summary', '')}")


def _receipts(brain: dict[str, Any], decision: dict[str, Any], chosen: dict[str, Any] | None) -> list[dict[str, Any]]:
    facts = {f["id"]: f for f in brain["facts"]}
    cited_beliefs = [b for b in brain["beliefs"] if b["status"] != "insufficient_evidence"]
    fact_ids = sorted({c for b in cited_beliefs for c in b["cites"] if c in facts})
    return [
        {"stage": "world", "items": [brain["world"]["summary"]]},
        {"stage": "memory", "items": [f"{m['kind']} (written {m['written_on']}) from {m['ref']['source']}:{m['ref']['row_id']}" for m in brain["memory"]]},
        {"stage": "facts", "items": [f"{fid} = {facts[fid]['value']!r}: {facts[fid]['formula']}" for fid in fact_ids]},
        {"stage": "beliefs", "items": [f"{b['id']} = {b['value']} (confidence {b['confidence']}, cites {', '.join(b['cites'][:4])})" for b in cited_beliefs]},
        {"stage": "twin", "items": [f"{c['channel']} · {c['window']} · {c['tone']}: score {c['score']}" for c in decision["twin"]["candidates"][:3]]},
        {"stage": "council", "items": [decision["council"]["moderator"].get("summary", "")]},
        {"stage": "decision", "items": [decision["reason"]]},
    ]


def simulate_outcomes(seed: int = 7) -> dict[str, Any]:
    """DEMO ONLY: draw outcomes for the latest decisions so the uplift view has something to show.

    Treatment converts at the chosen candidate's evidence-weighted rate; holdout at a self-cure rate derived from
    each customer's own on-time history. Results are flagged simulated everywhere they appear.
    """
    rng = random.Random(seed)
    latest = store.latest_decisions()
    with store.db() as conn:
        conn.execute("DELETE FROM outcomes WHERE simulated=1")
    n = 0
    for cid, d in latest.items():
        brain = store.get_brain(cid)
        if not brain:
            continue
        fv = {f["id"]: f["value"] for f in brain["facts"]}
        if brain["pack"] == "emi_collection":
            self_cure = 0.08 + 0.5 * float(fv.get("on_time_rate") or 0)
        else:
            intent = next((b["score"] or 0 for b in brain["beliefs"] if b["id"] == "renewal_intent"), 0)
            self_cure = 0.9 if fv.get("auto_renew") else 0.1 + 0.3 * intent
        if d["arm"] == "holdout" or d["action"] != "contact":
            p = self_cure
        else:
            top = d["twin"]["candidates"][0] if d["twin"]["candidates"] else {"score": 0}
            p = self_cure + (1 - self_cure) * min(0.8, 1.2 * top["score"])
        store.record_outcome(cid, d["decision_id"], d["arm"], rng.random() < p, datetime.now().isoformat(timespec="seconds"), True)
        n += 1
    return {"simulated_outcomes": n}


def uplift() -> dict[str, Any]:
    s = store.outcome_summary()
    t, h = s.get("treatment", {"n": 0, "converted": 0}), s.get("holdout", {"n": 0, "converted": 0})
    tr = t["converted"] / t["n"] if t["n"] else None
    hr = h["converted"] / h["n"] if h["n"] else None
    return {"treatment": {**t, "rate": tr}, "holdout": {**h, "rate": hr},
            "uplift_pts": round((tr - hr) * 100, 1) if tr is not None and hr is not None else None,
            "simulated": any(x.get("simulated") for x in s.values()),
            "note": "Uplift = treatment conversion minus holdout conversion. Holdout is a fixed 10% that is never messaged."}


def ask(customer_id: str, question: str) -> dict[str, Any]:
    """Plain-language question over one brain. Answers cite fact and belief ids."""
    from . import llm

    brain = store.get_brain(customer_id)
    if not brain:
        raise KeyError(customer_id)
    if llm.enabled():
        digest = privacy.pseudonymise({"facts": [{k: f[k] for k in ("id", "question", "value", "formula")} for f in brain["facts"]],
                                       "beliefs": [{k: b[k] for k in ("id", "value", "status", "reasoning")} for b in brain["beliefs"]],
                                       "memory": brain["memory"], "persona": brain["persona"],
                                       "latest_decision": (store.latest_decision(customer_id) or {}).get("reason")},
                                      [brain.get("display_name", "")])
        out = llm.ask_json("Answer questions about one customer using only the brain given. Cite fact and belief ids. "
                           "If the brain does not contain the answer, say so plainly.",
                           f"Brain: {digest}\n\nQuestion: {question}",
                           {"type": "object", "properties": {"answer": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}}},
                           max_tokens=1200)
        if out:
            return {**out, "method": "llm"}
    q = set(question.lower().replace("?", "").split())
    scored = sorted(brain["facts"], key=lambda f: -len(q & set((f["question"] + " " + f["id"].replace("_", " ")).lower().split())))
    hits = [f for f in scored[:3] if q & set((f["question"] + " " + f["id"].replace("_", " ")).lower().split())]
    if not hits:
        return {"answer": "I could not match that question to a fact in this brain. Turn on Claude for open questions.", "cites": [], "method": "rules"}
    return {"answer": " ".join(f"{f['question']} {f['value']!r} ({f['formula']})." for f in hits), "cites": [f["id"] for f in hits], "method": "rules"}
