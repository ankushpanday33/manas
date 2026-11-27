"""Goal packs: describe a business once, and every customer becomes a brain.

A pack declares the ontology (object types, link types, text columns read by extraction),
the beliefs the brain forms, what counts as converted, which channels and windows exist,
and the compliance rules that gate every send.
"""
from __future__ import annotations

from typing import Any

PACKS: dict[str, dict[str, Any]] = {
    "emi_collection": {
        "id": "emi_collection",
        "title": "EMI collection",
        "summary": "Recover overdue instalments: who pays on their own, who needs a nudge, who needs a call or a plan.",
        "objects": {
            "Customer": {"source": "customers", "id": "customer_id",
                          "fields": ["preferred_language", "city", "consent_whatsapp", "consent_sms", "consent_voice", "dnd"]},
            "Loan": {"source": "loans", "id": "loan_id",
                     "fields": ["emi_amount", "overdue_amount", "days_past_due", "collections_note", "note_date"]},
            "Payment": {"source": "payments", "id": "payment_id", "fields": ["amount", "paid_at", "method", "on_time"]},
            "PromiseToPay": {"source": "promises", "id": "promise_id",
                             "fields": ["promised_amount", "promised_date", "made_on", "status"]},
            "Communication": {"source": "communications", "id": "comm_id",
                              "fields": ["channel", "sent_at", "status", "direction", "reply_text"]},
            "Event": {"source": "events", "id": "event_id", "fields": ["at", "event_name", "screen", "cta"]},
        },
        "links": [
            {"from": "Loan", "type": "borrowed_by", "to": "Customer", "on": "loans.customer_id"},
            {"from": "Payment", "type": "repays", "to": "Loan", "on": "payments.loan_id"},
            {"from": "PromiseToPay", "type": "promised_on", "to": "Loan", "on": "promises.loan_id"},
            {"from": "Communication", "type": "sent_to", "to": "Customer", "on": "communications.customer_id"},
            {"from": "Event", "type": "did", "to": "Customer", "on": "events.customer_id"},
            {"from": "Customer", "type": "disputes", "to": "Loan", "on": "read from text"},
        ],
        "text_columns": ["loans.collections_note (dated by note_date)", "communications.reply_text (dated by sent_at)"],
        "beliefs": ["willingness_to_pay", "ability_to_pay", "reachability", "escalation_risk"],
        "conversion": "payment received against an overdue instalment within 7 days",
        "channels": ["whatsapp", "sms", "voice"],
        # RBI Fair Practices Code: recovery contact only between 08:00 and 19:00.
        "windows": {"morning": (8, 12), "afternoon": (12, 17), "evening": (17, 19)},
        "quiet_hours_note": "RBI fair practice code: recovery contact only 08:00 to 19:00",
        "tones": ["gentle", "firm", "empathetic_plan"],
        "frequency_cap": {"per_day": 1, "per_week": 3},
        "templates": {
            "gentle": "Namaste {name}, your EMI of {amount} is pending. Pay securely here: {link}",
            "firm": "{name}, your EMI of {amount} is {dpd} days overdue. Please pay today to avoid charges: {link}",
            "empathetic_plan": "{name}, we understand delays happen. Pay {amount} after your salary credit, or pick a plan that suits you: {link}",
        },
    },
    "subscription_renewal": {
        "id": "subscription_renewal",
        "title": "Subscription renewal",
        "summary": "Renew before customers lapse: who renews on their own, who needs a reason, who needs an offer.",
        "objects": {
            "Customer": {"source": "customers", "id": "customer_id",
                          "fields": ["preferred_language", "city", "consent_whatsapp", "consent_sms", "consent_voice", "dnd"]},
            "Subscription": {"source": "subscriptions", "id": "sub_id",
                             "fields": ["plan", "price", "renews_on", "auto_renew", "status"]},
            "Usage": {"source": "usage", "id": "usage_id", "fields": ["date", "minutes", "content_type"]},
            "Communication": {"source": "communications", "id": "comm_id",
                              "fields": ["channel", "sent_at", "status", "direction", "reply_text"]},
            "Event": {"source": "events", "id": "event_id", "fields": ["at", "event_name", "screen", "cta"]},
        },
        "links": [
            {"from": "Subscription", "type": "held_by", "to": "Customer", "on": "subscriptions.customer_id"},
            {"from": "Usage", "type": "consumed_by", "to": "Customer", "on": "usage.customer_id"},
            {"from": "Communication", "type": "sent_to", "to": "Customer", "on": "communications.customer_id"},
            {"from": "Event", "type": "did", "to": "Customer", "on": "events.customer_id"},
        ],
        "text_columns": ["communications.reply_text (dated by sent_at)"],
        "beliefs": ["renewal_intent", "engagement", "price_sensitivity", "reachability"],
        "conversion": "subscription renewed on or before the renewal date",
        "channels": ["whatsapp", "sms", "push"],
        "windows": {"morning": (9, 12), "afternoon": (12, 18), "evening": (18, 21)},
        "quiet_hours_note": "No promotional messages outside 09:00 to 21:00",
        "tones": ["reminder", "value_recap", "offer"],
        "frequency_cap": {"per_day": 1, "per_week": 3},
        "templates": {
            "reminder": "Hi {name}, your {plan} plan renews on {date}. Keep enjoying without a break: {link}",
            "value_recap": "{name}, you enjoyed {minutes} minutes of {top_content} this month. Renew {plan} to keep it going: {link}",
            "offer": "{name}, renew {plan} today and get an extra month free. Offer ends {date}: {link}",
        },
    },
}


def get_pack(pack_id: str) -> dict[str, Any]:
    if pack_id not in PACKS:
        raise KeyError(f"Unknown pack: {pack_id}")
    return PACKS[pack_id]


def pack_summaries() -> list[dict[str, Any]]:
    return [
        {
            "id": p["id"], "title": p["title"], "summary": p["summary"],
            "objects": list(p["objects"].keys()), "links": p["links"],
            "beliefs": p["beliefs"], "conversion": p["conversion"], "channels": p["channels"],
            "text_columns": p["text_columns"], "quiet_hours_note": p["quiet_hours_note"],
        }
        for p in PACKS.values()
    ]
