"""Lightweight LLM text-completion helper with multi-provider fallback.

Providers, in auto-selection order: Claude > OpenAI > Gemini > Groq > heuristic.
Within Gemini, we rotate across multiple model IDs because each has a
separate 20-RPD free-tier quota. The chain converts a single-model brick
wall into a graceful soft-degradation.

Callers always get a deterministic, JSON-clean response or a ``None``
(signalling that they must fall back to a heuristic).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path

_LOG = logging.getLogger("llm")
# Module-level holder so the operator (or a debug endpoint) can introspect
# the most recent provider failure. Caller-facing flow still returns None on
# error so heuristics kick in — this is just for diagnostics.
LAST_ERROR: dict | None = None
# Track which (provider, model) combos hit a quota wall this session so we
# don't keep wasting wall-clock retrying them.
_EXHAUSTED: set[tuple[str, str]] = set()
# Per-process response cache for parse-company / match-audience etc. so the
# same description doesn't burn N Gemini calls when N variants run in
# parallel or the user re-parses on the company page.
_RESPONSE_CACHE: dict[str, str] = {}
_CACHE_MAX = 256

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import (  # noqa: E402
    CLAUDE_MODEL, GEMINI_TEXT_CHAIN, GROQ_TEXT_MODEL,
    MISTRAL_BASE_URL, MISTRAL_TEXT_MODEL,
    OPENAI_MODEL, OPENROUTER_BASE_URL, OPENROUTER_TEXT_MODEL,
    PROJECT_ROOT, TOGETHER_BASE_URL, TOGETHER_TEXT_MODEL,
    XAI_BASE_URL, XAI_TEXT_MODEL,
)

# Provider-health telemetry: record quota/ok events so the diagnostics page can
# surface the moment a provider runs out. Defensive — telemetry must never break
# the LLM path, hence the no-op fallbacks.
try:
    try:
        from src.provider_health import (  # noqa: E402
            record_ok as _ph_ok, record_quota as _ph_quota,
            record_error as _ph_error)
    except ImportError:
        from provider_health import (  # noqa: E402
            record_ok as _ph_ok, record_quota as _ph_quota,
            record_error as _ph_error)
except Exception:  # pragma: no cover
    def _ph_ok(*a, **k): pass
    def _ph_quota(*a, **k): pass
    def _ph_error(*a, **k): pass

__all__ = ["text_complete", "extract_json", "have_any_key"]


# ---------------------------------------------------------------------------
# Environment / keys
# ---------------------------------------------------------------------------

def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass


def _get_key(name: str) -> str | None:
    _load_env()
    return os.environ.get(name) or None


_ALL_KEY_ENVS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
    "GROQ_API_KEY", "MISTRAL_API_KEY", "OPENROUTER_API_KEY",
    "XAI_API_KEY", "TOGETHER_API_KEY",
)


def have_any_key() -> bool:
    return any(_get_key(k) for k in _ALL_KEY_ENVS)


def _select_provider(provider: str) -> str:
    """Resolve 'auto' → the strongest available provider with a key."""
    if provider != "auto":
        return provider
    # Quality-then-quota order: paid (Claude, OpenAI) → top free-tier
    # (Gemini, Groq) → other free providers in order of typical reliability.
    for name, env in (
        ("claude", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("gemini", "GEMINI_API_KEY"),
        ("groq", "GROQ_API_KEY"),
        ("mistral", "MISTRAL_API_KEY"),
        ("openrouter", "OPENROUTER_API_KEY"),
        ("xai", "XAI_API_KEY"),
        ("together", "TOGETHER_API_KEY"),
    ):
        if _get_key(env):
            return name
    return "none"


def _is_quota_error(exc: Exception) -> bool:
    """True if the exception text indicates rate-limit / quota / temporary
    unavailability — these are the cases worth falling forward through the
    chain."""
    msg = str(exc).lower()
    return any(s in msg for s in (
        "429", "resource_exhausted", "quota", "rate limit", "rate_limit",
        "503", "unavailable", "overloaded",
        # Retired/unknown model ids (Google 404s models per-account as it
        # deprecates them) — fall forward through the chain instead of
        # failing the whole request on one dead id.
        "404", "not_found", "not found", "no longer available",
    ))


# ---------------------------------------------------------------------------
# Provider call adapters — each returns text or raises
# ---------------------------------------------------------------------------

def _call_claude(prompt: str, system: str, max_tokens: int,
                 json_mode: bool) -> str | None:
    try:
        import anthropic
    except ImportError:
        return None
    key = _get_key("ANTHROPIC_API_KEY")
    if not key:
        return None
    client = anthropic.Anthropic(api_key=key)
    messages = [{"role": "user", "content": prompt}]
    if json_mode:
        messages.append({"role": "assistant", "content": "{"})
    msg = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=max_tokens,
        system=system or "You are a helpful, concise analyst.",
        messages=messages,
    )
    text = "".join(b.text for b in msg.content
                   if getattr(b, "type", None) == "text")
    return ("{" + text) if json_mode else text


def _call_openai(prompt: str, system: str, max_tokens: int,
                 json_mode: bool) -> str | None:
    try:
        from openai import OpenAI
    except ImportError:
        return None
    key = _get_key("OPENAI_API_KEY")
    if not key:
        return None
    client = OpenAI(api_key=key)
    kwargs: dict = {
        "model": OPENAI_MODEL, "max_tokens": max_tokens,
        "messages": [
            {"role": "system",
             "content": system or "You are a helpful, concise analyst."},
            {"role": "user", "content": prompt},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content


def _call_gemini_model(model: str, prompt: str, system: str,
                       max_tokens: int, json_mode: bool) -> str | None:
    """Call a specific Gemini model. Returns text or raises on failure."""
    from google import genai
    from google.genai import types as gtypes
    key = _get_key("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    client = genai.Client(api_key=key)
    config = gtypes.GenerateContentConfig(
        system_instruction=system or "You are a helpful, concise analyst.",
        max_output_tokens=max(max_tokens, 200),
        thinking_config=gtypes.ThinkingConfig(thinking_budget=0),
        response_mime_type="application/json" if json_mode else "text/plain",
    )
    resp = client.models.generate_content(
        model=model, contents=prompt, config=config,
    )
    return resp.text


def _call_gemini(prompt: str, system: str, max_tokens: int,
                 json_mode: bool) -> str | None:
    """Try each Gemini model in the chain until one returns text. Each has
    its own daily quota so this multiplies the effective free budget."""
    try:
        import google.genai  # noqa: F401
    except ImportError:
        return None
    last_exc: Exception | None = None
    for model in GEMINI_TEXT_CHAIN:
        if ("gemini", model) in _EXHAUSTED:
            continue
        try:
            out = _call_gemini_model(model, prompt, system, max_tokens,
                                      json_mode)
            if out:
                return out
            # Empty text — model might've eaten budget on thinking. Try next.
            _LOG.warning("gemini model %s returned empty text", model)
        except Exception as exc:                      # noqa: BLE001
            last_exc = exc
            if _is_quota_error(exc):
                _LOG.warning("gemini model %s quota exhausted: %s",
                              model, str(exc)[:160])
                _EXHAUSTED.add(("gemini", model))
                _ph_quota("gemini", model, str(exc)[:160])
                continue
            # Non-quota error (auth/network) — don't burn through all models
            raise
    if last_exc is not None:
        raise last_exc
    return None


def _call_groq(prompt: str, system: str, max_tokens: int,
               json_mode: bool) -> str | None:
    try:
        from groq import Groq
    except ImportError:
        return None
    key = _get_key("GROQ_API_KEY")
    if not key:
        return None
    client = Groq(api_key=key)
    kwargs: dict = {
        "model": GROQ_TEXT_MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system",
             "content": system or "You are a helpful, concise analyst."},
            {"role": "user", "content": prompt},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content


def _call_openai_compat(env_key: str, base_url: str, model: str,
                         prompt: str, system: str, max_tokens: int,
                         json_mode: bool) -> str | None:
    """Generic adapter for OpenAI-compatible providers (Mistral / OpenRouter
    / xAI / Together). All four expose the same /chat/completions schema, so
    one body of code drives all four — only the base_url and model differ.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return None
    key = _get_key(env_key)
    if not key:
        return None
    client = OpenAI(api_key=key, base_url=base_url)
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system",
             "content": system or "You are a helpful, concise analyst."},
            {"role": "user", "content": prompt},
        ],
    }
    if json_mode:
        # Not every compatible provider supports response_format; if they
        # don't, the call still works because the system prompt asks for
        # JSON. Pass it if Mistral/OpenRouter/xAI; some Together models 422.
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content


