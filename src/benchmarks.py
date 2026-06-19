"""Industry × platform × region benchmarks — loaded once at import time.

Backed by the four 2025-2026 reference JSONs sitting in
``data/benchmarks/extracted/`` (see that folder's README.md for the
extraction methodology). This module is the single read-side interface
for the rest of the codebase: callers ask "what's the industry median
engagement for fitness on TikTok?" or "what 2026 context should the
LLM critic know about LinkedIn?" and we return a cited, structured
answer.

Design notes:
- Loaded ONCE at first import, kept in module-level dicts. ~36KB total
  across four files — trivial memory cost.
- Every lookup returns a ``BenchmarkLookup`` with the value AND a
  ``source`` citation so the UI / prompt can attribute it honestly.
- Falls back gracefully when no match — caller decides whether to
  degrade or hide the card.
- Rival IQ data is ORGANIC engagement, not paid CTR. We don't pretend
  otherwise; callers re-frame appropriately (e.g. as a creative-quality
  proxy, not as a paid forecast anchor).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "BenchmarkLookup",
    "industry_platform_engagement",
    "platform_2026_context",
    "global_2026_context",
    "trends_2026_for_prompt",
    "hubspot_2026_for_prompt",
    "linkedin_paid_benchmark",
    "BENCHMARK_SOURCES",
]


# ---------------------------------------------------------------------------
# File loading — happens once at import
# ---------------------------------------------------------------------------

_EXTRACTS = Path(__file__).resolve().parent.parent / "data" / "benchmarks" / "extracted"


def _load(name: str) -> dict:
    path = _EXTRACTS / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:                                     # noqa: BLE001
        return {}


_RIVAL_IQ  = _load("rival_iq_2025_industry_engagement.json")
_SPROUT    = _load("sprout_social_index_2026_platform_stats.json")
_HOOTSUITE = _load("hootsuite_social_trends_2026.json")
_HUBSPOT   = _load("hubspot_state_of_marketing_2026.json")
_SOCIVO_LI   = _load("socivo_linkedin_paid_benchmarks_2026.json")


BENCHMARK_SOURCES = {
    "rival_iq":      _RIVAL_IQ.get("source", {}),
    "sprout":        _SPROUT.get("source", {}),
    "hootsuite":     _HOOTSUITE.get("source", {}),
    "hubspot":       _HUBSPOT.get("source", {}),
    "socivo_linkedin": _SOCIVO_LI.get("source", {}),
}


# ---------------------------------------------------------------------------
# Lookup result container
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkLookup:
    """One factual lookup with provenance.

    ``value`` is whatever the caller asked for (a number, a dict, a
    string). ``source`` is a stable identifier ("rival_iq" / "sprout" /
    "hootsuite" / "hubspot") matching ``BENCHMARK_SOURCES``. ``cite`` is
    a one-line human-readable citation suitable for a UI footer.
    """
    value: Any
    source: str = ""
    cite: str = ""
    found: bool = True
    notes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "value": self.value, "source": self.source,
            "cite": self.cite, "found": self.found,
            "notes": self.notes,
        }


def _cite(source_key: str) -> str:
    src = BENCHMARK_SOURCES.get(source_key) or {}
    title = src.get("title", "").strip()
    publisher = src.get("publisher", "").strip()
    if title and publisher:
        return f"{publisher} — {title}"
    return publisher or title or source_key


# ---------------------------------------------------------------------------
# Platform-name normalisation
# ---------------------------------------------------------------------------
# AdProof platform IDs vs the slugs used in the extract JSONs.
_PLATFORM_RIVAL = {
    "meta_facebook":  "facebook",
    "meta_instagram": "instagram",
    "tiktok":         "tiktok",
    # X / Twitter isn't an AdProof platform today but is in Rival IQ.
}
_PLATFORM_SPROUT = {
    "meta_facebook":  "facebook",
    "meta_instagram": "instagram",
    "linkedin":       "linkedin",
    "tiktok":         "tiktok",
    "youtube":        "youtube",
    "pinterest":      "pinterest",
    "reddit":         "reddit",
    "snapchat":       "snapchat",
    "threads":        "threads",
    "bluesky":        "bluesky",
    "x":              "x_twitter",
    "twitter":        "x_twitter",
}


def _platform_slug(platform_id: str, dataset: dict) -> str | None:
    """Map an AdProof platform_id to the dataset's slug."""
    p = (platform_id or "").lower()
    return dataset.get(p)


# ---------------------------------------------------------------------------
# Public lookups
# ---------------------------------------------------------------------------

def industry_platform_engagement(industry: str, platform_id: str) -> BenchmarkLookup:
    """Median engagement rate + posting frequency for an industry on a
    platform, per Rival IQ 2025.

    Caller is responsible for INTERPRETING the engagement rate (it's
    organic, not paid CTR). The simulate pipeline reframes it as a
    soft creative-quality anchor, NOT as a paid-CTR target.
    """
    if not (industry and platform_id):
        return BenchmarkLookup(value=None, found=False)
    by_industry = (_RIVAL_IQ.get("by_industry") or {})
    plat_slug = _platform_slug(platform_id, _PLATFORM_RIVAL)
    if not plat_slug:
        return BenchmarkLookup(value=None, found=False,
                                notes={"reason": f"Rival IQ doesn't track {platform_id}."})
    industry_data = by_industry.get(industry.lower())
    if not industry_data:
        return BenchmarkLookup(value=None, found=False,
                                notes={"reason": f"Industry '{industry}' not in Rival IQ taxonomy."})
    cell = industry_data.get(plat_slug)
    if not cell:
        return BenchmarkLookup(value=None, found=False)
    return BenchmarkLookup(
        value={
            "engagement_rate": cell.get("engagement_rate"),
            "posts_per_week":  cell.get("posts_per_week"),
            "industry":        industry,
            "platform":        plat_slug,
            "data_year":       _RIVAL_IQ.get("source", {}).get("data_year"),
        },
        source="rival_iq",
        cite=_cite("rival_iq"),
        notes={
            "metric_kind": "ORGANIC engagement rate (likes+comments+shares+reactions / followers)",
            "sample":      _RIVAL_IQ.get("source", {}).get("sample_size", ""),
        },
    )


