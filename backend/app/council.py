"""Decision council: three agents with different goals argue, a moderator decides (idea from BettaFish's ForumEngine).

  Outcome Analyst    - wants the number to move: picks the best evidence-weighted candidate
  Customer Advocate  - protects the person and compliance: least intrusive option that still works, vetoes on dispute or hardship
  Cost Strategist    - wants the most outcome per rupee of channel spend

Disagreement is kept, not hidden: the moderator's summary names who dissented and why.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import llm, privacy

CHANNEL_COST_INR = {"whatsapp": 0.12, "sms": 0.15, "rcs": 0.20, "push": 0.01, "voice": 2.50, "email": 0.02}
INTRUSION = {"push": 0, "email": 0, "whatsapp": 1, "rcs": 1, "sms": 1, "voice": 3}

AGENTS = {
    "outcome_analyst": ("Outcome Analyst", "You want the goal metric to move. Back the candidate with the strongest evidence of working for this person."),
    "customer_advocate": ("Customer Advocate", "You protect the customer and the company's conduct record. Prefer the least intrusive option that still "
                                               "works. Insist on a human when there is a dispute, hardship, or a request to stop contact."),
    "cost_strategist": ("Cost Strategist", "You want the most outcome per rupee of channel spend. Prefer cheaper channels unless the evidence "
                                           "for a costlier one is clearly stronger."),
}


def _label(c: dict[str, Any]) -> str:
    return f"{c['channel']} · {c['window']} · {c['tone']}"


def _rules(brain: dict[str, Any], cands: list[dict[str, Any]]) -> dict[str, Any]:
    fv = {f["id"]: f["value"] for f in brain["facts"]}
    top_score = cands[0]["score"] if cands else 0
    # Cheaper or gentler options only count if they are nearly as good AND backed by this customer's own evidence.
    viable = [i for i, c in enumerate(cands)
              if c["score"] >= 0.9 * top_score and (c["empirical"]["source"] == "customer" or i == 0)] or [0]

    analyst = {"speaker": "outcome_analyst", "choice": 0,
               "argument": f"{_label(cands[0])} has the strongest evidence: {cands[0]['empirical']['detail']}.",
               "cites": ["comm_stats", "best_responding_slot"]}

    advocate_choice = min(viable, key=lambda i: (INTRUSION.get(cands[i]["channel"], 2), -cands[i]["score"]))
    veto = None
    if fv.get("dispute_flag"):
        veto = "dispute on record: a person must resolve it before any reminder"
    elif fv.get("hardship_flag") and brain["pack"] == "emi_collection":
        veto = "hardship mentioned: route to a person to offer a restructuring plan"
    advocate = {"speaker": "customer_advocate", "choice": advocate_choice, "veto": veto,
                "argument": veto or f"{_label(cands[advocate_choice])} is the least intrusive option within 15% of the best score.",
                "cites": ["dispute_flag", "hardship_flag", "contact_objection_flag"]}

    strategist_choice = max(viable, key=lambda i: cands[i]["score"] / CHANNEL_COST_INR.get(cands[i]["channel"], 1.0))
    c = cands[strategist_choice]
    strategist = {"speaker": "cost_strategist", "choice": strategist_choice,
                  "argument": f"{_label(c)} gives the best outcome per rupee (₹{CHANNEL_COST_INR.get(c['channel'], 1):.2f} per send).",
                  "cites": ["channel_costs"]}
    return {"analyst": analyst, "advocate": advocate, "strategist": strategist}


def _moderate(stances: list[dict[str, Any]], cands: list[dict[str, Any]]) -> dict[str, Any]:
    veto = next((s.get("veto") for s in stances if s.get("veto")), None)
    if veto:
        return {"choice": None, "action": "human_review", "summary": f"Customer Advocate vetoed: {veto}.",
                "dissent": [s["speaker"] for s in stances if not s.get("veto")]}
    votes: dict[int, list[str]] = {}
    for s in stances:
        votes.setdefault(s["choice"], []).append(s["speaker"])
    best = max(votes, key=lambda i: (len(votes[i]), cands[i]["score"]))
    dissent = [s["speaker"] for s in stances if s["choice"] != best]
    return {"choice": best, "action": "contact",
            "summary": f"{len(votes[best])} of 3 agents back {_label(cands[best])}" + (f"; dissent from {', '.join(dissent)}." if dissent else "; unanimous."),
            "dissent": dissent}


_STANCE_SCHEMA = {"type": "object", "properties": {
    "choice": {"type": "integer", "description": "index of the candidate you back"},
    "veto": {"type": ["string", "null"], "description": "only if no candidate should be sent: the reason a human must take over"},
    "argument": {"type": "string", "description": "two sentences at most, citing fact ids"},
    "cites": {"type": "array", "items": {"type": "string"}},
}}
_MOD_SCHEMA = {"type": "object", "properties": {
    "choice": {"type": ["integer", "null"]},
    "action": {"type": "string", "enum": ["contact", "human_review", "hold"]},
    "summary": {"type": "string"},
    "dissent": {"type": "array", "items": {"type": "string"}},
}}


def deliberate(brain: dict[str, Any], twin: dict[str, Any], use_llm: bool = True) -> dict[str, Any]:
    cands = twin["candidates"][:5]
    if not cands:
        return {"method": "rules", "stances": [], "moderator": {"choice": None, "action": "hold", "summary": "No channel is allowed or evidenced.", "dissent": []}}

    rules = _rules(brain, cands)
    if not (use_llm and llm.enabled()):
        stances = [rules["analyst"], rules["advocate"], rules["strategist"]]
        return {"method": "rules", "stances": stances, "moderator": _moderate(stances, cands)}

    names = [brain.get("display_name", "")]
    digest = privacy.pseudonymise({
        "facts": {f["id"]: f["value"] for f in brain["facts"] if f["value"] is not None},
        "beliefs": {b["id"]: {"value": b["value"], "status": b["status"]} for b in brain["beliefs"]},
        "memory": [{"kind": m["kind"], "detail": m.get("detail"), "written_on": m["written_on"]} for m in brain["memory"]],
        "candidates": [{"index": i, "action": _label(c), "score": c["score"], "evidence": c["empirical"]["detail"],
                        "channel_cost_inr": CHANNEL_COST_INR.get(c["channel"]), "simulated": c["simulated"]} for i, c in enumerate(cands)],
    }, names)

    def ask(key: str) -> dict[str, Any]:
        name, role = AGENTS[key]
        out = llm.ask_json(f"You are the {name} on a decision council for customer {brain['alias']}. {role} "
                           "Argue only from the facts given; cite fact ids.", str(digest), _STANCE_SCHEMA, max_tokens=800)
        fallback = {"outcome_analyst": rules["analyst"], "customer_advocate": rules["advocate"], "cost_strategist": rules["strategist"]}[key]
        if not out or not isinstance(out.get("choice"), int) or not 0 <= out["choice"] < len(cands):
            return fallback
        return {"speaker": key, **out}

    with ThreadPoolExecutor(max_workers=3) as pool:
        stances = list(pool.map(ask, AGENTS))

    transcript = "\n".join(f"{AGENTS[s['speaker']][0]}: backs [{s['choice']}] {_label(cands[s['choice']])}. "
                           f"{('VETO: ' + s['veto'] + '. ') if s.get('veto') else ''}{s['argument']}" for s in stances)
    mod = llm.ask_json("You moderate a decision council. Weigh the three arguments. A well-founded veto from the Customer Advocate "
                       "wins. Name dissent honestly. Choose a candidate index, or human_review / hold.",
                       f"Candidates: {[_label(c) for c in cands]}\n\n{transcript}", _MOD_SCHEMA, max_tokens=600)
    if not mod or (mod.get("action") == "contact" and not (isinstance(mod.get("choice"), int) and 0 <= mod["choice"] < len(cands))):
        mod = _moderate(stances, cands)
    return {"method": "llm", "stances": stances, "moderator": mod}
