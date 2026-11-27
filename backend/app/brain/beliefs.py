"""Beliefs: judgements formed from facts, each citing the facts it rests on.

Confidence here means sample adequacy (how much evidence there is), never a claim the data cannot back.
With too little evidence a belief returns insufficient_evidence instead of guessing.
When Claude is enabled, an independent judge re-reads every belief against its cited facts;
a disagreement sends the belief to human review instead of acting on it.
"""
from __future__ import annotations

from typing import Any

from .. import llm


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _level(score: float) -> str:
    return "high" if score >= 0.66 else "medium" if score >= 0.4 else "low"


def _belief(bid: str, score: float | None, n: int, need: int, cites: list[str], reasoning: str) -> dict[str, Any]:
    if score is None or n < need:
        return {"id": bid, "value": None, "score": None, "confidence": round(min(1.0, n / max(need * 3, 1)), 2),
                "status": "insufficient_evidence", "cites": cites, "evidence_n": n,
                "reasoning": f"Only {n} observations; at least {need} needed before forming this belief.", "judge": None}
    return {"id": bid, "value": _level(score), "score": round(_clamp(score), 2),
            "confidence": round(min(1.0, n / (need * 3)), 2), "status": "formed", "cites": cites,
            "evidence_n": n, "reasoning": reasoning, "judge": None}


def _num(facts: dict[str, Any], key: str, default: float | None = None) -> float | None:
    v = facts.get(key)
    return default if v is None or isinstance(v, (str, bool)) else float(v)


def _reach(fv: dict[str, Any], channels: list[str], stats: dict[str, Any]) -> dict[str, Any]:
    rates = [r for ch in channels for r in [_num(fv, f"{ch}_read_rate"), _num(fv, f"{ch}_answer_rate")] if r is not None]
    sends = sum(c["sends"] for ws in stats.values() for c in ws.values())
    last_reply = _num(fv, "days_since_last_reply")
    recency = 1.0 if last_reply is not None and last_reply <= 30 else 0.5 if last_reply is not None and last_reply <= 90 else 0.0
    score = 0.7 * max(rates, default=0.0) + 0.3 * recency if rates else None
    best = fv.get("best_responding_slot")
    return _belief("reachability", score, sends, 4,
                   [f"{ch}_read_rate" for ch in channels if ch != "voice"] + ["voice_answer_rate", "days_since_last_reply", "best_responding_slot"],
                   f"Best read/answer rate {max(rates, default=0):.0%}; last reply {int(last_reply) if last_reply is not None else 'never'} days ago; responds best on {best or 'no clear slot'}.")


def emi_beliefs(fv: dict[str, Any], stats: dict[str, Any], pack: dict[str, Any]) -> list[dict[str, Any]]:
    keep = _num(fv, "promise_keep_rate")
    on_time = _num(fv, "on_time_rate")
    closed = int(str(fv.get("promises_kept") or "0 of 0").split(" of ")[-1])
    n_pay = int(_num(fv, "payments_12m", 0) or 0)
    replied_recently = (_num(fv, "days_since_last_reply") or 999) <= 30
    objection = bool(fv.get("contact_objection_flag"))
    dispute = bool(fv.get("dispute_flag"))
    hardship = bool(fv.get("hardship_flag"))
    salary = bool(fv.get("salary_dependent"))
    dpd = _num(fv, "days_past_due", 0) or 0

    parts = [(0.45, keep), (0.35, on_time), (0.2, 1.0 if replied_recently else 0.0)]
    used = [(w, v) for w, v in parts if v is not None]
    wtp = sum(w * v for w, v in used) / sum(w for w, _ in used) if used else None
    if wtp is not None:
        wtp -= 0.25 if objection else 0
        wtp -= 0.2 if dispute else 0
    beliefs = [_belief("willingness_to_pay", wtp, closed + n_pay, 3,
                       ["promise_keep_rate", "on_time_rate", "days_since_last_reply", "contact_objection_flag", "dispute_flag"],
                       f"Kept {fv.get('promises_kept')} promises, paid on time {on_time or 0:.0%} of the time"
                       f"{', replied in the last 30 days' if replied_recently else ''}{', asked us to stop contacting' if objection else ''}"
                       f"{', has an open dispute' if dispute else ''}.")]

    atp = 0.85 - min(dpd / 150, 0.45) - (0.35 if hardship else 0) + (0.1 if salary and not hardship else 0)
    beliefs.append(_belief("ability_to_pay", atp, n_pay + (1 if hardship or salary else 0), 2,
                           ["days_past_due", "hardship_flag", "salary_dependent", "payments_12m"],
                           f"{int(dpd)} days past due{'; mentioned hardship' if hardship else ''}"
                           f"{'; payment tied to salary credit, so the delay looks temporary' if salary and not hardship else ''}."))

    beliefs.append(_reach(fv, pack["channels"], stats))

    broken = closed - round((keep or 0) * closed)
    esc = min(dpd / 90, 0.5) + (0.3 if dispute else 0) + (0.2 if objection else 0) + min(broken * 0.1, 0.3) \
        + (0.15 if (_num(fv, "contacts_last_7d", 0) or 0) >= 3 else 0)
    beliefs.append(_belief("escalation_risk", esc, n_pay + closed + 1, 2,
                           ["days_past_due", "dispute_flag", "contact_objection_flag", "promise_keep_rate", "contacts_last_7d"],
                           f"{int(dpd)} DPD, {broken} broken promises{', dispute raised' if dispute else ''}"
                           f"{', contact objection on record' if objection else ''}, {int(_num(fv, 'contacts_last_7d', 0) or 0)} contacts this week."))
    return beliefs


