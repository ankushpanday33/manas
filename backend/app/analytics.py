"""Mixpanel and PostHog: collect events in, push decisions out.

  collect  - POST /api/collect/{mixpanel|posthog|generic}: a webhook / pipeline posts events as they happen
  sync     - pull recent raw events (Mixpanel Raw Event Export, PostHog HogQL query API)
  push     - write each user's next action back as profile / person properties plus a `manas_decision` event

Credentials come only from env vars. Without them every call is a dry run that returns the exact request it would make
(secrets redacted), so the wiring can be checked before keys exist.

Never pushed to a third party: phone numbers, amounts owed, dispute or hardship signals, or anything read from notes and replies.

API shapes (checked against vendor docs, November 2026):
  Mixpanel export  GET https://data[-eu|-in].mixpanel.com/api/2.0/export?project_id&from_date&to_date  (service account basic auth, JSONL)
  Mixpanel profile POST https://api[-eu|-in].mixpanel.com/engage  [{"$token","$distinct_id","$set"}]
  Mixpanel event   POST https://api[-eu|-in].mixpanel.com/track   [{"event","properties":{"token","distinct_id","time","$insert_id"}}]
  PostHog query    POST {POSTHOG_HOST}/api/projects/{id}/query/  {"query":{"kind":"HogQLQuery","query":...}}  (personal API key, Bearer)
  PostHog capture  POST {POSTHOG_INGEST_HOST}/batch/  {"api_key","batch":[...]}  ($set via properties.$set)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

# Vendor event names -> Manas vocabulary. Unknown names are kept, lower-cased with underscores.
EVENT_MAP = {
    "login_viewed": "viewed_login", "login_screen_viewed": "viewed_login", "sign_in_viewed": "viewed_login",
    "login_clicked": "interacted_login", "sign_in_clicked": "interacted_login", "otp_requested": "interacted_login",
    "login_success": "completed_login", "logged_in": "completed_login", "sign_in_completed": "completed_login", "$identify": "completed_login",
    "cta_clicked": "clicked_cta", "button_clicked": "clicked_cta", "$autocapture": "clicked_cta",
    "paywall_viewed": "viewed_paywall", "pricing_viewed": "viewed_paywall", "payment_page_viewed": "viewed_paywall",
    "checkout_started": "started_checkout", "payment_initiated": "started_checkout",
    "checkout_abandoned": "abandoned_checkout", "payment_failed": "abandoned_checkout", "payment_cancelled": "abandoned_checkout",
    "purchase": "completed_purchase", "order_completed": "completed_purchase", "payment_success": "completed_purchase",
    "$pageview": "viewed_screen", "$screen": "viewed_screen", "screen_viewed": "viewed_screen", "page_viewed": "viewed_screen",
    "app_opened": "app_open", "$session_start": "app_open", "application_opened": "app_open",
}
OVERRIDE = os.environ.get("MANAS_EVENT_MAP_JSON")
if OVERRIDE and os.path.exists(OVERRIDE):
    EVENT_MAP.update(json.loads(open(OVERRIDE, encoding="utf-8").read()))


def map_event(name: str) -> str:
    key = str(name or "").strip().lower().replace(" ", "_").replace("-", "_")
    return EVENT_MAP.get(key, EVENT_MAP.get(str(name or ""), key))


def _ist(ts: datetime) -> str:
    return ts.astimezone(timezone(timedelta(hours=5, minutes=30))).replace(tzinfo=None).isoformat(timespec="seconds")


def _row(customer_id: Any, at: str, event: str, props: dict[str, Any], uid: str) -> dict[str, Any] | None:
    if not customer_id:
        return None
    return {"event_id": uid, "customer_id": str(customer_id), "at": at, "event_name": map_event(event),
            "screen": str(props.get("screen") or props.get("$screen_name") or props.get("$pathname") or props.get("$current_url") or "")[:80],
            "cta": str(props.get("cta") or props.get("button") or props.get("button_name") or props.get("$el_text") or "")[:60],
            "source_event": event}


def from_mixpanel(e: dict[str, Any]) -> dict[str, Any] | None:
    p = e.get("properties", {})
    t = p.get("time")
    when = _ist(datetime.fromtimestamp(t / 1000 if t and t > 1e11 else (t or 0), tz=timezone.utc)) if t else ""
    uid = p.get("$insert_id") or hashlib.sha1(json.dumps(e, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return _row(p.get("$user_id") or p.get("distinct_id"), when, e.get("event", ""), p, f"MP-{uid}")


def from_posthog(e: dict[str, Any]) -> dict[str, Any] | None:
    ev = e.get("event") if isinstance(e.get("event"), dict) else e     # webhook destinations wrap the event
    props = ev.get("properties") or {}
    if isinstance(props, str):
        props = json.loads(props or "{}")
    ts = ev.get("timestamp")
    try:
        when = _ist(datetime.fromisoformat(str(ts).replace("Z", "+00:00"))) if ts else ""
    except ValueError:
        when = str(ts)
    uid = ev.get("uuid") or hashlib.sha1(json.dumps(ev, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return _row(ev.get("distinct_id") or props.get("distinct_id"), when, ev.get("event", ""), props, f"PH-{uid}")


def from_generic(e: dict[str, Any]) -> dict[str, Any] | None:
    uid = e.get("event_id") or hashlib.sha1(json.dumps(e, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return _row(e.get("customer_id") or e.get("user_id") or e.get("distinct_id"), str(e.get("at") or e.get("timestamp") or ""),
                e.get("event_name") or e.get("event", ""), e.get("properties") or e, f"GE-{uid}")


TRANSFORM = {"mixpanel": from_mixpanel, "posthog": from_posthog, "generic": from_generic}


def store_events(rows: list[dict[str, Any]]) -> dict[str, Any]:
    from . import store

    good = [r for r in rows if r and r.get("at")]
    loaded = store.put_records("events", good, "event_id", "customer_id") if good else 0
    known = set(store.customer_ids())
    orphans = sorted({r["customer_id"] for r in good if r["customer_id"] not in known})
    return {"received": len(rows), "stored": loaded, "dropped": len(rows) - len(good), "unknown_users": orphans[:20],
            "mapped_names": sorted({f"{r['source_event']} -> {r['event_name']}" for r in good if r["source_event"] != r["event_name"]})[:20]}


# ---------- config ----------
def config() -> dict[str, Any]:
    region = os.environ.get("MIXPANEL_REGION", "us").lower()
    sfx = {"eu": "-eu", "in": "-in"}.get(region, "")
    return {
        "mixpanel": {"region": region, "export_host": os.environ.get("MIXPANEL_EXPORT_HOST", f"https://data{sfx}.mixpanel.com"),
                     "api_host": os.environ.get("MIXPANEL_API_HOST", f"https://api{sfx}.mixpanel.com"),
                     "project_id": os.environ.get("MIXPANEL_PROJECT_ID"), "user": os.environ.get("MIXPANEL_SERVICE_USER"),
                     "secret": os.environ.get("MIXPANEL_SERVICE_SECRET"), "token": os.environ.get("MIXPANEL_TOKEN"),
                     "env": ["MIXPANEL_PROJECT_ID", "MIXPANEL_SERVICE_USER", "MIXPANEL_SERVICE_SECRET", "MIXPANEL_TOKEN", "MIXPANEL_REGION (us|eu|in)"]},
        "posthog": {"host": os.environ.get("POSTHOG_HOST", "https://us.posthog.com"),
                    "ingest_host": os.environ.get("POSTHOG_INGEST_HOST", "https://us.i.posthog.com"),
                    "project_id": os.environ.get("POSTHOG_PROJECT_ID"), "personal_key": os.environ.get("POSTHOG_PERSONAL_API_KEY"),
                    "project_key": os.environ.get("POSTHOG_PROJECT_API_KEY"),
                    "env": ["POSTHOG_HOST", "POSTHOG_INGEST_HOST", "POSTHOG_PROJECT_ID", "POSTHOG_PERSONAL_API_KEY", "POSTHOG_PROJECT_API_KEY"]},
    }


def status() -> dict[str, Any]:
    c = config()
    mp, ph = c["mixpanel"], c["posthog"]
    return {
        "mixpanel": {"can_sync": bool(mp["project_id"] and mp["user"] and mp["secret"]), "can_push": bool(mp["token"]),
                     "region": mp["region"], "export_host": mp["export_host"], "api_host": mp["api_host"], "env": mp["env"]},
        "posthog": {"can_sync": bool(ph["project_id"] and ph["personal_key"]), "can_push": bool(ph["project_key"]),
                    "host": ph["host"], "ingest_host": ph["ingest_host"], "env": ph["env"]},
        "collect": {"url": "/api/collect/{mixpanel|posthog|generic}", "secret_required": bool(os.environ.get("MANAS_COLLECT_SECRET"))},
    }


# ---------- sync (pull) ----------
def sync(provider: str, days: int = 7, dry_run: bool | None = None) -> dict[str, Any]:
    import httpx

    c = config()[provider]
    st = status()[provider]
    if provider == "mixpanel":
        to_d, from_d = date.today(), date.today() - timedelta(days=days)
        req = {"method": "GET", "url": f"{c['export_host']}/api/2.0/export",
               "params": {"project_id": c["project_id"] or "{MIXPANEL_PROJECT_ID}", "from_date": from_d.isoformat(), "to_date": to_d.isoformat()},
               "auth": "service account basic auth (MIXPANEL_SERVICE_USER:MIXPANEL_SERVICE_SECRET)"}
        if dry_run or not st["can_sync"]:
            return {"dry_run": True, "request": req, "missing": [e for e in c["env"][:3] if not os.environ.get(e)]}
        auth = base64.b64encode(f"{c['user']}:{c['secret']}".encode()).decode()
        r = httpx.get(req["url"], params=req["params"], headers={"Authorization": f"Basic {auth}", "Accept": "text/plain"}, timeout=120)
        r.raise_for_status()
        rows = [from_mixpanel(json.loads(line)) for line in r.text.splitlines() if line.strip()]
        return {"dry_run": False, **store_events(rows)}
    if provider == "posthog":
        hogql = (f"SELECT uuid, event, distinct_id, timestamp, properties FROM events "
                 f"WHERE timestamp > now() - INTERVAL {int(days)} DAY ORDER BY timestamp LIMIT 50000")
        req = {"method": "POST", "url": f"{c['host']}/api/projects/{c['project_id'] or '{POSTHOG_PROJECT_ID}'}/query/",
               "json": {"query": {"kind": "HogQLQuery", "query": hogql}, "name": "manas_sync"},
               "auth": "Authorization: Bearer {POSTHOG_PERSONAL_API_KEY}"}
        if dry_run or not st["can_sync"]:
            return {"dry_run": True, "request": req, "missing": [e for e in ("POSTHOG_PROJECT_ID", "POSTHOG_PERSONAL_API_KEY") if not os.environ.get(e)]}
        r = httpx.post(req["url"], json=req["json"], headers={"Authorization": f"Bearer {c['personal_key']}"}, timeout=120)
        r.raise_for_status()
        body = r.json()
        cols = body.get("columns", ["uuid", "event", "distinct_id", "timestamp", "properties"])
        rows = [from_posthog(dict(zip(cols, rec))) for rec in body.get("results", [])]
        return {"dry_run": False, **store_events(rows)}
    raise ValueError("provider must be mixpanel or posthog")


# ---------- push ----------
SAFE_PROPS = ("action", "offer", "channel", "window", "send_at", "language", "provider", "purchase_propensity_7d",
              "churn_risk_14d", "arm")


def decision_properties(customer_id: str) -> dict[str, Any] | None:
    from . import store

    d = store.latest_decision(customer_id)
    b = store.get_brain(customer_id)
    if not d or not b:
        return None
    fv = {f["id"]: f["value"] for f in b["facts"]}
    dl = d.get("delivery") or {}
    props = {"action": d["action"], "offer": d.get("tone"), "channel": d.get("channel"), "window": d.get("window"),
             "send_at": d.get("send_at"), "language": (dl.get("language") or {}).get("template_language") or d.get("language"),
             "provider": (dl.get("provider") or {}).get("id"), "purchase_propensity_7d": fv.get("purchase_propensity_7d"),
             "churn_risk_14d": fv.get("churn_risk_14d"), "arm": d.get("arm")}
    return {f"manas_{k}": props[k] for k in SAFE_PROPS if props.get(k) is not None}


def push(provider: str, customer_ids: list[str] | None = None, dry_run: bool | None = None) -> dict[str, Any]:
    import httpx
    from . import store

    ids = customer_ids or [b["customer_id"] for b in store.all_brains()]
    items = [(cid, decision_properties(cid)) for cid in ids]
    items = [(cid, p) for cid, p in items if p]
    now = int(datetime.now(tz=timezone.utc).timestamp())
    c = config()[provider]
    st = status()[provider]
    if provider == "mixpanel":
        profiles = [{"$token": c["token"] or "{MIXPANEL_TOKEN}", "$distinct_id": cid, "$set": p} for cid, p in items]
        events = [{"event": "manas_decision", "properties": {"token": c["token"] or "{MIXPANEL_TOKEN}", "distinct_id": cid, "time": now,
                                                            "$insert_id": f"manas-{cid}-{p.get('manas_send_at') or now}", **p}} for cid, p in items]
        reqs = [{"method": "POST", "url": f"{c['api_host']}/engage", "json": profiles[:2], "count": len(profiles)},
                {"method": "POST", "url": f"{c['api_host']}/track", "json": events[:2], "count": len(events)}]
        if dry_run or not st["can_push"]:
            return {"dry_run": True, "users": len(items), "requests": reqs, "missing": [] if c["token"] else ["MIXPANEL_TOKEN"]}
        sent = 0
        for i in range(0, len(profiles), 200):     # Mixpanel accepts batches; it returns 200 even on validation errors, so read the body
            r1 = httpx.post(reqs[0]["url"], params={"verbose": 1}, json=profiles[i:i + 200], timeout=60)
            r2 = httpx.post(reqs[1]["url"], params={"verbose": 1}, json=events[i:i + 200], timeout=60)
            r1.raise_for_status(); r2.raise_for_status()
            if '"status":0' in r1.text.replace(" ", "") or '"status":0' in r2.text.replace(" ", ""):
                raise RuntimeError(f"Mixpanel rejected the batch: {r1.text[:200]} {r2.text[:200]}")
            sent += len(profiles[i:i + 200])
        return {"dry_run": False, "users": sent}
    if provider == "posthog":
        batch = []
        for cid, p in items:
            batch.append({"event": "$set", "distinct_id": cid, "properties": {"$set": p}})
            batch.append({"event": "manas_decision", "distinct_id": cid, "properties": p})
        req = {"method": "POST", "url": f"{c['ingest_host']}/batch/", "json": {"api_key": c["project_key"] or "{POSTHOG_PROJECT_API_KEY}", "batch": batch[:4]},
               "count": len(batch)}
        if dry_run or not st["can_push"]:
            return {"dry_run": True, "users": len(items), "requests": [req], "missing": [] if c["project_key"] else ["POSTHOG_PROJECT_API_KEY"]}
        for i in range(0, len(batch), 500):
            r = httpx.post(req["url"], json={"api_key": c["project_key"], "batch": batch[i:i + 500]}, timeout=60)
            r.raise_for_status()
        return {"dry_run": False, "users": len(items)}
    raise ValueError("provider must be mixpanel or posthog")
