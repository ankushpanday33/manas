"""Predictions from in-app events and app signals. Transparent by design: a logistic score over named features,
weights in config, and every prediction returns the drivers that moved it (no black box).

  purchase_propensity_7d  - chance of a purchase in the next 7 days
  churn_risk_14d          - chance the user goes quiet for 14 days
  login_completion        - chance a user who opens login finishes it

With fewer than MIN_EVENTS events in 30 days a prediction returns insufficient_evidence instead of a number.
Payment-flavoured names (viewed_payment_page, started_payment, abandoned_payment, completed_payment) are treated as the
same funnel steps as viewed_paywall, started_checkout, abandoned_checkout and completed_purchase.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

MIN_EVENTS = 6
RULE_VERSION = "events-1.0"

# feature -> weight (log-odds). Bias sets the base rate.
PURCHASE_WEIGHTS = {"bias": -2.4, "cta_clicks_7d": 0.35, "paywall_views_7d": 0.30, "abandoned_checkout_14d": 0.9,
                    "purchases_90d": 0.45, "active_days_7d": 0.18, "login_completed": 0.4, "competitor_astro_app": 0.35,
                    "life_event_app": 0.45, "days_since_last_event": -0.08}
CHURN_WEIGHTS = {"bias": -1.2, "days_since_last_event": 0.16, "active_days_7d": -0.35, "events_trend_down": 0.9,
                 "login_dropoff": 0.6, "purchases_90d": -0.3}
LOGIN_WEIGHTS = {"bias": 0.6, "login_attempts_30d": 0.15, "login_dropoffs_30d": -0.5, "active_days_7d": 0.15}


def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _score(weights: dict[str, float], feats: dict[str, float]) -> tuple[float, list[dict[str, Any]]]:
    z = weights["bias"]
    drivers = []
    for k, w in weights.items():
        if k == "bias":
            continue
        contrib = w * feats.get(k, 0)
        z += contrib
        if abs(contrib) >= 0.05:
            drivers.append({"feature": k, "value": feats.get(k, 0), "weight": w, "effect": round(contrib, 2)})
    drivers.sort(key=lambda d: -abs(d["effect"]))
    return round(_sig(z), 3), drivers


def _d(v: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v)[:19]) if v else None
    except ValueError:
        return None


ALIASES = {"viewed_payment_page": "viewed_paywall", "viewed_plans": "viewed_paywall", "started_payment": "started_checkout",
           "abandoned_payment": "abandoned_checkout", "completed_payment": "completed_purchase", "renewed": "completed_purchase"}


def event_features(events: list[dict[str, Any]], today: date) -> dict[str, Any]:
    now = datetime.combine(today, datetime.min.time())
    ev = sorted(({**e, "event_name": ALIASES.get(e.get("event_name", ""), e.get("event_name", ""))} for e in events if _d(e.get("at"))),
                key=lambda e: e["at"])
    last30 = [e for e in ev if _d(e["at"]) >= now - timedelta(days=30)]
    last7 = [e for e in ev if _d(e["at"]) >= now - timedelta(days=7)]
    prev7 = [e for e in ev if now - timedelta(days=14) <= _d(e["at"]) < now - timedelta(days=7)]
    names7, names30 = Counter(e["event_name"] for e in last7), Counter(e["event_name"] for e in last30)
    ab14 = [e for e in ev if e["event_name"] == "abandoned_checkout" and _d(e["at"]) >= now - timedelta(days=14)]
    bought_after = {e.get("cta") for e in ev if e["event_name"] == "completed_purchase"}
    open_abandoned = [e for e in ab14 if e.get("cta") not in bought_after]
    logins_v, logins_done = names30.get("viewed_login", 0), names30.get("completed_login", 0)
    ctas = Counter(e.get("cta") for e in last30 if e["event_name"] == "clicked_cta" and e.get("cta"))
    screens = Counter(e.get("screen") for e in last30 if e["event_name"] == "viewed_screen" and e.get("screen"))
    return {
        "events_30d": len(last30), "events_7d": len(last7),
        "active_days_7d": len({e["at"][:10] for e in last7}),
        "cta_clicks_7d": names7.get("clicked_cta", 0), "paywall_views_7d": names7.get("viewed_paywall", 0),
        "abandoned_checkout_14d": min(len(open_abandoned), 3),
        "abandoned_item": open_abandoned[-1].get("cta") if open_abandoned else None,
        "login_attempts_30d": logins_v, "login_completed": 1 if logins_done else 0,
        "login_dropoffs_30d": max(logins_v - logins_done, 0), "login_dropoff": 1 if logins_v > logins_done else 0,
        "days_since_last_event": (now - _d(ev[-1]["at"])).days if ev else 30,
        "events_trend_down": 1 if prev7 and len(last7) < 0.5 * len(prev7) else 0,
        "top_cta": ctas.most_common(1)[0][0] if ctas else None,
        "top_screen": screens.most_common(1)[0][0] if screens else None,
        "rows": [e["_row_id"] for e in last30][:40],
    }


def predict(events: list[dict[str, Any]], app_signals: dict[str, Any], purchases_90d: int, today: date) -> dict[str, Any]:
    f = event_features(events, today)
    feats = {**f, "purchases_90d": min(purchases_90d, 4),
             "competitor_astro_app": 1 if "astro_competitor" in app_signals.get("personalise", []) else 0,
             "life_event_app": 1 if set(app_signals.get("personalise", [])) & {"matrimony", "jobs", "education"} else 0}
    out: dict[str, Any] = {"rule_version": RULE_VERSION, "features": {k: v for k, v in feats.items() if k != "rows"}, "rows": f["rows"]}
    if f["events_30d"] < MIN_EVENTS:
        status = {"status": "insufficient_evidence", "value": None, "drivers": [],
                  "note": f"only {f['events_30d']} events in 30 days; at least {MIN_EVENTS} needed"}
        out.update(purchase_propensity_7d=dict(status), churn_risk_14d=dict(status), login_completion=dict(status))
        return out
    p, d = _score(PURCHASE_WEIGHTS, feats)
    if app_signals.get("protect"):
        d.insert(0, {"feature": "protect_only_apps", "value": ", ".join(app_signals["protect"]), "weight": 0, "effect": 0,
                     "note": "never raises the prediction; it switches off paid offers instead"})
    c, dc = _score(CHURN_WEIGHTS, feats)
    l, dl = _score(LOGIN_WEIGHTS, feats)
    out["purchase_propensity_7d"] = {"status": "ok", "value": p, "drivers": d[:6]}
    out["churn_risk_14d"] = {"status": "ok", "value": c, "drivers": dc[:5]}
    out["login_completion"] = {"status": "ok" if f["login_attempts_30d"] else "insufficient_evidence",
                               "value": l if f["login_attempts_30d"] else None, "drivers": dl[:4]}
    return out
