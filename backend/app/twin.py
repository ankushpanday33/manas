"""Digital twin: rehearse the message on the customer's twin before sending it (idea from MiroFish).

Every candidate action (channel x window x tone) gets an evidence-weighted score from a metric ladder,
most outcome-proximate rung first: conversion within 3 days, then reply, read, delivery. A rung is used only
with enough sends; otherwise the population prior carries it and the candidate is marked cold-start.
When Claude is on, the top candidates are also role-played by an agent built from the customer's persona,
and its simulated reaction is blended in at a fixed, visible weight.
"""
from __future__ import annotations

from typing import Any

from . import llm, privacy

LADDER = [("converted_3d", 1.0), ("replied", 0.5), ("read", 0.3), ("delivered", 0.1)]
MIN_SENDS = 3
PRIOR_STRENGTH = 4.0
SIM_WEIGHT = 0.3
# A slot this customer has never seen must beat their own evidence by 2x to be chosen.
POP_DISCOUNT = 0.5


def population_stats(brains: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    pop: dict[str, dict[str, dict[str, int]]] = {}
    for b in brains:
        for ch, ws in b.get("comm_stats", {}).items():
            for w, c in ws.items():
                cell = pop.setdefault(ch, {}).setdefault(w, {"sends": 0, "delivered": 0, "read": 0, "replied": 0, "converted_3d": 0})
                for k in cell:
                    cell[k] += c.get(k, 0)
    return pop


def _cell_score(cust: dict[str, int] | None, pop: dict[str, int] | None) -> dict[str, Any]:
    cust = cust or {}
    pop = pop or {}
    for rung, weight in LADDER:
        n, k = cust.get("sends", 0), cust.get(rung, 0)
        pn, pk = pop.get("sends", 0), pop.get(rung, 0)
        if n >= MIN_SENDS and (k > 0 or rung == LADDER[-1][0]):
            prior = pk / pn if pn else 0.2
            post = (prior * PRIOR_STRENGTH + k) / (PRIOR_STRENGTH + n)
            return {"score": post * weight, "rate": round(post, 3), "rung": rung, "weight": weight, "evidence_n": n,
                    "source": "customer", "detail": f"{k}/{n} sends led to {rung.replace('_', ' ')} (shrunk toward population {prior:.0%})"}
    for rung, weight in LADDER:
        pn, pk = pop.get("sends", 0), pop.get(rung, 0)
        if pn >= 20 and pk > 0:
            rate = pk / pn
            return {"score": rate * weight * POP_DISCOUNT, "rate": round(rate, 3), "rung": rung, "weight": weight, "evidence_n": cust.get("sends", 0),
                    "source": "population",
                    "detail": f"exploration: never tried on this customer; population {pk}/{pn} sends led to {rung.replace('_', ' ')} (discounted {int((1 - POP_DISCOUNT) * 100)}%)"}
    return {"score": 0.0, "rate": None, "rung": None, "weight": 0, "evidence_n": 0, "source": "none", "detail": "no evidence anywhere"}


def _tone_mods(pack_id: str, fv: dict[str, Any], beliefs: dict[str, dict], tone: str) -> list[tuple[str, float]]:
    mods = []
    if pack_id == "emi_collection":
        wtp = beliefs.get("willingness_to_pay", {}).get("value")
        dpd = fv.get("days_past_due") or 0
        if tone == "empathetic_plan" and (fv.get("salary_dependent") or fv.get("hardship_flag")):
            mods.append(("payment tied to salary or hardship: offer a plan", 0.08))
        if tone == "gentle" and wtp == "high":
            mods.append(("reliable payer: a gentle nudge is enough", 0.05))
        if tone == "firm" and wtp == "low" and dpd > 30:
            mods.append(("low willingness and 30+ DPD: be clear", 0.04))
        if tone == "firm" and (fv.get("hardship_flag") or wtp == "high"):
            mods.append(("firm tone backfires on this person", -0.08))
    else:
        if tone == "offer" and beliefs.get("price_sensitivity", {}).get("value") == "high":
            mods.append(("price sensitive: an offer moves them", 0.08))
        if tone == "value_recap" and beliefs.get("engagement", {}).get("value") in {"high", "medium"}:
            mods.append(("engaged user: remind them what they love", 0.06))
        if tone == "reminder" and beliefs.get("renewal_intent", {}).get("value") == "high":
            mods.append(("intends to renew: a reminder is enough, no discount needed", 0.05))
        if tone == "offer" and beliefs.get("renewal_intent", {}).get("value") == "high":
            mods.append(("would renew anyway: avoid giving away margin", -0.06))
    # In-app events
    if fv.get("abandoned_checkout"):
        gentle = "gentle" if pack_id == "emi_collection" else "reminder"
        if tone == gentle:
            mods.append((f"left {str(fv['abandoned_checkout']).replace('_', ' ')} halfway in the app: a gentle link to finish", 0.08))
    if pack_id == "subscription_renewal" and tone == "value_recap" and (fv.get("churn_risk_14d") or 0) > 0.6:
        mods.append((f"churn risk {fv['churn_risk_14d']:.0%}: remind them what they love", 0.05))
    if pack_id == "emi_collection" and tone == "empathetic_plan" and fv.get("top_cta") == "view_plan":
        mods.append(("keeps opening the repayment-plan screen", 0.06))
    return mods


def _slot_mods(fv: dict[str, Any], channel: str, window: str) -> list[tuple[str, float]]:
    mods = []
    pref = str(fv.get("stated_time_preference") or "")
    if pref and (window in pref or (pref.startswith("after") and window == "evening") or (pref == "morning" and window == "morning")):
        mods.append((f"they asked to be contacted {pref}", 0.06))
    if channel == "voice" and fv.get("contact_objection_flag"):
        mods.append(("asked us to stop calling", -0.15))
    return mods


_SIM_SCHEMA = {
    "type": "object",
    "properties": {
        "reactions": {"type": "array", "items": {"type": "object", "properties": {
            "candidate_index": {"type": "integer"},
            "probability_of_acting": {"type": "number", "description": "0 to 1: chance this person pays or renews within 3 days after this message"},
            "inner_reaction": {"type": "string", "description": "One line, in the person's own voice and language"},
        }}}
    },
}


def simulate(brain: dict[str, Any], pack: dict[str, Any], pop: dict[str, Any], render_message, allowed: set[str] | None = None) -> dict[str, Any]:
    fv = {f["id"]: f["value"] for f in brain["facts"]}
    beliefs = {b["id"]: b for b in brain["beliefs"]}
    cust_stats = brain.get("comm_stats", {})
    candidates = []
    for ch in pack["channels"]:
        if allowed is not None and ch not in allowed:
            continue
        for w in pack["windows"]:
            base = _cell_score(cust_stats.get(ch, {}).get(w), pop.get(ch, {}).get(w))
            for tone in pack["tones"]:
                mods = _slot_mods(fv, ch, w) + _tone_mods(brain["pack"], fv, beliefs, tone)
                score = max(0.0, base["score"] + sum(m for _, m in mods))
                candidates.append({"channel": ch, "window": w, "tone": tone, "score": round(score, 4),
                                   "empirical": base, "modifiers": [{"why": t, "delta": d} for t, d in mods], "simulated": None})
    candidates.sort(key=lambda c: c["score"], reverse=True)
    top = candidates[:4]

    sim_used = False
    if llm.enabled() and top:
        persona = brain["persona"]
        listing = "\n".join(f"[{i}] {c['channel']} in the {c['window']}, message: \"{render_message(c['tone'], scrub=True)}\""
                            for i, c in enumerate(top))
        out = llm.ask_json(
            "You are role-playing one real customer as a simulation agent. Stay strictly inside the persona and facts. "
            "For each candidate message, estimate how likely this person is to act (pay or renew) within 3 days, and give "
            "their one-line inner reaction in their own language.",
            f"Persona: {privacy.pseudonymise(persona, [brain.get('display_name', '')])}\n"
            f"Beliefs: { {k: v['value'] for k, v in beliefs.items()} }\n\nCandidates:\n{listing}",
            _SIM_SCHEMA, max_tokens=1500)
        if out:
            for r in out.get("reactions", []):
                i = r.get("candidate_index")
                if isinstance(i, int) and 0 <= i < len(top):
                    p = max(0.0, min(1.0, float(r.get("probability_of_acting", 0))))
                    top[i]["simulated"] = {"probability": round(p, 2), "reaction": r.get("inner_reaction", "")}
                    top[i]["score"] = round((1 - SIM_WEIGHT) * top[i]["score"] + SIM_WEIGHT * p, 4)
                    sim_used = True
            top.sort(key=lambda c: c["score"], reverse=True)

    total_sends = sum(c.get("sends", 0) for ws in cust_stats.values() for c in ws.values())
    status = "ok" if top and top[0]["empirical"]["source"] == "customer" else \
        "cold_start" if top and top[0]["empirical"]["source"] == "population" else "insufficient_evidence"
    return {
        "status": status,
        "customer_sends": total_sends,
        "ladder": [{"rung": r, "weight": w} for r, w in LADDER],
        "candidates": top + candidates[4:12],
        "simulation_used": sim_used,
        "sim_weight": SIM_WEIGHT if sim_used else 0,
        "note": {"ok": "Chosen on this customer's own outcomes.",
                 "cold_start": "Not enough of this customer's history: the population prior decides, discounted 50%.",
                 "insufficient_evidence": "No evidence for any channel yet: hold or ask a human."}[status],
    }
