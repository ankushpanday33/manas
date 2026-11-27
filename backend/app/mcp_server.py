"""MCP server: lets Claude (or any MCP client) read and act on the brains.

Run (stdio):   uv run --directory backend python -m app.mcp_server
Register it with the .mcp.json at the repo root (Claude Code picks it up automatically in this folder).

Every tool reads the same database as the web app. Tools never return phone numbers.
Logs go to stderr because stdout is the MCP protocol channel.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

try:  # MCP Python SDK v2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # v1
    from mcp.server.fastmcp import FastMCP as _Server

from . import analytics, decide, messaging, store

store.init()
server = _Server("manas")

PRIVATE = {"dob", "birth_time", "birth_latitude", "birth_longitude", "birth_place_name", "phone", "birth_datetime_utc"}


def _brain_summary(b: dict[str, Any]) -> dict[str, Any]:
    return {"customer_id": b["customer_id"], "alias": b["alias"], "pack": b["pack"], "persona": b["persona"].get("narrative"),
            "beliefs": {x["id"]: x["value"] or x["status"] for x in b["beliefs"]},
            "predictions": {k: (b.get("predictions") or {}).get(k, {}).get("value") for k in ("purchase_propensity_7d", "churn_risk_14d", "login_completion")},
            "facts": {f["id"]: f["value"] for f in b["facts"] if f["value"] not in (None, False, [], "")}}


def _decision_summary(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d:
        return None
    dl = d.get("delivery") or {}
    return {"action": d["action"], "offer": d.get("tone"), "channel": d.get("channel"), "send_at": d.get("send_at"),
            "platform": (dl.get("provider") or {}).get("name"), "platform_why": (dl.get("provider") or {}).get("why"),
            "fallback": dl.get("fallback"), "language": dl.get("language"), "message": (dl.get("message") or {}).get("body") or d.get("message_preview"),
            "channel_payload": {k: v for k, v in (dl.get("message") or {}).items() if k in {"whatsapp_template", "sms", "push", "in_app"}},
            "reason": d["reason"], "timing": d.get("timing_reason"), "arm": d.get("arm")}


@server.tool()
def list_users(action: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List users with their next action. Filter by action: contact, hold, human_review or no_action."""
    latest = store.latest_decisions()
    out = []
    for b in store.all_brains():
        d = latest.get(b["customer_id"]) or {}
        if action and d.get("action") != action:
            continue
        out.append({"customer_id": b["customer_id"], "alias": b["alias"], "action": d.get("action"), "offer": d.get("tone"),
                    "channel": d.get("channel"), "send_at": d.get("send_at")})
        if len(out) >= limit:
            break
    return out


@server.tool()
def get_user_brain(customer_id: str) -> dict[str, Any]:
    """One user's brain: chart, persona, beliefs, predictions and key facts. No birth details are returned."""
    b = store.get_brain(customer_id)
    if not b:
        return {"error": f"no brain for {customer_id}; build brains first"}
    return _brain_summary(b)


@server.tool()
def get_next_action(customer_id: str) -> dict[str, Any] | None:
    """The latest decision: action, offer, channel, messaging platform and why, fallback, language and the ready message."""
    return _decision_summary(store.latest_decision(customer_id))


@server.tool()
def decide_now(customer_id: str, use_llm: bool = False) -> dict[str, Any] | None:
    """Run the decision again for one user (guards, twin, council, timing, delivery plan) and return it."""
    try:
        return _decision_summary(decide.decide(customer_id, use_llm=use_llm))
    except KeyError:
        return {"error": f"no brain for {customer_id}"}


@server.tool()
def explain_decision(customer_id: str) -> dict[str, Any]:
    """The receipts behind the latest decision: world, memory, facts, beliefs, twin, council and the decision."""
    d = store.latest_decision(customer_id)
    if not d:
        return {"error": f"no decision for {customer_id}"}
    return {"receipts": d["receipts"], "policy_checks": d["policy_checks"], "reason": d["reason"]}


@server.tool()
def ask_brain(customer_id: str, question: str) -> dict[str, Any]:
    """Ask a plain-language question about one user. The answer cites fact and belief ids."""
    try:
        return decide.ask(customer_id, question)
    except KeyError:
        return {"error": f"no brain for {customer_id}"}


@server.tool()
def ingest_events(events: list[dict[str, Any]], source: str = "generic") -> dict[str, Any]:
    """Store in-app events. source = generic ({customer_id, event_name, at, cta, screen}), mixpanel or posthog (vendor shape)."""
    if source not in analytics.TRANSFORM:
        return {"error": "source must be generic, mixpanel or posthog"}
    return analytics.store_events([analytics.TRANSFORM[source](e) for e in events])


@server.tool()
def sync_analytics(provider: str, days: int = 7, dry_run: bool = True) -> dict[str, Any]:
    """Pull recent events from mixpanel or posthog. dry_run=True shows the request without calling the vendor."""
    return analytics.sync(provider, days, dry_run)


@server.tool()
def push_decisions(provider: str, customer_ids: list[str] | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Write next actions to mixpanel or posthog as user properties plus a manas_decision event. dry_run=True previews it."""
    return analytics.push(provider, customer_ids, dry_run)


@server.tool()
def rebuild_and_decide(customer_ids: list[str] | None = None) -> dict[str, Any]:
    """Rebuild brains (after new events) and decide again. Without ids, every user."""
    from .brain.build import build_brain

    ids = customer_ids or store.customer_ids()
    pack = store.get_setting("pack", "emi_collection")
    built, failed = 0, []
    for cid in ids:
        try:
            build_brain(cid, pack)
            decide.decide(cid, use_llm=False)
            built += 1
        except Exception as e:
            failed.append({"customer_id": cid, "error": str(e)})
    return {"rebuilt": built, "failed": failed}


@server.tool()
def messaging_platforms() -> list[dict[str, Any]]:
    """Messaging platforms by channel, whether each is configured, and the env vars that switch it on."""
    return [{k: p[k] for k in ("id", "name", "channel", "configured", "env", "cost_inr")} for p in messaging.providers()]


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
