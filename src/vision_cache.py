"""Process-local LRU cache for vision-analysis results.

When the wizard runs a creative against multiple placements (Reels +
In-Feed Video + Facebook Reels for the same image), the existing code
calls Gemini once PER placement. The vision result is invariant under
placement choice — image content, copy, brand context don't change —
so we were paying Gemini three times and (worse) getting three subtly
different scores because the model is non-deterministic. That's the
'two void, one runnable for the same creative' bug from 2026-06-08.

This module memoises ``analyze_ad`` / ``analyze_ad_video`` results by a
content-aware key so the second + third placement on a multi-placement
run reuse the first call's output. Saves ~66% of Gemini cost on
multi-placement runs and (more importantly) makes the verdict
deterministic across placements.

Scope of the cache:
- Process-local — survives between requests on the same worker,
  resets on every redeploy. That's fine: re-running an old saved
  campaign legitimately re-analyses (the model may have improved).
- Bounded (LRU, default 64 entries) so a long-running worker can't
  accumulate large response objects.
- Keyed on file bytes (sha256), ad_text, audience_hint, brand_category,
  brand_industry — every input that actually shifts the vision read.
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

__all__ = [
    "vision_cache_key",
    "get_cached_vision",
    "set_cached_vision",
    "clear_vision_cache",
]


_MAX_ENTRIES = 64
_lock = threading.Lock()
_cache: "OrderedDict[str, Any]" = OrderedDict()


def _hash_file(path) -> str:
    """SHA-256 of a file's bytes (streamed; safe for our 25MB cap)."""
    h = hashlib.sha256()
    p = Path(path)
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def vision_cache_key(creative_path,
                      ad_text: str = "",
                      audience_hint: str = "",
                      brand_category: str = "",
                      brand_industry: str = "") -> str:
    """Build a stable cache key for one (file + context) tuple.

    Returns "" when there's no creative — caller treats that as 'don't
    cache'. Hashing the file bytes (not the path) is critical because
    Tier 2 downloads URLs to randomly-named temp files, so paths differ
    across calls even when the bytes are identical.
    """
    if not creative_path:
        return ""
    try:
        digest = _hash_file(creative_path)
    except OSError:
        return ""
    # Normalise to limit cache-miss thrash from incidental whitespace.
    ctx = "|".join((
        digest,
        (ad_text or "").strip().lower(),
        (audience_hint or "").strip().lower(),
        (brand_category or "").strip().lower(),
        (brand_industry or "").strip().lower(),
    ))
    return ctx


def get_cached_vision(key: str):
    """Return the cached vision result for ``key`` or None.

    LRU touch: move the entry to the end of the OrderedDict on access.
    """
    if not key:
        return None
    with _lock:
        if key not in _cache:
            return None
        _cache.move_to_end(key)
        return _cache[key]


def set_cached_vision(key: str, value: Any) -> None:
    """Cache a vision result. Bounded — drops oldest on overflow."""
    if not key or value is None:
        return
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
        _cache[key] = value
        while len(_cache) > _MAX_ENTRIES:
            _cache.popitem(last=False)


def clear_vision_cache() -> None:
    """Drop everything — primarily for tests."""
    with _lock:
        _cache.clear()
