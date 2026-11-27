"""Bring your own data: CSV, Excel (.xlsx) or JSON / NDJSON, any column names.

Headers are matched to the pack's columns by synonyms, dates written DD/MM/YYYY are normalised to ISO, and every
row is validated. The upload returns a report (rows loaded, rows skipped with the reason, columns we did not
recognise, a preview) instead of failing silently. Pack-specific rules live in `RULES` and `fix_row`.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from typing import Any

from . import sample_data, store

SYNONYMS: dict[str, list[str]] = {
    "customer_id": ["customer_id", "cust_id", "customerid", "client_id", "user_id", "userid", "borrower_id", "account_id", "uid"],
    "name": ["name", "customer_name", "full_name", "user_name", "fullname"],
    "phone": ["phone", "mobile", "mobile_no", "mobile_number", "phone_number", "msisdn", "contact"],
    "preferred_language": ["preferred_language", "language", "lang"],
    "city": ["city", "town", "location"],
    "dob": ["dob", "date_of_birth", "birth_date", "birthdate"],
    "birth_time": ["birth_time", "time_of_birth", "tob"],
    "birth_place_name": ["birth_place_name", "birth_place", "place_of_birth", "pob", "birth_city"],
    "birth_latitude": ["birth_latitude", "lat", "latitude"],
    "birth_longitude": ["birth_longitude", "lon", "lng", "longitude"],
    "astro_consent_at": ["astro_consent_at", "consent_at", "consent_date", "astro_consent"],
    "loan_id": ["loan_id", "loan_no", "loan_number", "account_no"],
    "overdue_amount": ["overdue_amount", "overdue", "amount_overdue", "outstanding"],
    "days_past_due": ["days_past_due", "dpd"],
    "emi_amount": ["emi_amount", "emi", "instalment", "installment"],
    "collections_note": ["collections_note", "note", "notes", "remark", "remarks", "agent_note"],
    "amount": ["amount", "amt", "value", "paid_amount"],
    "paid_at": ["paid_at", "payment_date", "paid_on", "txn_date", "transaction_date"],
    "sent_at": ["sent_at", "sent_on", "timestamp", "time", "datetime"],
    "channel": ["channel", "medium", "mode"],
    "status": ["status", "delivery_status", "state"],
    "reply_text": ["reply_text", "reply", "message", "text_reply"],
    "text": ["text", "message_text", "question", "query"],
    "started_at": ["started_at", "session_start", "opened_at", "login_at"],
    "minutes": ["minutes", "duration", "duration_min", "mins"],
    "renews_on": ["renews_on", "renewal_date", "expiry", "expiry_date"],
    "plan": ["plan", "plan_name", "pack", "product_name"],
    "price": ["price", "plan_price", "mrp"],
    "event_name": ["event_name", "event", "event_type", "action"],
    "at": ["at", "event_time", "event_at", "created_at", "occurred_at"],
    "cta": ["cta", "cta_name", "button", "button_name"],
}

# Columns that hold dates / datetimes: normalised to ISO so the brain can read them.
DATE_HINT = re.compile(r"(^|_)(dob|date|at|on|renews|paid|sent|started|made)($|_)")

RULES: dict[str, dict[str, list[str]]] = {
    # source -> required columns (beyond customer_id)
    "customers": {"required": []},
    "loans": {"required": ["overdue_amount"]},
    "payments": {"required": ["amount", "paid_at"]},
    "promises": {"required": ["promised_date"]},
    "communications": {"required": ["channel", "sent_at"]},
    "subscriptions": {"required": ["renews_on"]},
    "usage": {"required": ["date"]},
    "sessions": {"required": ["started_at"]},
    "chats": {"required": ["at", "text"]},
    "purchases": {"required": ["at", "product"]},
    "events": {"required": ["at", "event_name"]},
}

DESCRIPTIONS = {
    "customers": "One row per person. The id ties every other file together.",
    "loans": "One row per loan: what is owed, how late, and the collector's note.",
    "payments": "Every payment received, with date and method.",
    "promises": "Promises to pay, with the promised date and whether they were kept.",
    "communications": "Every message or call sent (direction out) and every reply (direction in).",
    "subscriptions": "One row per subscription period, with the renewal date.",
    "usage": "Daily usage: minutes and what they watched or listened to.",
    "sessions": "App sessions: when, how long, which screen.",
    "chats": "What users asked astrologers, in their own words.",
    "purchases": "Every purchase: consult, puja, report.",
    "events": "In-app events: viewed_login, interacted_login, completed_login, viewed_screen, clicked_cta, viewed_payment_page or viewed_plans, started_payment or started_checkout, abandoned_payment or abandoned_checkout, completed_payment or completed_purchase.",
}


def _canon(key: str) -> str:
    k = re.sub(r"[^a-z0-9]+", "_", (key or "").strip().lower()).strip("_")
    for canon, alts in SYNONYMS.items():
        if k in alts:
            return canon
    return k


def _norm_date(v: Any) -> Any:
    if v is None or v == "":
        return v
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds") if (v.hour or v.minute or v.second) else v.date().isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            d = datetime.strptime(s[:19], fmt)
            return s if fmt == "%Y-%m-%d" else d.isoformat(timespec="seconds")
        except ValueError:
            pass
    for fmt, has_time in (("%d/%m/%Y", False), ("%d-%m-%Y", False), ("%d.%m.%Y", False), ("%d/%m/%Y %H:%M", True),
                          ("%d/%m/%Y %H:%M:%S", True), ("%d-%m-%Y %H:%M", True)):
        try:
            d = datetime.strptime(s, fmt)
            return d.isoformat(timespec="seconds") if has_time else d.date().isoformat()
        except ValueError:
            pass
    return s


def read_file(filename: str, raw: bytes) -> list[dict[str, Any]]:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        header = [str(h) if h is not None else "" for h in next(it, [])]
        return [dict(zip(header, row)) for row in it if any(c not in (None, "") for c in row)]
    text = raw.decode("utf-8-sig")
    if name.endswith(".json"):
        data = json.loads(text)
        return data if isinstance(data, list) else data.get("rows", [])
    if name.endswith((".ndjson", ".jsonl")):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def known_columns(source: str, pack_id: str) -> list[str]:
    gen = sample_data.DATASETS.get(pack_id)
    if not gen:
        return []
    rows = gen(n=12).get(source, [])
    cols: list[str] = []
    for r in rows:
        for k in r:
            if not k.startswith("_") and k not in cols:
                cols.append(k)
    return cols


def fix_row(source: str, r: dict[str, Any]) -> str | None:
    """Pack-specific clean-up. Return a reason to skip the row, or None."""
    if source == "events":
        if not r.get("at") and r.get("sent_at"):
            r["at"] = r.pop("sent_at")
        r["event_name"] = str(r.get("event_name") or "").strip().lower().replace(" ", "_")
    return None


def ingest(source: str, filename: str, raw: bytes, pack_id: str, mode: str = "append") -> dict[str, Any]:
    if source not in sample_data.ID_FIELDS:
        raise ValueError(f"source must be one of {sorted(sample_data.ID_FIELDS)}")
    rows_in = read_file(filename, raw)
    if not rows_in:
        raise ValueError("The file has no rows.")
    id_field = sample_data.ID_FIELDS[source]
    known = set(known_columns(source, pack_id)) | {id_field, "customer_id"}
    original = list(rows_in[0].keys())
    mapping = {h: _canon(h) for h in original}
    unknown = sorted({c for c in mapping.values() if c not in known})
    required = ["customer_id"] + RULES.get(source, {}).get("required", [])
    missing_cols = [c for c in required if c not in mapping.values()]
    if "customer_id" in missing_cols:
        raise ValueError(f"No customer id column found. Rename one of your columns to customer_id (seen: {', '.join(original)}).")

    good, skipped = [], []
    for i, raw_row in enumerate(rows_in, start=2):
        r = {mapping.get(k, _canon(k)): (v.strip() if isinstance(v, str) else v) for k, v in raw_row.items() if k is not None}
        for k in list(r):
            if DATE_HINT.search(k) or k in {"birth_time"}:
                r[k] = _norm_date(r[k]) if k != "birth_time" else (str(r[k])[:5] if r[k] not in (None, "") else None)
        if r.get("customer_id") in (None, ""):
            skipped.append({"row": i, "reason": "customer_id is empty"})
            continue
        r["customer_id"] = str(r["customer_id"]).strip()
        empty = [c for c in required if c != "customer_id" and r.get(c) in (None, "")]
        if empty:
            skipped.append({"row": i, "reason": f"missing {', '.join(empty)}"})
            continue
        reason = fix_row(source, r)
        if reason:
            skipped.append({"row": i, "reason": reason})
            continue
        r.setdefault(id_field, f"{source[:3].upper()}-{r['customer_id']}-{i}")
        good.append(r)

    if mode == "replace":
        with store.db() as conn:
            conn.execute("DELETE FROM records WHERE source=?", (source,))
    loaded = store.put_records(source, good, id_field, "customer_id") if good else 0
    return {
        "source": source, "file": filename, "mode": mode, "rows_in_file": len(rows_in), "loaded": loaded,
        "skipped": len(skipped), "skipped_rows": skipped[:50],
        "column_mapping": {k: v for k, v in mapping.items() if k != v}, "unrecognised_columns": unknown,
        "missing_required_columns": [c for c in missing_cols if c != "customer_id"],
        "preview": good[:3], "next": "Build brains and decide to see these rows in every brain.",
    }


def schema(pack_id: str, sources: list[str]) -> list[dict[str, Any]]:
    out = []
    for s in sources:
        cols = known_columns(s, pack_id)
        req = ["customer_id"] + RULES.get(s, {}).get("required", [])
        out.append({"source": s, "description": DESCRIPTIONS.get(s, ""), "id_field": sample_data.ID_FIELDS[s],
                    "required": req, "columns": cols, "rows_now": store.source_counts().get(s, 0)})
    return out


def template_csv(source: str, pack_id: str) -> str:
    rows = sample_data.DATASETS[pack_id](n=6).get(source, [])[:5]
    cols = known_columns(source, pack_id)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: v for k, v in r.items() if not k.startswith("_")})
    return buf.getvalue()