def _call_mistral(prompt, system, max_tokens, json_mode):
    return _call_openai_compat(
        "MISTRAL_API_KEY", MISTRAL_BASE_URL, MISTRAL_TEXT_MODEL,
        prompt, system, max_tokens, json_mode)


def _call_openrouter(prompt, system, max_tokens, json_mode):
    return _call_openai_compat(
        "OPENROUTER_API_KEY", OPENROUTER_BASE_URL, OPENROUTER_TEXT_MODEL,
        prompt, system, max_tokens, json_mode)


def _call_xai(prompt, system, max_tokens, json_mode):
    return _call_openai_compat(
        "XAI_API_KEY", XAI_BASE_URL, XAI_TEXT_MODEL,
        prompt, system, max_tokens, json_mode)


def _call_together(prompt, system, max_tokens, json_mode):
    # Together's free models 422 on response_format=json_object; the system
    # prompt + JSON-extraction at the call site handles parsing.
    return _call_openai_compat(
        "TOGETHER_API_KEY", TOGETHER_BASE_URL, TOGETHER_TEXT_MODEL,
        prompt, system, max_tokens, json_mode=False)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_key(prompt: str, system: str, json_mode: bool) -> str:
    h = hashlib.sha1()
    h.update(prompt.encode("utf-8", errors="ignore"))
    h.update(b"\x00")
    h.update((system or "").encode("utf-8", errors="ignore"))
    h.update(b"|json" if json_mode else b"|text")
    return h.hexdigest()


