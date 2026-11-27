"""Episodic memory: free text read in time.

"Tomorrow" means the day after the note was written, not the day we read it. Every signal keeps a
pointer to the exact row and the date it was written, so it can be cited later.
Works in English, Hindi (romanised) and Hinglish out of the box; Claude extends it when enabled.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .. import llm, privacy

KINDS = ["promise", "salary_dependent", "hardship", "dispute", "time_preference", "contact_objection", "channel_preference"]

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("dispute", re.compile(r"wrong charge|dispute|galat|fraud|not my loan|mera loan nahi|already paid|pehle hi (?:de|pay)", re.I)),
    ("hardship", re.compile(r"job (?:lost|gone)|naukri (?:chali|gayi)|hospital|medical|bimar|layoff|no income", re.I)),
    ("salary_dependent", re.compile(r"salary|tankhwah|payday|vetan", re.I)),
    ("contact_objection", re.compile(r"(?:don'?t|do not|mat) (?:call|karo call)|stop (?:calling|messag)|call mat", re.I)),
    ("promise", re.compile(r"will pay|pay (?:kar\s*dunga|karunga|kar\s*dungi|karungi)|de dunga|de dungi|paying (?:on|by)|i'?ll pay", re.I)),
]
_TIME_PREF = re.compile(r"(?:after|ke baad)\s*(\d{1,2})\s*(?:pm|baje)|(evening|shaam|night|raat)|(morning|subah)", re.I)
_CHANNEL_PREF = re.compile(r"(whatsapp|sms|call|email)\s*(?:pe|par|on)?\s*(?:message|msg|bhejo|karo|only|please)", re.I)


def _resolve_date(text: str, written: date) -> date | None:
    t = text.lower()
    if re.search(r"day after tomorrow|parso|parson", t):
        return written + timedelta(days=2)
    if re.search(r"tomorrow|\bkal\b", t):
        return written + timedelta(days=1)
    if re.search(r"next week|agle hafte|agle week", t):
        return written + timedelta(days=7)
    if re.search(r"next month|agle mahine", t):
        nm = (written.replace(day=1) + timedelta(days=32)).replace(day=1)
        return nm
    m = re.search(r"(?:after|by|on)\s+(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\b|(\d{1,2})(?:st|nd|rd|th)?\s*(?:tarikh|tareekh|ke baad)", t)
    if m:
        day = int(m.group(1) or m.group(2))
        if 1 <= day <= 31:
            candidate = written.replace(day=min(day, 28))
            if candidate <= written:
                candidate = (written.replace(day=1) + timedelta(days=32)).replace(day=min(day, 28))
            return candidate
    return None


def _rule_signals(text: str, written: date, ref: dict[str, str]) -> list[dict[str, Any]]:
    signals = []
    for kind, pattern in _RULES:
        if pattern.search(text):
            resolved = _resolve_date(text, written) if kind in {"promise", "salary_dependent"} else None
            signals.append({"kind": kind, "resolved_date": resolved.isoformat() if resolved else None,
                            "detail": None, "written_on": written.isoformat(), "ref": ref, "method": "rules"})
    m = _TIME_PREF.search(text)
    if m:
        if m.group(1):
            hour = int(m.group(1))
            detail = f"after {hour + 12 if hour < 12 else hour}:00"
        elif m.group(2):
            detail = "evening"
        else:
            detail = "morning"
        signals.append({"kind": "time_preference", "resolved_date": None, "detail": detail,
                        "written_on": written.isoformat(), "ref": ref, "method": "rules"})
    c = _CHANNEL_PREF.search(text)
    if c:
        signals.append({"kind": "channel_preference", "resolved_date": None, "detail": c.group(1).lower(),
                        "written_on": written.isoformat(), "ref": ref, "method": "rules"})
    return signals


_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "signals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text_index": {"type": "integer"},
                    "kind": {"type": "string", "enum": KINDS},
                    "resolved_date": {"type": ["string", "null"], "description": "ISO date the text refers to, resolved against the date it was written, or null"},
                    "detail": {"type": ["string", "null"]},
                },
            },
        }
    },
}

_LLM_SYSTEM = (
    "You read short customer notes and replies from Indian lending and subscription businesses, in English, Hindi, "
    "Hinglish and other Indian languages. Extract only signals that are explicitly present. Resolve relative dates "
    "(kal, tomorrow, after the 5th, next week) against the date each text was written, never today's date. "
    "If a text has no signal, return nothing for it."
)


def read_texts(texts: list[dict[str, Any]], names: list[str]) -> list[dict[str, Any]]:
    """texts: [{text, written_on (date), ref:{source,row_id}}] -> memory signals."""
    signals: list[dict[str, Any]] = []
    for t in texts:
        signals.extend(_rule_signals(t["text"], t["written_on"], t["ref"]))

    if llm.enabled() and texts:
        listing = "\n".join(
            f"[{i}] written {t['written_on'].isoformat()}: {privacy.scrub_text(t['text'], names)}" for i, t in enumerate(texts)
        )
        result = llm.ask_json(_LLM_SYSTEM, f"Texts:\n{listing}", _LLM_SCHEMA, max_tokens=2000)
        if result:
            llm_signals = []
            for s in result.get("signals", []):
                idx = s.get("text_index")
                if not isinstance(idx, int) or not 0 <= idx < len(texts):
                    continue
                t = texts[idx]
                llm_signals.append({"kind": s["kind"], "resolved_date": s.get("resolved_date"), "detail": s.get("detail"),
                                    "written_on": t["written_on"].isoformat(), "ref": t["ref"], "method": "llm"})
            # Model and rules must agree on kind+row to keep the rules' copy; the model adds what rules missed.
            seen = {(s["kind"], s["ref"]["row_id"]) for s in signals}
            signals.extend(s for s in llm_signals if (s["kind"], s["ref"]["row_id"]) not in seen)

    for i, s in enumerate(signals):
        s["id"] = f"mem_{i + 1}"
    signals.sort(key=lambda s: s["written_on"])
    return signals
