"""Creative-fatigue detection from a client's real ad outcomes.

Reimplements the standard creative-fatigue rubric — frequency ceilings,
click-through decay, creative lifespan — as our own logic over the normalized
ad-outcomes DataFrame (the same one `outcomes.py` calibrates from).

Honest by design:
  * Uses ONLY the signals the upload actually contains (frequency, per-ad
    click-through over time) and reports which were available.
  * Thresholds are segment-tagged: a B2B audience is smaller, so frequency
    builds faster and fatigues sooner than a broad DTC/general audience — we
    must not judge them on the same ceiling (mirrors the per-account,
    never-global calibration principle).

These thresholds are widely-published industry facts, not a forecast.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

__all__ = ["analyze_fatigue", "FATIGUE_SEGMENTS"]

FATIGUE_SEGMENTS = ("general", "b2b_saas")

# Frequency ceilings (impressions per person). B2B audiences are smaller, so
# frequency builds faster — lower ceilings. General/DTC tolerate a bit more.
_FREQ_THRESHOLDS = {
    "b2b_saas": {"warning": 3.5, "urgent": 4.0, "depleted": 5.5},
    "general":  {"warning": 4.5, "urgent": 6.0, "depleted": 8.0},
}

# A click-through decline (recent window vs older window for the SAME ad) of
# this size signals fatigue / a dying creative.
_CTR_DROP_WARNING = 0.20    # ≥20% lower = warning
_CTR_DROP_URGENT = 0.35     # ≥35% lower = urgent

_STATUS_RANK = {"healthy": 0, "warning": 1, "urgent": 2, "depleted": 3}


def _thresholds(segment: str) -> dict:
    return _FREQ_THRESHOLDS.get(segment, _FREQ_THRESHOLDS["general"])


def _per_ad_frequency(g: pd.DataFrame) -> float | None:
    """Frequency for an ad: prefer a reported column, else impressions/reach."""
    if "frequency" in g.columns and g["frequency"].notna().any():
        v = float(g["frequency"].dropna().mean())
        if v > 0:
            return round(v, 2)
    if "reach" in g.columns and "impressions" in g.columns:
        reach = float(g["reach"].sum())
        impr = float(g["impressions"].sum())
        if reach > 0:
            return round(impr / reach, 2)
    return None


def _ctr_trend(g: pd.DataFrame) -> dict | None:
    """Older-half vs recent-half weighted click-through for ONE ad — needs the
    ad to appear across at least two distinct dates."""
    if "_date" not in g.columns:
        return None
    gg = g[g["_date"].notna()].sort_values("_date")
    if gg["_date"].nunique() < 2 or len(gg) < 2:
        return None
    cut = len(gg) // 2
    older, recent = gg.iloc[:cut], gg.iloc[cut:]

    def _w(d: pd.DataFrame) -> float | None:
        imp = float(d["impressions"].sum()) if "impressions" in d else 0.0
        clk = float(d["clicks"].sum()) if "clicks" in d else 0.0
        return clk / imp if imp else None

    o, r = _w(older), _w(recent)
    if not o or not r:
        return None
    change = (r - o) / o
    return {"older_ctr": round(o, 5), "recent_ctr": round(r, 5),
            "change_pct": round(change, 3)}


def _classify(freq: float | None, trend: dict | None, th: dict) -> tuple[str, list[str]]:
    """Combine the available signals into a status + human reasons."""
    reasons: list[str] = []
    status = "healthy"

    if freq is not None:
        if freq >= th["depleted"]:
            status = "depleted"
            reasons.append(f"frequency {freq} — far past the {th['urgent']} ceiling; audience saturated")
        elif freq >= th["urgent"]:
            status = _worse(status, "urgent")
            reasons.append(f"frequency {freq} ≥ {th['urgent']} — refresh now")
        elif freq >= th["warning"]:
            status = _worse(status, "warning")
            reasons.append(f"frequency {freq} approaching the {th['urgent']} ceiling")

    if trend is not None:
        drop = -trend["change_pct"]            # positive = a decline
        if drop >= _CTR_DROP_URGENT:
            status = _worse(status, "urgent")
            reasons.append(f"click-through fell {round(drop*100)}% (recent vs older) — creative dying")
        elif drop >= _CTR_DROP_WARNING:
            status = _worse(status, "warning")
            reasons.append(f"click-through down {round(drop*100)}% over time")

    if status == "healthy":
        reasons.append("no fatigue signal in the available data")
    return status, reasons


def _worse(a: str, b: str) -> str:
    return a if _STATUS_RANK[a] >= _STATUS_RANK[b] else b


def analyze_fatigue(df: pd.DataFrame, segment: str = "general",
                    now: datetime | None = None) -> dict:
    """Classify each ad Healthy / Warning / Urgent / Depleted from real data.

    Returns a JSON-able report: per-ad statuses (worst first), summary counts,
    which signals were available, and the segment used.
    """
    segment = segment if segment in _FREQ_THRESHOLDS else "general"
    th = _thresholds(segment)
    if df is None or df.empty or "ad_name" not in df.columns:
        return {"usable": False,
                "reason": "Need per-ad rows (an 'Ad name' column) to detect fatigue.",
                "segment": segment}

    d = df.copy()
    d["_date"] = (pd.to_datetime(d["date_start"], errors="coerce")
                  if "date_start" in d.columns else pd.NaT)

    has_freq_col = "frequency" in d.columns and d["frequency"].notna().any()
    has_reach = "reach" in d.columns and d["reach"].notna().any()
    # Per-ad time series only exists if at least one ad spans multiple dates.
    multi_date = ("_date" in d.columns
                  and d.groupby("ad_name")["_date"].nunique().max() is not np.nan
                  and (d.groupby("ad_name")["_date"].nunique() >= 2).any())

    if not (has_freq_col or has_reach or multi_date):
        return {
            "usable": False,
            "segment": segment,
            "reason": ("This export has no frequency/reach column and no per-ad "
                       "date breakdown, so there's no fatigue signal to read. "
                       "Re-export with Frequency (or Reach), or with a daily/weekly "
                       "breakdown per ad, to enable fatigue detection."),
        }

    ads: list[dict[str, Any]] = []
    for ad_name, g in d.groupby("ad_name"):
        freq = _per_ad_frequency(g)
        trend = _ctr_trend(g)
        status, reasons = _classify(freq, trend, th)
        platform = str(g["platform"].iloc[0]) if "platform" in g.columns and len(g) else ""
        impr = int(g["impressions"].sum()) if "impressions" in g.columns else 0
        ads.append({
            "ad_name": str(ad_name)[:120],
            "platform": platform,
            "status": status,
            "frequency": freq,
            "ctr_change_pct": trend["change_pct"] if trend else None,
            "impressions": impr,
            "reasons": reasons,
        })

    # Worst first, then by spend/impressions so the urgent + high-spend ads top
    # the list (those are bleeding the most budget).
    ads.sort(key=lambda a: (-_STATUS_RANK[a["status"]], -a["impressions"]))
    counts = {s: sum(1 for a in ads if a["status"] == s)
              for s in ("healthy", "warning", "urgent", "depleted")}
    signals = []
    if has_freq_col: signals.append("frequency")
    elif has_reach:  signals.append("frequency (derived from reach)")
    if multi_date:   signals.append("per-ad click-through over time")

    return {
        "usable": True,
        "segment": segment,
        "n_ads": len(ads),
        "counts": counts,
        "needs_attention": counts["urgent"] + counts["depleted"],
        "signals_used": signals,
        "ads": ads[:50],
        "note": ("Frequency ceilings are segment-tagged (B2B audiences fatigue "
                 "sooner). Based on the signals your export contained — not a forecast."),
    }
