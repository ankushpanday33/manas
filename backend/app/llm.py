"""Thin Claude wrapper.

The engine works fully without a model (deterministic rules). When credentials exist, Claude is used for:
note extraction, belief review, persona narrative, twin role-play, the council, and Ask.
Every call returns schema-validated JSON (structured outputs), and nothing personal is sent:
callers must pass text through privacy.pseudonymise first.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger("manas.llm")

MODEL = os.environ.get("MANAS_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("MANAS_EFFORT", "medium")

_client = None
_disabled_reason: str | None = None


def _has_credentials() -> bool:
    if os.environ.get("MANAS_LLM", "").lower() in {"0", "off", "false"}:
        return False
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("MANAS_LLM", "").lower() in {"1", "on", "true"}
    )


def enabled() -> bool:
    return _disabled_reason is None and _has_credentials()


def status() -> dict[str, Any]:
    return {"enabled": enabled(), "model": MODEL if enabled() else None,
            "reason": _disabled_reason or (None if _has_credentials() else "no credentials: running on deterministic rules")}


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def _strict(schema: dict[str, Any]) -> dict[str, Any]:
    """Structured outputs need additionalProperties: false and every property required, recursively."""
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        schema["additionalProperties"] = False
        schema["required"] = list(props.keys())
        for v in props.values():
            _strict(v)
    elif schema.get("type") == "array" and isinstance(schema.get("items"), dict):
        _strict(schema["items"])
    return schema


def ask_json(system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 4000) -> dict[str, Any] | None:
    """Return parsed JSON matching `schema`, or None when the model is off, refuses, or errors.

    Callers always have a deterministic fallback, so a None here never breaks a decision.
    """
    global _disabled_reason
    if not enabled():
        return None
    import anthropic

    try:
        response = _get_client().beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": _strict(json.loads(json.dumps(schema)))}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        _disabled_reason = "authentication failed: check ANTHROPIC_API_KEY"
        log.warning(_disabled_reason)
        return None
    except anthropic.PermissionDeniedError:
        _disabled_reason = "API key lacks permission for this model"
        log.warning(_disabled_reason)
        return None
    except anthropic.RateLimitError:
        log.warning("rate limited; falling back to rules for this call")
        return None
    except anthropic.APIStatusError as e:
        log.warning("Claude API error %s; falling back to rules", e.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("network error reaching Claude; falling back to rules")
        return None

    if response.stop_reason in {"refusal", "max_tokens"}:
        log.warning("model stopped with %s; falling back to rules", response.stop_reason)
        return None
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("model returned invalid JSON; falling back to rules")
        return None
