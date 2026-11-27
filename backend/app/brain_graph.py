"""Brain graph: one user's whole brain as a knowledge graph (entities + typed relationships), in the style of
MiroFish's graph view. Every node is something the brain actually holds; every edge is a real relationship:
a record belonging to the person, a fact citing a record, a belief citing a fact, a chart value ruled by a planet,
a memory signal read from a chat, the decision resting on beliefs.

Generic over packs: records, memory, facts, beliefs and the decision work for any pack; the chart part is added
only when the brain has a chart (Astro Manas).
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from . import store

# Entity types and their legend colours (orange family first, then neutrals and status colours).
TYPES = {
    "Person": "#FF6623", "Decision": "#C2410C", "Belief": "#F59E0B", "Fact": "#FDBA74", "Memory": "#EF4444",
    "Topic": "#DB2777", "Planet": "#7C3AED", "Number": "#A16207", "Panchang": "#0D9488", "Trait": "#65A30D",
    "Recommendation": "#CA8A04", "Record": "#9CA3AF", "Channel": "#475569", "Product": "#0891B2",
    "Astrologer": "#9333EA", "Offer": "#EA580C", "Content": "#16A34A", "Event": "#2563EB", "AppCategory": "#BE123C",
}

SOURCE_LABEL = {"sessions": "Session", "chats": "Chat", "purchases": "Purchase", "communications": "Message",
                "events": "Event", "installed_apps": "App",
                "loans": "Loan", "payments": "Payment", "promises": "Promise", "subscriptions": "Subscription", "usage": "Usage"}
TIME_FIELDS = ("started_at", "at", "sent_at", "paid_at", "made_on", "date", "renews_on")


class G:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []
        self._seen: set[tuple[str, str, str]] = set()

    def node(self, nid: str, ntype: str, label: str, summary: str = "", **props: Any) -> str:
        if nid not in self.nodes:
            self.nodes[nid] = {"id": nid, "type": ntype, "label": str(label), "summary": summary,
                               "props": {k: v for k, v in props.items() if v not in (None, "", [], {})}}
        return nid

    def edge(self, a: str, b: str, label: str) -> None:
        key = (a, b, label)
        if a in self.nodes and b in self.nodes and a != b and key not in self._seen:
            self._seen.add(key)
            self.edges.append({"source": a, "target": b, "label": label})


def _record_label(src: str, r: dict[str, Any]) -> str:
    when = next((str(r[f])[:10] for f in TIME_FIELDS if r.get(f)), "")
    return f"{SOURCE_LABEL.get(src, src.title())} {when}".strip()


def build(customer_id: str) -> dict[str, Any] | None:
    brain = store.get_brain(customer_id)
    if not brain:
        return None
    records = store.records_for(customer_id)
    decision = store.latest_decision(customer_id)
    g = G()
    me = g.node("person", "Person", brain["alias"], brain["persona"].get("narrative", ""),
                language=brain["persona"].get("language"), city=brain["persona"].get("city"), mood=brain["persona"].get("mood"))

    # Records hang off shared hub entities (channel, content, product, astrologer, offer), and the person links to
    # the hubs. That gives the clustered, interlinked look of a real knowledge graph instead of a star.
    row_node: dict[tuple[str, str], str] = {}
    person_rel = {"Channel": "REACHED_ON", "Content": "READS", "Product": "BUYS", "Astrologer": "CONSULTS", "Offer": "WAS_OFFERED",
                  "Loan": "HAS_LOAN", "Event": "DOES", "AppCategory": "HAS_APPS_IN"}
    from datetime import datetime, timedelta

    def ts(r: dict[str, Any]) -> datetime | None:
        v = next((r[f] for f in TIME_FIELDS if r.get(f)), None)
        try:
            return datetime.fromisoformat(str(v)[:19]) if v else None
        except ValueError:
            return None

    for src, rows in records.items():
        if src == "customers":
            continue
        for r in rows:
            nid = g.node(f"rec:{src}:{r['_row_id']}", "Record", _record_label(src, r), f"{SOURCE_LABEL.get(src, src)} row {r['_row_id']}",
                         **{k: v for k, v in r.items() if not k.startswith("_") and k not in {"customer_id", "phone", "name"}})
            row_node[(src, str(r["_row_id"]))] = nid
            hubs = []
            if r.get("channel"):
                hubs.append((g.node(f"ch:{r['channel']}", "Channel", r["channel"].replace("_", "-").title()), "VIA"))
            if r.get("product"):
                hubs.append((g.node(f"prod:{r['product']}", "Product", r["product"].replace("_", " ").title()), "OF"))
            if r.get("offer"):
                hubs.append((g.node(f"offer:{r['offer']}", "Offer", r["offer"].replace("_", " ").title()), "OFFERED"))
            if r.get("astrologer_id"):
                hubs.append((g.node(f"astro:{r['astrologer_id']}", "Astrologer", r["astrologer_id"]), "WITH"))
            if r.get("content_tag"):
                hubs.append((g.node(f"content:{r['content_tag']}", "Content", r["content_tag"].title()), "READ"))
            if r.get("content_type"):
                hubs.append((g.node(f"content:{r['content_type']}", "Content", str(r["content_type"]).title()), "WATCHED"))
            if r.get("plan"):
                hubs.append((g.node(f"prod:{r['plan']}", "Product", r["plan"]), "PLAN"))
            if r.get("method"):
                hubs.append((g.node(f"ch:pay:{r['method']}", "Channel", f"Pays by {r['method']}"), "PAID_BY"))
            if src == "events" and r.get("event_name"):
                hubs.append((g.node(f"evt:{r['event_name']}", "Event", r["event_name"].replace("_", " ")), "IS"))
                if r.get("cta"):
                    hubs.append((g.node(f"cta:{r['cta']}", "Offer", f"CTA {r['cta'].replace('_', ' ')}"), "ON_CTA"))
            if src == "installed_apps" and r.get("category"):
                from .astro import app_catalog
                cat = app_catalog.CATEGORIES.get(r["category"], {})
                hubs.append((g.node(f"appcat:{r['category']}", "AppCategory", cat.get("label", r["category"]),
                                    f"{cat.get('logic', '')} Use: {cat.get('use')}.", use=cat.get("use")), "IN_CATEGORY"))
            if r.get("screen") and src != "events":
                hubs.append((g.node(f"screen:{r['screen']}", "Content", f"{r['screen'].title()} screen"), "ON_SCREEN"))
            if r.get("loan_id") and src != "loans":
                hubs.append((f"rec:loans:{r['loan_id']}", "AGAINST"))
            for hub, rel in hubs:
                g.edge(nid, hub, rel)
                htype = g.nodes.get(hub, {}).get("type")
                g.edge(me, hub, person_rel.get(htype, "LINKED"))
            if not hubs:
                g.edge(me, nid, {"sessions": "OPENED", "chats": "ASKED", "purchases": "BOUGHT", "communications": "RECEIVED"}.get(src, "HAS"))

    # Causal links: a message that was read, followed within 2 days by a session or purchase, is drawn as LED_TO.
    msgs = [(ts(r), row_node[("communications", str(r["_row_id"]))]) for r in records.get("communications", [])
            if r.get("direction") == "out" and str(r.get("status", "")).lower() in {"read", "answered"} and ts(r)]
    outcomes = [(ts(r), row_node[(src, str(r["_row_id"]))]) for src in ("sessions", "purchases", "payments")
                for r in records.get(src, []) if ts(r)]
    for mt, mn in msgs:
        for ot, on in outcomes:
            if mt <= ot <= mt + timedelta(days=2):
                g.edge(mn, on, "LED_TO")

    # Memory: signals read from text, linked to the row they came from and to topics.
    for m in brain["memory"]:
        mid = g.node(f"mem:{m['id']}", "Memory", f"{m['kind'].replace('_', ' ')}{': ' + str(m['detail']) if m.get('detail') else ''}",
                     f"Read by {m['method']} from text written {m['written_on']}", written_on=m["written_on"], resolved_date=m.get("resolved_date"))
        src_node = row_node.get((m["ref"]["source"], str(m["ref"]["row_id"])))
        if src_node:
            g.edge(src_node, mid, "MENTIONS")
        g.edge(mid, me, "ABOUT")
        if m["kind"] == "topic" and m.get("detail"):
            g.edge(mid, g.node(f"topic:{m['detail']}", "Topic", m["detail"].title()), "TOPIC")

    # Chart (Astro Manas only): numbers, planets, Panchang, traits, recommendations.
    chart = brain.get("chart")
    if chart:
        def planet(p: str) -> str:
            return g.node(f"planet:{p}", "Planet", p.title())

        for key, label in (("radical", "Radical"), ("destiny", "Destiny"), ("name", "Name")):
            n, p = chart.get(f"{key}_number"), chart.get(f"{key}_planet")
            if n is None:
                continue
            nid = g.node(f"num:{key}", "Number", f"{label} {n}", f"{label} number", value=n)
            g.edge(me, nid, f"HAS_{key.upper()}")
            if p:
                g.edge(nid, planet(p), "RULED_BY")
        for n in chart.get("lucky_numbers") or []:
            g.edge(me, g.node(f"lucky:{n}", "Number", f"Lucky {n}", "top tier of the weighted friendship score"), "LUCKY")
        for n in chart.get("challenging_numbers") or []:
            g.edge(me, g.node(f"chal:{n}", "Number", f"Challenging {n}", "a compatibility reading, not a bad-luck prediction"), "CHALLENGING")
        for c in chart.get("lucky_colours_primary") or []:
            g.edge(me, g.node(f"colour:{c}", "Recommendation", c, "lucky colour (Radical)"), "COLOUR")
        for s in chart.get("traditional_gemstones") or []:
            g.edge(g.node("num:radical", "Number", "Radical"), g.node(f"stone:{s}", "Recommendation", s, "association only: REQUIRES_KUNDLI_REVIEW"), "TRADITIONAL_STONE")
        for key, label in (("nakshatra", "Nakshatra"), ("tithi", "Tithi"), ("vara", "Vara"), ("yoga", "Yoga"), ("karana", "Karana")):
            name = chart.get(f"{key}_name")
            if not name:
                continue
            pid = g.node(f"pan:{key}", "Panchang", f"{label}: {name}", f"{label} at the exact birth instant")
            g.edge(me, pid, f"BORN_IN_{key.upper()}")
            if key == "nakshatra" and chart.get("nakshatra_lord"):
                g.edge(pid, planet(chart["nakshatra_lord"]), "LORD")
            if key == "vara" and chart.get("vara_lord"):
                g.edge(pid, planet(chart["vara_lord"]), "LORD")
        row = None
        try:
            from .astro import engine  # only present in Astro Manas
            row = engine.get_user_row(customer_id)
        except ImportError:
            row = None
        if row:
            for key in ("nakshatra", "tithi", "vara", "yoga", "karana"):
                for t in row.get(f"{key}_tags") or []:
                    g.edge(f"pan:{key}", g.node(f"trait:{t}", "Trait", t), "GIVES_TRAIT")

    # Facts: each cites its rows (or chart columns); beliefs cite facts.
    for f in brain["facts"]:
        if f["value"] in (None, False, [], ""):
            continue
        fid = g.node(f"fact:{f['id']}", "Fact", f"{f['id'].replace('_', ' ')} = {f['value']}", f["formula"],
                     question=f["question"], value=f["value"], kind=f.get("kind"))
        cited = 0
        for c in f["citations"]:
            src, rid = c["source"], str(c["row_id"])
            target = row_node.get((src, rid))
            if src == "user":
                col = rid.split(".", 1)[-1]
                target = {"radical_number": "num:radical", "radical_calculation": "num:radical", "destiny_number": "num:destiny",
                          "destiny_calculation": "num:destiny", "name_number": "num:name", "name_calculation": "num:name",
                          "nakshatra_index": "pan:nakshatra", "nakshatra_lord": "pan:nakshatra", "radical_planet": "num:radical",
                          "lucky_numbers": "person"}.get(col)
            if target:
                g.edge(target, fid, "EVIDENCE_FOR")
                cited += 1
        if not cited:
            g.edge(me, fid, "KNOWN_FACT")
    for b in brain["beliefs"]:
        bid = g.node(f"belief:{b['id']}", "Belief", f"{b['id'].replace('_', ' ')}: {b['value'] or b['status'].replace('_', ' ')}",
                     b["reasoning"], confidence=b["confidence"], status=b["status"])
        g.edge(bid, me, "BELIEF_ABOUT")
        for c in b["cites"]:
            g.edge(f"fact:{c}", bid, "SUPPORTS")

    # Decision: the chosen action, resting on beliefs, through a channel, with a matched astrologer.
    if decision:
        did = g.node("decision", "Decision", f"Decision: {decision['action'].replace('_', ' ')}", decision["reason"],
                     offer=decision.get("offer") or decision.get("tone"), channel=decision.get("channel"), send_at=decision.get("send_at"))
        g.edge(me, did, "NEXT_ACTION")
        for b in brain["beliefs"]:
            if b["status"] == "formed":
                g.edge(f"belief:{b['id']}", did, "INFORMS")
        if decision.get("channel"):
            g.edge(did, g.node(f"ch:{decision['channel']}", "Channel", decision["channel"].replace("_", "-").title()), "VIA")
        off = decision.get("offer") or decision.get("tone")
        if off:
            g.edge(did, g.node(f"offer:{off}", "Offer", off.replace("_", " ").title()), "OFFERS")
        if decision.get("astrologer"):
            a = decision["astrologer"]
            g.edge(did, g.node(f"astro:{a['id']}", "Astrologer", a["name"], a.get("why", "")), "MATCHED")

    nodes = list(g.nodes.values())
    degree = Counter([e["source"] for e in g.edges] + [e["target"] for e in g.edges])
    for n in nodes:
        n["degree"] = degree.get(n["id"], 0)
    counts = Counter(n["type"] for n in nodes)
    return {"nodes": nodes, "edges": g.edges, "types": [{"type": t, "color": c, "count": counts[t]} for t, c in TYPES.items() if counts[t]],
            "title": brain["display_name"], "alias": brain["alias"]}
