"""Brain builder: one living brain per customer.

A brain has five layers, each traceable to the one below:
  world    - the customer's graph: objects and links joined from your own tables
  memory   - episodic signals read from free text, dated by when they were written
  facts    - answers computed in code, each citing rows
  beliefs  - judgements citing facts, checked by an independent judge
  persona  - a portrait of the person used by the digital twin (MiroFish-style agent profile)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .. import llm, privacy, store
from ..packs import get_pack
from . import beliefs as beliefs_mod
from . import memory as memory_mod
from .facts import FACT_BUILDERS, _d


def _world(records: dict[str, list[dict]], pack: dict[str, Any], customer_id: str) -> dict[str, Any]:
    nodes, edges, counts = [], [], {}
    src_to_type = {spec["source"]: name for name, spec in pack["objects"].items()}
    src_to_type.setdefault("events", "Event")
    cust_node = f"Customer:{customer_id}"
    nodes.append({"id": cust_node, "type": "Customer", "label": privacy.alias(customer_id)})
    for src, rows in records.items():
        otype = src_to_type.get(src)
        if not otype or otype == "Customer":
            continue
        counts[otype] = len(rows)
        for r in rows:
            nid = f"{otype}:{r['_row_id']}"
            nodes.append({"id": nid, "type": otype, "label": r["_row_id"]})
            link = next((l for l in pack["links"] if l["from"] == otype), None)
            target = cust_node
            if link and link["to"] != "Customer":
                parent_key = link["on"].split(".")[-1]
                if r.get(parent_key):
                    target = f"{link['to']}:{r[parent_key]}"
            edges.append({"from": nid, "to": target, "type": link["type"] if link else "related_to"})
    return {"nodes": nodes, "edges": edges, "counts": counts,
            "summary": f"{len(counts) + 1} object types, {len(edges)} links"}


def _texts(records: dict[str, list[dict]]) -> list[dict[str, Any]]:
    texts = []
    for l in records.get("loans", []):
        if l.get("collections_note"):
            texts.append({"text": l["collections_note"], "written_on": _d(l.get("note_date")) or date.today(),
                          "ref": {"source": "loans", "row_id": l["_row_id"]}})
    for c in records.get("communications", []):
        if c.get("direction") == "in" and c.get("reply_text"):
            texts.append({"text": c["reply_text"], "written_on": _d(c.get("sent_at")) or date.today(),
                          "ref": {"source": "communications", "row_id": c["_row_id"]}})
    return texts


def _persona(customer: dict[str, Any], fv: dict[str, Any], beliefs: list[dict[str, Any]], memory: list[dict[str, Any]],
             pack_id: str) -> dict[str, Any]:
    """A twin-ready portrait. Rules give the skeleton; Claude, when on, writes the narrative from pseudonymised inputs."""
    b = {x["id"]: x for x in beliefs}
    slot = fv.get("best_responding_slot")
    pref_time = fv.get("stated_time_preference")
    traits = []
    if fv.get("salary_dependent"):
        traits.append("plans payments around salary credit")
    if (fv.get("promise_keep_rate") or 0) >= 0.66:
        traits.append("keeps their word once they commit")
    if fv.get("contact_objection_flag"):
        traits.append("dislikes repeated contact")
    if fv.get("dispute_flag"):
        traits.append("feels wronged about a charge")
    if fv.get("hardship_flag"):
        traits.append("going through a financial hardship")
    if pack_id == "subscription_renewal":
        if (fv.get("usage_trend") or 0) > 0.1:
            traits.append("watching more than last month")
        elif (fv.get("usage_trend") or 0) < -0.2:
            traits.append("drifting away from the app")
        if fv.get("top_content"):
            traits.append(f"loves {fv['top_content']}")
    persona = {
        "alias": privacy.alias(customer["customer_id"]),
        "language": customer.get("preferred_language") or "English",
        "city": customer.get("city"),
        "responds_on": slot,
        "stated_time": pref_time,
        "traits": traits,
        "mood": "guarded" if fv.get("dispute_flag") or fv.get("contact_objection_flag") else
                "stressed" if fv.get("hardship_flag") else "cooperative" if (b.get("willingness_to_pay", b.get("renewal_intent", {})).get("value") == "high") else "neutral",
        "narrative": None,
        "method": "rules",
    }
    persona["narrative"] = (
        f"Speaks {persona['language']}{', lives in ' + persona['city'] if persona['city'] else ''}. "
        f"{'Responds best on ' + slot + '. ' if slot else 'No reliable response slot yet. '}"
        f"{'Asked to be contacted ' + pref_time + '. ' if pref_time else ''}"
        f"{'Tends to: ' + ', '.join(traits) + '.' if traits else ''}"
    ).strip()

    if llm.enabled():
        digest = {"facts": {k: v for k, v in fv.items() if v is not None},
                  "beliefs": {x["id"]: x["value"] for x in beliefs},
                  "memory": [{"kind": m["kind"], "detail": m.get("detail"), "written_on": m["written_on"]} for m in memory]}
        out = llm.ask_json(
            "Write a short, respectful persona of a customer for a simulation agent, grounded only in the facts given. "
            "No invented biography. Second person is not allowed; describe them in third person.",
            f"Customer {persona['alias']}, language {persona['language']}.\n{privacy.pseudonymise(digest, [customer.get('name', '')])}",
            {"type": "object", "properties": {"narrative": {"type": "string"}, "communication_style": {"type": "string"},
                                              "what_motivates_them": {"type": "string"}, "what_to_avoid": {"type": "string"}}},
            max_tokens=800)
        if out:
            persona.update(out)
            persona["method"] = "llm"
    return persona


def build_brain(customer_id: str, pack_id: str, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    pack = get_pack(pack_id)
    records = store.records_for(customer_id)
    customer = (records.get("customers") or [{"customer_id": customer_id}])[0]
    names = [customer.get("name", "")]

    world = _world(records, pack, customer_id)
    memory = memory_mod.read_texts(_texts(records), names)
    facts, stats, predictions = FACT_BUILDERS[pack_id](records, pack, today, memory)
    fv = {f["id"]: f["value"] for f in facts}
    beliefs = beliefs_mod.BELIEF_BUILDERS[pack_id](fv, stats, pack)
    beliefs = beliefs_mod.judge(beliefs, {f["id"]: f for f in facts})
    persona = _persona(customer, fv, beliefs, memory, pack_id)

    brain = {
        "customer_id": customer_id,
        "alias": privacy.alias(customer_id),
        "display_name": customer.get("name") or customer_id,
        "pack": pack_id,
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "profile": {k: customer.get(k) for k in pack["objects"]["Customer"]["fields"]},
        "world": world,
        "memory": memory,
        "facts": facts,
        "comm_stats": {ch: {w: {k: v for k, v in c.items() if k != "rows"} for w, c in ws.items()} for ch, ws in stats.items()},
        "beliefs": beliefs,
        "persona": persona,
        "predictions": predictions,
        "llm": llm.status(),
    }
    store.save_brain(customer_id, pack_id, brain["built_at"], brain)
    return brain
