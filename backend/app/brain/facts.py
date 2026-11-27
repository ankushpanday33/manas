"""Facts: answers computed in code, never guessed by a model. Each one cites the rows it read and the formula."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Callable


def _d(value: Any) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value)[:19]).date() if "T" in str(value) else date.fromisoformat(str(value)[:10])


def _dt(value: Any) -> datetime | None:
    return datetime.fromisoformat(str(value)[:19]) if value else None


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def window_of(hour: int, windows: dict[str, tuple[int, int]]) -> str | None:
    for name, (start, end) in windows.items():
        if start <= hour < end:
            return name
    return None


def comm_stats(records: dict[str, list[dict]], windows: dict[str, tuple[int, int]], success_dates: list[date]) -> dict[str, Any]:
    """Per channel x window: sends, delivered, read, replied, converted_3d (a conversion within 3 days of the send).

    Sends outside the pack's windows are still counted under 'outside' so nothing is silently dropped.
    """
    comms = sorted(records.get("communications", []), key=lambda c: c.get("sent_at", ""))
    inbound = [c for c in comms if c.get("direction") == "in"]
    stats: dict[str, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(lambda: {
        "sends": 0, "delivered": 0, "read": 0, "replied": 0, "converted_3d": 0, "rows": []}))
    for c in comms:
        if c.get("direction") != "out":
            continue
        sent = _dt(c.get("sent_at"))
        if not sent:
            continue
        ch = c.get("channel", "unknown")
        w = window_of(sent.hour, windows) or "outside"
        cell = stats[ch][w]
        cell["sends"] += 1
        cell["rows"].append(c["_row_id"])
        status = str(c.get("status", "")).lower()
        if status in {"delivered", "read", "answered"}:
            cell["delivered"] += 1
        if status in {"read", "answered"}:
            cell["read"] += 1
        if any(i.get("channel") == ch and sent < (_dt(i.get("sent_at")) or sent) <= sent + timedelta(hours=48) for i in inbound):
            cell["replied"] += 1
        # Only a message that was actually read (or a call answered) gets credit for a conversion that followed it.
        if status in {"read", "answered"} and any(sent.date() <= s <= sent.date() + timedelta(days=3) for s in success_dates):
            cell["converted_3d"] += 1
    return {ch: dict(ws) for ch, ws in stats.items()}


class FactBook:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(self, fid: str, question: str, value: Any, formula: str, cites: list[tuple[str, str]], unit: str | None = None) -> None:
        self.items.append({
            "id": fid, "question": question, "value": value, "unit": unit, "formula": formula,
            "citations": [{"source": s, "row_id": r} for s, r in cites], "kind": "computed",
        })


def _channel_rates(fb: FactBook, stats: dict[str, Any], channels: list[str]) -> None:
    for ch in channels:
        cells = stats.get(ch, {})
        sends = sum(c["sends"] for c in cells.values())
        rows = [(f"communications", r) for c in cells.values() for r in c["rows"]][:25]
        if ch == "voice":
            ans = sum(c["read"] for c in cells.values())
            fb.add(f"{ch}_answer_rate", "How often do they pick up calls?", round(ans / sends, 2) if sends else None,
                   f"answered / calls placed = {ans}/{sends}", rows)
        else:
            rd = sum(c["read"] for c in cells.values())
            rp = sum(c["replied"] for c in cells.values())
            fb.add(f"{ch}_read_rate", f"How often do they read {ch} messages?", round(rd / sends, 2) if sends else None,
                   f"read / sent = {rd}/{sends}", rows)
            fb.add(f"{ch}_reply_rate", f"How often do they reply on {ch}?", round(rp / sends, 2) if sends else None,
                   f"replies within 48h / sent = {rp}/{sends}", rows)


def _common_comm_facts(fb: FactBook, records: dict[str, list[dict]], stats: dict[str, Any], today: date) -> None:
    comms = records.get("communications", [])
    out90 = [c for c in comms if c.get("direction") == "out" and (_d(c.get("sent_at")) or today) >= today - timedelta(days=90)]
    fb.add("outbound_contacts_90d", "How many times did we contact them in 90 days?", len(out90),
           "count(communications where direction=out and sent_at >= today-90d)", [("communications", c["_row_id"]) for c in out90][:25])
    last7 = [c for c in comms if c.get("direction") == "out" and (_d(c.get("sent_at")) or date.min) >= today - timedelta(days=7)]
    fb.add("contacts_last_7d", "How many contacts in the last 7 days?", len(last7),
           "count(outbound in last 7 days)", [("communications", c["_row_id"]) for c in last7])
    inbound = sorted((c for c in comms if c.get("direction") == "in"), key=lambda c: c.get("sent_at", ""))
    if inbound:
        last = inbound[-1]
        fb.add("days_since_last_reply", "When did they last reply to us?", (today - _d(last["sent_at"])).days,
               f"today - last inbound sent_at ({last['sent_at'][:10]}) on {last.get('channel')}", [("communications", last["_row_id"])], "days")
    else:
        fb.add("days_since_last_reply", "When did they last reply to us?", None, "no inbound message on record", [], "days")

    best, best_rate, best_rows, best_n = None, -1.0, [], 0
    for ch, cells in stats.items():
        for w, c in cells.items():
            if c["sends"] >= 3 and w != "outside":
                rate = (c["read"] + 2 * c["replied"]) / (3 * c["sends"])
                if rate > best_rate:
                    best, best_rate, best_rows, best_n = f"{ch} · {w}", rate, c["rows"], c["sends"]
    fb.add("best_responding_slot", "Where and when do they actually respond?", best,
           f"argmax over channel x window of (reads + 2*replies)/(3*sends), min 3 sends; chosen slot had {best_n} sends" if best else "fewer than 3 sends in every slot",
           [("communications", r) for r in best_rows][:25])


def _event_facts(fb: "FactBook", records: dict[str, list[dict]], today: date, conversions_90d: int) -> dict[str, Any]:
    """In-app events and the transparent predictions built on them (shared by every pack)."""
    from .. import predict

    pred = predict.predict(records.get("events", []), {}, conversions_90d, today)
    f = pred["features"]
    rows = [("events", r) for r in pred.pop("rows")]
    fb.add("events_30d", "How many in-app events in 30 days?", f["events_30d"], "count(events, last 30 days)", rows)
    fb.add("cta_clicks_7d", "How many CTA clicks this week?", f["cta_clicks_7d"], "count(event_name = clicked_cta, last 7 days)", rows)
    fb.add("top_cta", "Which CTA do they click most?", f["top_cta"], "mode(cta where event_name = clicked_cta, 30d)", rows)
    fb.add("abandoned_checkout", "Did they leave a payment halfway?", f["abandoned_item"],
           "abandoned payment / checkout in 14 days with no later completion for the same CTA", rows)
    fb.add("login_dropoff", "Did they start login and not finish?", bool(f["login_dropoff"]),
           f"viewed_login {f['login_attempts_30d']} times, completed {f['login_completed']} (30d)", rows)
    for key, q in (("purchase_propensity_7d", "How likely are they to pay or buy in the next 7 days?"),
                   ("churn_risk_14d", "How likely are they to go quiet for 14 days?")):
        pr = pred[key]
        fb.add(key, q, pr["value"], ("logistic over named event features; top drivers: " + ", ".join(f"{d['feature']} {d['effect']:+}" for d in pr["drivers"][:3]))
               if pr["status"] == "ok" else pr["note"], rows)
    return pred


def emi_facts(records: dict[str, list[dict]], pack: dict[str, Any], today: date, memory: list[dict]) -> tuple[list[dict], dict]:
    fb = FactBook()
    loans = records.get("loans", [])
    pays = sorted(records.get("payments", []), key=lambda p: p.get("paid_at", ""))
    proms = records.get("promises", [])
    lc = [("loans", l["_row_id"]) for l in loans]

    overdue = sum(_f(l.get("overdue_amount")) for l in loans)
    fb.add("overdue_amount", "How much is overdue right now?", round(overdue), "sum(Loan.overdue_amount)", lc, "INR")
    fb.add("emi_amount", "What is the monthly EMI?", round(sum(_f(l.get("emi_amount")) for l in loans)), "sum(Loan.emi_amount)", lc, "INR")
    dpd = max((int(_f(l.get("days_past_due"))) for l in loans), default=0)
    fb.add("days_past_due", "How late is the most overdue loan?", dpd, "max(Loan.days_past_due)", lc, "days")
    bucket = "current" if dpd == 0 else "1-30" if dpd <= 30 else "31-60" if dpd <= 60 else "61-90" if dpd <= 90 else "90+"
    fb.add("arrears_bucket", "Which arrears bucket are they in?", bucket, "bucket(max days_past_due)", lc)

    yr = [p for p in pays if (_d(p.get("paid_at")) or date.min) >= today - timedelta(days=365)]
    pc = [("payments", p["_row_id"]) for p in yr]
    fb.add("payments_12m", "How many EMIs did they pay in 12 months?", len(yr), "count(Payment where paid_at >= today-365d)", pc)
    on_time = sum(1 for p in yr if _truthy(p.get("on_time")))
    fb.add("on_time_rate", "How often do they pay on time?", round(on_time / len(yr), 2) if yr else None,
           f"on_time payments / payments = {on_time}/{len(yr)}", pc)
    fb.add("late_payments_12m", "How many EMIs were paid late?", len(yr) - on_time, "count(Payment where on_time = false)",
           [("payments", p["_row_id"]) for p in yr if not _truthy(p.get("on_time"))])
    if pays:
        last = pays[-1]
        fb.add("days_since_last_payment", "When did they last pay?", (today - _d(last["paid_at"])).days,
               f"today - last Payment.paid_at ({last['paid_at'][:10]})", [("payments", last["_row_id"])], "days")
        method = Counter(p.get("method", "unknown") for p in pays).most_common(1)[0][0]
        fb.add("payment_method_pattern", "How do they usually pay?", method, "mode(Payment.method)", [("payments", p["_row_id"]) for p in pays][:25])
    else:
        fb.add("days_since_last_payment", "When did they last pay?", None, "no payment on record", [], "days")
        fb.add("payment_method_pattern", "How do they usually pay?", None, "no payment on record", [])

    closed = [p for p in proms if p.get("status") in {"kept", "broken"}]
    kept = [p for p in closed if p.get("status") == "kept"]
    fb.add("promises_kept", "How many past promises did they keep?", f"{len(kept)} of {len(closed)}",
           "count(PromiseToPay where status=kept) of closed promises", [("promises", p["_row_id"]) for p in closed])
    fb.add("promise_keep_rate", "How reliable are their promises?", round(len(kept) / len(closed), 2) if closed else None,
           f"kept / closed = {len(kept)}/{len(closed)}", [("promises", p["_row_id"]) for p in closed])
    open_p = [p for p in proms if p.get("status") == "open" and (_d(p.get("promised_date")) or date.min) >= today]
    fb.add("open_promise_date", "Is there an open promise to pay?", open_p[0]["promised_date"] if open_p else None,
           "PromiseToPay where status=open and promised_date >= today", [("promises", p["_row_id"]) for p in open_p])

    pay_dates = [_d(p["paid_at"]) for p in pays if p.get("paid_at")]
    stats = comm_stats(records, pack["windows"], pay_dates)
    _channel_rates(fb, stats, pack["channels"])
    _common_comm_facts(fb, records, stats, today)
    _memory_facts(fb, memory)
    pred = _event_facts(fb, records, today, len([p for p in pays if (_d(p.get("paid_at")) or date.min) >= today - timedelta(days=90)]))
    return fb.items, stats, pred


def subscription_facts(records: dict[str, list[dict]], pack: dict[str, Any], today: date, memory: list[dict]) -> tuple[list[dict], dict]:
    fb = FactBook()
    subs = sorted(records.get("subscriptions", []), key=lambda s: s.get("renews_on", ""))
    usage = records.get("usage", [])
    if subs:
        s = subs[-1]
        sc = [("subscriptions", s["_row_id"])]
        fb.add("plan", "Which plan are they on?", s.get("plan"), "Subscription.plan (latest)", sc)
        fb.add("price", "What do they pay?", round(_f(s.get("price"))), "Subscription.price", sc, "INR")
        renews = _d(s.get("renews_on"))
        fb.add("days_to_renewal", "How many days to renewal?", (renews - today).days if renews else None,
               f"Subscription.renews_on ({s.get('renews_on')}) - today", sc, "days")
        fb.add("auto_renew", "Is auto-renew on?", _truthy(s.get("auto_renew")), "Subscription.auto_renew", sc)
    fb.add("renewals_so_far", "How many times have they renewed before?", max(len(subs) - 1, 0), "count(Subscription) - 1",
           [("subscriptions", s["_row_id"]) for s in subs])

    def minutes(a: int, b: int) -> tuple[float, list]:
        rows = [u for u in usage if today - timedelta(days=b) <= (_d(u.get("date")) or date.min) < today - timedelta(days=a)]
        return sum(_f(u.get("minutes")) for u in rows), rows

    m30, r30 = minutes(0, 30)
    mprev, rprev = minutes(30, 60)
    fb.add("minutes_30d", "How much did they use in the last 30 days?", round(m30), "sum(Usage.minutes, last 30d)",
           [("usage", u["_row_id"]) for u in r30][:25], "min")
    trend = round((m30 - mprev) / mprev, 2) if mprev else None
    fb.add("usage_trend", "Is usage rising or falling?", trend, f"(last 30d - previous 30d) / previous 30d = ({round(m30)}-{round(mprev)})/{round(mprev)}",
           [("usage", u["_row_id"]) for u in (r30 + rprev)][:25])
    fb.add("active_days_30d", "On how many days were they active?", len({u.get("date") for u in r30}), "count(distinct Usage.date, last 30d)",
           [("usage", u["_row_id"]) for u in r30][:25], "days")
    top = Counter(u.get("content_type") for u in r30).most_common(1)
    fb.add("top_content", "What do they enjoy most?", top[0][0] if top else None, "mode(Usage.content_type, last 30d)",
           [("usage", u["_row_id"]) for u in r30][:25])
    last_use = max((_d(u.get("date")) for u in usage if u.get("date")), default=None)
    fb.add("days_since_last_use", "When did they last use the product?", (today - last_use).days if last_use else None,
           "today - max(Usage.date)", [], "days")

    renew_dates = [_d(s.get("renewed_on")) for s in subs if s.get("renewed_on")]
    stats = comm_stats(records, pack["windows"], [d for d in renew_dates if d])
    _channel_rates(fb, stats, pack["channels"])
    _common_comm_facts(fb, records, stats, today)
    _memory_facts(fb, memory)
    pred = _event_facts(fb, records, today, len([d for d in renew_dates if d and d >= today - timedelta(days=90)]))
    return fb.items, stats, pred


def _memory_facts(fb: FactBook, memory: list[dict]) -> None:
    def latest(kind: str) -> dict | None:
        found = [m for m in memory if m["kind"] == kind]
        return found[-1] if found else None

    for kind, q in [("dispute", "Have they raised a dispute?"), ("hardship", "Have they mentioned hardship?"),
                    ("contact_objection", "Have they asked us to stop contacting them?")]:
        m = latest(kind)
        fb.items.append({"id": f"{kind}_flag", "question": q, "value": bool(m), "unit": None,
                         "formula": f"read from text ({m['method']}), written {m['written_on']}" if m else "no such signal in any text",
                         "citations": [m["ref"]] if m else [], "kind": "extracted"})
    m = latest("time_preference")
    fb.items.append({"id": "stated_time_preference", "question": "Did they say when to contact them?", "value": m["detail"] if m else None,
                     "unit": None, "formula": f"read from text, written {m['written_on']}" if m else "not stated",
                     "citations": [m["ref"]] if m else [], "kind": "extracted"})
    m = latest("salary_dependent")
    fb.items.append({"id": "salary_dependent", "question": "Do they tie payment to salary credit?", "value": bool(m),
                     "unit": None, "formula": f"read from text, written {m['written_on']}, refers to {m.get('resolved_date')}" if m else "not stated",
                     "citations": [m["ref"]] if m else [], "kind": "extracted"})


FACT_BUILDERS: dict[str, Callable[..., tuple[list[dict], dict]]] = {
    "emi_collection": emi_facts,
    "subscription_renewal": subscription_facts,
}