def subscription_beliefs(fv: dict[str, Any], stats: dict[str, Any], pack: dict[str, Any]) -> list[dict[str, Any]]:
    trend = _num(fv, "usage_trend")
    active = _num(fv, "active_days_30d", 0) or 0
    renewals = _num(fv, "renewals_so_far", 0) or 0
    idle = _num(fv, "days_since_last_use")
    auto = bool(fv.get("auto_renew"))
    price = _num(fv, "price", 0) or 0
    n_use = int(active)

    intent = 0.35 + (0.25 if auto else 0) + min(renewals * 0.08, 0.24) + (max(min(trend, 0.5), -0.5) * 0.3 if trend is not None else 0) \
        - (0.25 if idle is not None and idle > 14 else 0)
    beliefs = [_belief("renewal_intent", intent, n_use + int(renewals), 3,
                       ["auto_renew", "renewals_so_far", "usage_trend", "days_since_last_use"],
                       f"Auto-renew {'on' if auto else 'off'}, renewed {int(renewals)} times, usage trend "
                       f"{'n/a' if trend is None else f'{trend:+.0%}'}, idle {int(idle) if idle is not None else '?'} days.")]
    beliefs.append(_belief("engagement", active / 30 * 1.4, n_use, 1, ["active_days_30d", "minutes_30d", "top_content"],
                           f"Active {int(active)} of the last 30 days, mostly {fv.get('top_content') or 'nothing'}."))
    sens = 0.3 + (0.3 if price >= 299 else 0.1) + (0.25 if active < 6 else 0) - (0.2 if renewals >= 3 else 0)
    beliefs.append(_belief("price_sensitivity", sens, n_use + int(renewals), 2, ["price", "active_days_30d", "renewals_so_far"],
                           f"Pays ₹{int(price)} for {int(active)} active days a month; {int(renewals)} past renewals."))
    beliefs.append(_reach(fv, pack["channels"], stats))
    return beliefs


def event_belief(fv: dict[str, Any]) -> dict[str, Any]:
    pp = fv.get("purchase_propensity_7d")
    return _belief("conversion_propensity", pp, int(_num(fv, "events_30d", 0) or 0), 6,
                   ["purchase_propensity_7d", "cta_clicks_7d", "abandoned_checkout", "churn_risk_14d"],
                   (f"Event model gives {pp:.0%} chance of paying or buying in 7 days"
                    f"{'; left ' + str(fv['abandoned_checkout']).replace('_', ' ') + ' halfway' if fv.get('abandoned_checkout') else ''}.")
                   if pp is not None else "")


BELIEF_BUILDERS = {"emi_collection": lambda fv, st, pk: emi_beliefs(fv, st, pk) + [event_belief(fv)],
                   "subscription_renewal": lambda fv, st, pk: subscription_beliefs(fv, st, pk) + [event_belief(fv)]}

_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {"type": "array", "items": {"type": "object", "properties": {
            "belief_id": {"type": "string"},
            "agrees": {"type": "boolean"},
            "note": {"type": "string", "description": "One sentence: why the cited facts do or do not support the belief."},
        }}}
    },
}


def judge(beliefs: list[dict[str, Any]], facts_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Independent judge: a second pass that checks each formed belief only against the facts it cites."""
    formed = [b for b in beliefs if b["status"] == "formed"]
    if not formed or not llm.enabled():
        return beliefs
    lines = []
    for b in formed:
        cited = "; ".join(f"{c}={facts_by_id[c]['value']!r}" for c in b["cites"] if c in facts_by_id)
        lines.append(f"- {b['id']} = {b['value']} (score {b['score']}). Cited facts: {cited}")
    result = llm.ask_json(
        "You are an independent auditor. For each belief, decide only from its cited facts whether the belief is "
        "supported. Do not use outside assumptions. Disagree when the facts point the other way or are too thin.",
        "\n".join(lines), _JUDGE_SCHEMA, max_tokens=1500)
    if not result:
        return beliefs
    verdicts = {v["belief_id"]: v for v in result.get("verdicts", [])}
    for b in formed:
        v = verdicts.get(b["id"])
        if v:
            b["judge"] = {"agrees": v["agrees"], "note": v["note"]}
            if not v["agrees"]:
                b["status"] = "needs_review"
    return beliefs
