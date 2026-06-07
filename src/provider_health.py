"""Provider health + quota-exhaustion tracking.

The LLM + vision layers fall back across ~8 providers, so a single provider
running out of quota is invisible to the user — the run silently uses the next
one. This module records those events so the owner can SEE, on the diagnostics
page, the moment a provider's quota runs out (and which model), plus the last
time each provider answered successfully.

In-memory + process-local (same lifetime as the _EXHAUSTED sets it sits next
to). Railway restarts reset it; that's acceptable for a *liveness* signal —
it's the honest "is it working right now" answer without standing up new infra.
If we ever want durable history we'd persist to Supabase.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict

_LOCK = threading.Lock()
_MAX_EVENTS = 200
_EVENTS: Deque[dict] = deque(maxlen=_MAX_EVENTS)
# Per-provider rolling summary, keyed by lowercased provider name.
_SUMMARY: Dict[str, dict] = {}

_VALID_KINDS = ("ok", "quota", "error")


def record_event(provider: str, model: str, kind: str, reason: str = "") -> None:
    """Record one provider call outcome.

    kind:
      'ok'    — the provider answered successfully
      'quota' — rate-limit / quota / 429 / resource-exhausted / overloaded
      'error' — any other failure (bad key, network, malformed response)
    """
    if kind not in _VALID_KINDS:
        kind = "error"
    provider = (provider or "unknown").lower()
    model = model or ""
    ts = time.time()
    ev = {"ts": ts, "provider": provider, "model": model,
          "kind": kind, "reason": (reason or "")[:240]}
    with _LOCK:
        _EVENTS.append(ev)
        s = _SUMMARY.setdefault(provider, {
            "provider": provider,
            "last_ok_ts": None,
            "last_error_ts": None,
            "last_error_kind": None,
            "last_error_reason": "",
            "ok_count": 0,
            "quota_count": 0,
            "error_count": 0,
            "exhausted_models": [],
        })
        if kind == "ok":
            s["last_ok_ts"] = ts
            s["ok_count"] += 1
            # A fresh success clears the "currently exhausted" flag for that
            # model (quota windows reset) so the dashboard doesn't show a stale
            # red once the provider recovers.
            if model and model in s["exhausted_models"]:
                s["exhausted_models"].remove(model)
        elif kind == "quota":
            s["last_error_ts"] = ts
            s["last_error_kind"] = "quota"
            s["last_error_reason"] = ev["reason"]
            s["quota_count"] += 1
            if model and model not in s["exhausted_models"]:
                s["exhausted_models"].append(model)
        else:
            s["last_error_ts"] = ts
            s["last_error_kind"] = "error"
            s["last_error_reason"] = ev["reason"]
            s["error_count"] += 1


def record_ok(provider: str, model: str = "") -> None:
    record_event(provider, model, "ok")


def record_quota(provider: str, model: str, reason: str = "") -> None:
    record_event(provider, model, "quota", reason)


def record_error(provider: str, model: str, reason: str = "") -> None:
    record_event(provider, model, "error", reason)


def snapshot(limit: int = 60) -> dict:
    """Return recent events (most-recent-first) + the per-provider summary."""
    with _LOCK:
        events = list(_EVENTS)[-limit:][::-1]
        summary = {k: dict(v) for k, v in _SUMMARY.items()}
    return {"events": events, "summary": summary, "now": time.time()}


def reset() -> None:
    with _LOCK:
        _EVENTS.clear()
        _SUMMARY.clear()
