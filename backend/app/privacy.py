"""Pseudonymisation: the model never sees a name, phone number or email.

Swap in Microsoft Presidio for production-grade PII detection (Aadhaar, PAN, addresses).
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
AADHAAR = re.compile(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)")


def alias(customer_id: str) -> str:
    return "C-" + hashlib.sha256(customer_id.encode()).hexdigest()[:6]


def scrub_text(text: str, names: list[str] | None = None) -> str:
    if not text:
        return text
    out = EMAIL.sub("[email]", text)
    out = PAN.sub("[pan]", out)
    out = AADHAAR.sub("[aadhaar]", out)
    out = PHONE.sub("[phone]", out)
    for name in names or []:
        for part in {name, *name.split()}:
            if len(part) > 2:
                out = re.sub(re.escape(part), "[name]", out, flags=re.IGNORECASE)
    return out


def pseudonymise(obj: Any, names: list[str]) -> Any:
    """Recursively scrub a JSON-like structure. Keys named like PII are dropped outright."""
    if isinstance(obj, dict):
        return {k: pseudonymise(v, names) for k, v in obj.items() if k not in {"name", "phone", "email"}}
    if isinstance(obj, list):
        return [pseudonymise(v, names) for v in obj]
    if isinstance(obj, str):
        return scrub_text(obj, names)
    return obj
