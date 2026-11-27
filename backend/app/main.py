"""Manas API."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import decide as decide_mod
from . import ingest as ingest_mod
from . import llm, sample_data, store, twin
from .brain.build import build_brain
from .packs import PACKS, get_pack, pack_summaries

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Manas", version="0.1.0", description="A living brain for every customer.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["*"], allow_headers=["*"])
store.init()

def _active_pack() -> str:
    return store.get_setting("pack", "emi_collection")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "llm": llm.status(), "pack": _active_pack(), "sources": store.source_counts()}


@app.get("/api/packs")
def packs() -> list[dict[str, Any]]:
    return pack_summaries()


class DemoRequest(BaseModel):
    pack: str = "emi_collection"
    customers: int = 120


@app.post("/api/demo/load")
def load_demo(req: DemoRequest) -> dict[str, Any]:
    if req.pack not in PACKS:
        raise HTTPException(404, f"Unknown pack {req.pack}")
    store.reset()
    store.set_setting("pack", req.pack)
    data = sample_data.DATASETS[req.pack](n=max(10, min(req.customers, 1000)))
    loaded = {src: store.put_records(src, rows, sample_data.ID_FIELDS[src], "customer_id") for src, rows in data.items()}
    return {"pack": req.pack, "loaded": loaded}


def _pack_sources(pack: str) -> list[str]:
    return list(sample_data.DATASETS[pack](n=2).keys())


@app.get("/api/ingest/schema")
def ingest_schema(pack: str | None = None) -> dict[str, Any]:
    pk = pack or _active_pack()
    return {"pack": pk, "sources": ingest_mod.schema(pk, _pack_sources(pk)),
            "formats": ["CSV (comma, semicolon, tab or pipe)", "Excel .xlsx (first sheet)", "JSON array", "NDJSON"],
            "dates": "DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD, with or without time"}


@app.get("/api/ingest/template/{source}")
def ingest_template(source: str, pack: str | None = None) -> Response:
    pk = pack or _active_pack()
    if source not in _pack_sources(pk):
        raise HTTPException(404, f"{source} is not part of the {pk} pack")
    return Response(ingest_mod.template_csv(source, pk), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{pk}_{source}_template.csv"'})


@app.post("/api/ingest/{source}")
async def ingest(source: str, file: UploadFile = File(...), mode: str = Form("append"), pack: str | None = Form(None)) -> dict[str, Any]:
    pk = pack or _active_pack()
    store.set_setting("pack", pk)
    raw = await file.read()
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(413, "File is larger than 50 MB; split it or use the API in batches.")
    try:
        return ingest_mod.ingest(source, file.filename or "upload.csv", raw, pk, "replace" if mode == "replace" else "append")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # unreadable file: tell the user what went wrong instead of a 500
        raise HTTPException(400, f"Could not read {file.filename}: {e.__class__.__name__}: {e}")


class ResetRequest(BaseModel):
    confirm: bool = False


@app.post("/api/data/reset")
def reset_data(req: ResetRequest) -> dict[str, Any]:
    if not req.confirm:
        raise HTTPException(400, "Send confirm: true to delete all uploaded data, brains and decisions.")
    store.reset()
    return {"reset": True}


class BuildRequest(BaseModel):
    pack: str | None = None
    limit: int | None = None


@app.post("/api/brains/build")
def build_all(req: BuildRequest) -> dict[str, Any]:
    pack = req.pack or _active_pack()
    get_pack(pack)
    store.set_setting("pack", pack)
    ids = store.customer_ids()[: req.limit or None]
    today = date.today()
    # Claude calls are I/O bound; a small pool keeps a 100-customer build quick without hammering rate limits.
    with ThreadPoolExecutor(max_workers=6 if llm.enabled() else 1) as pool:
        brains = list(pool.map(lambda cid: build_brain(cid, pack, today), ids))
    return {"pack": pack, "built": len(brains), "llm": llm.status()}


class DecideAllRequest(BaseModel):
    use_llm: bool = False


@app.post("/api/decide/all")
def decide_all(req: DecideAllRequest) -> dict[str, Any]:
    counts: dict[str, int] = {}
    brains = store.all_brains()
    pop = twin.population_stats(brains)
    for cid in [b["customer_id"] for b in brains]:
        d = decide_mod.decide(cid, use_llm=req.use_llm, pop=pop)
        counts[d["action"]] = counts.get(d["action"], 0) + 1
    return {"decided": sum(counts.values()), "by_action": counts}


@app.get("/api/customers")
def customers() -> list[dict[str, Any]]:
    decisions = store.latest_decisions()
    out = []
    for b in store.all_brains():
        d = decisions.get(b["customer_id"])
        out.append({
            "customer_id": b["customer_id"], "alias": b["alias"], "display_name": b["display_name"], "pack": b["pack"],
            "language": b["persona"].get("language"), "city": b["persona"].get("city"), "mood": b["persona"].get("mood"),
            "beliefs": {x["id"]: {"value": x["value"], "status": x["status"]} for x in b["beliefs"]},
            "headline": _headline(b),
            "decision": {k: d.get(k) for k in ("action", "channel", "window", "tone", "send_at", "arm", "confidence")} if d else None,
        })
    return out


def _headline(b: dict[str, Any]) -> dict[str, Any]:
    fv = {f["id"]: f["value"] for f in b["facts"]}
    if b["pack"] == "emi_collection":
        return {"overdue_amount": fv.get("overdue_amount"), "days_past_due": fv.get("days_past_due")}
    return {"plan": fv.get("plan"), "days_to_renewal": fv.get("days_to_renewal"), "price": fv.get("price")}


@app.get("/api/customers/{customer_id}")
def customer(customer_id: str) -> dict[str, Any]:
    brain = store.get_brain(customer_id)
    if not brain:
        raise HTTPException(404, "No brain for this customer yet. Build brains first.")
    return {"brain": brain, "decision": store.latest_decision(customer_id), "arm": decide_mod.arm_for(customer_id)}


@app.post("/api/customers/{customer_id}/rebuild")
def rebuild(customer_id: str) -> dict[str, Any]:
    return build_brain(customer_id, _active_pack())


class DecideRequest(BaseModel):
    use_llm: bool = True


@app.post("/api/customers/{customer_id}/decide")
def decide_one(customer_id: str, req: DecideRequest) -> dict[str, Any]:
    try:
        return decide_mod.decide(customer_id, use_llm=req.use_llm)
    except KeyError:
        raise HTTPException(404, "No brain for this customer yet.")


class AskRequest(BaseModel):
    question: str


@app.post("/api/customers/{customer_id}/ask")
def ask(customer_id: str, req: AskRequest) -> dict[str, Any]:
    try:
        return decide_mod.ask(customer_id, req.question)
    except KeyError:
        raise HTTPException(404, "No brain for this customer yet.")


@app.post("/api/outcomes/simulate")
def simulate_outcomes() -> dict[str, Any]:
    return decide_mod.simulate_outcomes()


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    brains = store.all_brains()
    decisions = store.latest_decisions()
    beliefs: dict[str, dict[str, int]] = {}
    for b in brains:
        for x in b["beliefs"]:
            key = x["value"] if x["status"] == "formed" else x["status"]
            beliefs.setdefault(x["id"], {}).setdefault(key, 0)
            beliefs[x["id"]][key] += 1
    actions: dict[str, int] = {}
    channels: dict[str, int] = {}
    for d in decisions.values():
        actions[d["action"]] = actions.get(d["action"], 0) + 1
        if d.get("channel"):
            channels[d["channel"]] = channels.get(d["channel"], 0) + 1
    return {"pack": _active_pack(), "brains": len(brains), "decisions": len(decisions), "beliefs": beliefs,
            "actions": actions, "channels": channels, "uplift": decide_mod.uplift(), "llm": llm.status(),
            "sources": store.source_counts()}


class SettingRequest(BaseModel):
    number_system: str


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return {"number_system": store.get_setting("number_system", "indian"), "pack": _active_pack()}


@app.post("/api/settings")
def set_settings(req: SettingRequest) -> dict[str, Any]:
    if req.number_system not in {"indian", "international"}:
        raise HTTPException(400, "number_system must be indian or international")
    store.set_setting("number_system", req.number_system)
    return get_settings()


@app.get("/api/customers/{customer_id}/graph")
def brain_graph_view(customer_id: str) -> dict[str, Any]:
    from . import brain_graph

    out = brain_graph.build(customer_id)
    if not out:
        raise HTTPException(404, "No brain for this customer yet.")
    return out


# ---------- Integrations: Mixpanel / PostHog, messaging platforms ----------
from fastapi import Header, Request  # noqa: E402


@app.get("/api/integrations")
def integrations() -> dict[str, Any]:
    from . import analytics, messaging

    return {"analytics": analytics.status(), "platforms": messaging.providers(),
            "event_map": analytics.EVENT_MAP, "pushed_properties": [f"manas_{k}" for k in analytics.SAFE_PROPS],
            "never_pushed": ["phone numbers", "amounts owed", "dispute or hardship signals", "anything read from notes and replies"]}


@app.post("/api/collect/{source}")
async def collect(source: str, request: Request, x_manas_secret: str | None = Header(default=None)) -> dict[str, Any]:
    """Webhook for live events. Accepts one event or a list, in Mixpanel, PostHog or generic shape."""
    import os
    from . import analytics

    if source not in analytics.TRANSFORM:
        raise HTTPException(404, "source must be mixpanel, posthog or generic")
    secret = os.environ.get("MANAS_COLLECT_SECRET")
    if secret and x_manas_secret != secret:
        raise HTTPException(401, "bad or missing X-Manas-Secret header")
    body = await request.json()
    items = body if isinstance(body, list) else body.get("batch") or body.get("events") or [body]
    return analytics.store_events([analytics.TRANSFORM[source](e) for e in items if isinstance(e, dict)])


class SyncRequest(BaseModel):
    days: int = 7
    dry_run: bool | None = None


@app.post("/api/integrations/{provider}/sync")
def integration_sync(provider: str, req: SyncRequest) -> dict[str, Any]:
    from . import analytics

    try:
        return analytics.sync(provider, req.days, req.dry_run)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"{provider} sync failed: {e.__class__.__name__}: {e}")


class PushRequest(BaseModel):
    customer_ids: list[str] | None = None
    dry_run: bool | None = None


@app.post("/api/integrations/{provider}/push")
def integration_push(provider: str, req: PushRequest) -> dict[str, Any]:
    from . import analytics

    try:
        return analytics.push(provider, req.customer_ids, req.dry_run)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"{provider} push failed: {e.__class__.__name__}: {e}")