def _cache_get(key: str) -> str | None:
    return _RESPONSE_CACHE.get(key)


def _cache_put(key: str, value: str) -> None:
    if len(_RESPONSE_CACHE) >= _CACHE_MAX:
        # Drop oldest (dict insertion order in CPython 3.7+).
        oldest = next(iter(_RESPONSE_CACHE))
        _RESPONSE_CACHE.pop(oldest, None)
    _RESPONSE_CACHE[key] = value


# ---------------------------------------------------------------------------
# Public entry point — provider chain + cache
# ---------------------------------------------------------------------------

# Order to attempt providers when one fails with a quota error. We start
# with whatever `_select_provider` chose, then walk this chain. Heuristic
# is reached only when every key-bearing provider fails.
_PROVIDER_FALLBACK = (
    "claude", "openai", "gemini", "groq",
    "mistral", "openrouter", "xai", "together",
)

_PROVIDER_KEY_ENV = {
    "claude":     "ANTHROPIC_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "gemini":     "GEMINI_API_KEY",
    "groq":       "GROQ_API_KEY",
    "mistral":    "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "xai":        "XAI_API_KEY",
    "together":   "TOGETHER_API_KEY",
}


def _try_provider(name: str, prompt: str, system: str,
                  max_tokens: int, json_mode: bool) -> str | None:
    dispatch = {
        "claude":     _call_claude,
        "openai":     _call_openai,
        "gemini":     _call_gemini,
        "groq":       _call_groq,
        "mistral":    _call_mistral,
        "openrouter": _call_openrouter,
        "xai":        _call_xai,
        "together":   _call_together,
    }
    fn = dispatch.get(name)
    if fn is None:
        return None
    return fn(prompt, system, max_tokens, json_mode)


def text_complete(prompt: str,
                  system: str = "",
                  max_tokens: int = 600,
                  json_mode: bool = False,
                  provider: str = "auto",
                  use_cache: bool = True) -> str | None:
    """Return the model's text completion, or None if every provider is
    unavailable/exhausted.

    Provider order: explicit ``provider`` arg wins; otherwise auto = the
    strongest provider that has a key, then we walk the fallback chain
    whenever a quota/rate-limit/empty error fires.

    Successful results are cached in-process so the same description doesn't
    burn duplicate calls across parallel variants or a re-parse click.
    """
    global LAST_ERROR
    ck = _cache_key(prompt, system, json_mode) if use_cache else None
    if ck and (cached := _cache_get(ck)) is not None:
        LAST_ERROR = None
        return cached

    primary = _select_provider(provider)
    if primary == "none":
        LAST_ERROR = {"provider": "none",
                      "reason": "No LLM API key configured."}
        return None

    # Try the primary first, then walk fallbacks (skipping providers without
    # a key). Each provider gets ONE attempt at the public level; per-model
    # rotation happens inside `_call_gemini` itself.
    tried: list[tuple[str, str]] = []
    chain = [primary] + [p for p in _PROVIDER_FALLBACK if p != primary]
    last_exc_text: str | None = None
    for prov in chain:
        # Skip providers we don't have a key for (except the explicitly-
        # requested non-auto provider — let that surface its own error).
        env_name = _PROVIDER_KEY_ENV.get(prov)
        if env_name and not _get_key(env_name) and prov != provider:
            continue
        try:
            out = _try_provider(prov, prompt, system, max_tokens, json_mode)
            if out:
                LAST_ERROR = None
                _ph_ok(prov)
                if ck:
                    _cache_put(ck, out)
                return out
            # Empty text — fall through to next provider
            tried.append((prov, "empty"))
        except Exception as exc:                       # noqa: BLE001
            _LOG.exception("%s call failed", prov)
            last_exc_text = str(exc)[:240]
            tried.append((prov, last_exc_text))
            if _is_quota_error(exc):
                _ph_quota(prov, "", last_exc_text)
            else:
                _ph_error(prov, "", last_exc_text)
                # Non-quota error: don't keep banging on other providers
                # for an auth/network/code problem
                break
    LAST_ERROR = {
        "provider": primary,
        "reason": "All providers failed: " + "; ".join(
            f"{p}={r}" for p, r in tried) or "no providers reachable",
    }
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_json(text: str | None) -> dict | None:
    """Pull the first balanced JSON object out of a model response."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None