def platform_2026_context(platform_id: str) -> BenchmarkLookup:
    """Free-text 2026 platform context from Sprout's per-platform section.

    Used to enrich LLM critic prompts so the model knows current
    demographic / behavioural norms for the platform.
    """
    if not platform_id:
        return BenchmarkLookup(value=None, found=False)
    plat_slug = _platform_slug(platform_id, _PLATFORM_SPROUT)
    if not plat_slug:
        return BenchmarkLookup(value=None, found=False)
    platforms = _SPROUT.get("platforms") or {}
    section = platforms.get(plat_slug)
    if not section:
        return BenchmarkLookup(value=None, found=False)
    return BenchmarkLookup(
        value={
            "platform_label": section.get("label"),
            "text":           section.get("text", "")[:3500],
            "char_count":     section.get("char_count"),
        },
        source="sprout",
        cite=_cite("sprout"),
    )


def global_2026_context() -> BenchmarkLookup:
    """Global headline stats from Sprout — 2026 social-media baseline."""
    gc = _SPROUT.get("global_context") or {}
    if not gc:
        return BenchmarkLookup(value=None, found=False)
    return BenchmarkLookup(
        value=gc,
        source="sprout",
        cite=_cite("sprout"),
    )


def trends_2026_for_prompt(max_trends: int = 5) -> BenchmarkLookup:
    """Top N Hootsuite 2026 trends + key takeaways — for LLM prompts.

    Returns the trends with the most takeaways first (those tend to be
    the better-extracted, most-substantive entries).
    """
    trends = _HOOTSUITE.get("trends_2026") or []
    headline = _HOOTSUITE.get("headline_data_points") or {}
    picked = sorted(trends, key=lambda t: -len(t.get("takeaways", [])))[:max_trends]
    if not picked:
        return BenchmarkLookup(value=None, found=False)
    return BenchmarkLookup(
        value={"headline_stats": headline, "trends": picked},
        source="hootsuite",
        cite=_cite("hootsuite"),
    )


def hubspot_2026_for_prompt() -> BenchmarkLookup:
    """HubSpot 2026 marketing data — AI adoption, channel mix, brand-POV."""
    if not _HUBSPOT:
        return BenchmarkLookup(value=None, found=False)
    return BenchmarkLookup(
        value={
            "ai_disruption":       _HUBSPOT.get("ai_disruption", {}),
            "budget_outlook":      _HUBSPOT.get("budget_outlook", {}),
            "marketing_practices": _HUBSPOT.get("marketing_practices", {}),
            "channels":            _HUBSPOT.get("channels", {}),
        },
        source="hubspot",
        cite=_cite("hubspot"),
    )


# Campaign objective -> LinkedIn funnel stage. Mirrors
# linkedin_critic.OBJECTIVE_TO_STAGE so the benchmark band the user sees
# matches the stage the critic graded against.
_OBJECTIVE_TO_FUNNEL = {
    "awareness":     "TOF",
    "consideration": "MOF",
    "conversion":    "BOF",
}


def linkedin_paid_benchmark(objective: str = "consideration") -> BenchmarkLookup:
    """LinkedIn PAID benchmark band for the funnel stage implied by the
    campaign objective (awareness->TOF, consideration->MOF, conversion->BOF).

    Fills a gap nothing else in AdProof covers: Rival IQ is ORGANIC
    engagement only, so we have no paid-LinkedIn numbers anywhere else.
    These are Socivo's ranges — B2B SaaS, USD. The caller
    MUST label them as such and frame them as reference ranges for the
    stage, NOT a prediction of this specific ad's CTR. ``notes`` carries
    the honest caveats (CTRTLP != engagement rate, scope, currency, ROAS
    lag) so the UI / prompt can surface them.
    """
    if not _SOCIVO_LI:
        return BenchmarkLookup(value=None, found=False)
    funnel = _OBJECTIVE_TO_FUNNEL.get((objective or "").lower(), "MOF")
    stage_band = (_SOCIVO_LI.get("ctrtlp_by_stage") or {}).get(funnel) or {}
    src = _SOCIVO_LI.get("source") or {}
    return BenchmarkLookup(
        value={
            "objective":                 objective,
            "funnel_stage":              funnel,
            "ctrtlp_band":               stage_band,
            "ctrtlp_overall_avg_pct":    _SOCIVO_LI.get("ctrtlp_overall_avg_pct"),
            "ctrtlp_good_threshold_pct": _SOCIVO_LI.get("ctrtlp_good_threshold_pct"),
            "cpm_usd":                   _SOCIVO_LI.get("cpm_usd"),
            "cpc_usd":                   _SOCIVO_LI.get("cpc_usd"),
            "cost_per_lead_usd":         _SOCIVO_LI.get("cost_per_lead_usd"),
            "roas_pct":                  _SOCIVO_LI.get("roas_pct"),
            "format_ranking":            _SOCIVO_LI.get("format_ranking") or [],
            "scope":                     src.get("scope", "B2B SaaS"),
            "currency":                  src.get("currency", "USD"),
        },
        source="socivo_linkedin",
        cite=_cite("socivo_linkedin"),
        notes=_SOCIVO_LI.get("honest_notes") or {},
    )
