"""The Simulation Lab's engine tap (L1).

A LIGHTWEIGHT path into the same agent-based model every forecast uses —
no LLM calls, no vision analysis, capped and cached — so the Lab UI can
re-simulate in seconds while a user drags factors.

Returns four things the Lab renders:
  kpis      — clicks/conversions/revenue/ROAS bands + CTR/CPM/spend
  daily     — per-day click/conversion envelopes (p10/p50/p90 across runs)
  factors   — the engine's own click-logit decomposition (what pushed CTR)
  timeline  — a downsampled per-agent state matrix (≤400 agents × days)
              driving the population-field animation:
              0 unexposed · 1 exposed · 2 clicked · 3 converted

Honesty contract: "creative_quality" builds a SYNTHETIC creative (all visual
scores set to the slider value, neutral psychology) — the response labels it
hypothetical. Scoring a real ad stays the wizard's job.
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import PSYCHOLOGY_FEATURES, VISUAL_SCORE_KEYS  # noqa: E402

try:
    from src.agent import AdStimulus, visual_weights_for
    from src.model import AdSimulationModel, release_model
    from src.personas import filter_personas
    from src.pipeline import get_resources
    from src.platforms import get_format
    from src.simcal import fit_fatigue_theta
    from src.simulation import monte_carlo
except ImportError:
    from agent import AdStimulus, visual_weights_for
    from model import AdSimulationModel, release_model
    from personas import filter_personas
    from pipeline import get_resources
    from platforms import get_format
    from simcal import fit_fatigue_theta
    from simulation import monte_carlo

# Hard caps — the Lab must never be able to take down the wizard.
MAX_RUNS = 8
MAX_DAYS = 30
MAX_AGENTS = 600          # personas simulated
TIMELINE_AGENTS = 400     # agents in the animation payload
_SEED = 42

_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 64


def _cache_key(params: dict) -> str:
    return hashlib.sha256(
        json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()


def _band(d: dict) -> dict:
    return {"p10": round(float(d.get("p10", 0)), 2),
            "p50": round(float(d.get("p50", 0)), 2),
            "p90": round(float(d.get("p90", 0)), 2)}


def _agent_state(a) -> int:
    if a.total_purchases > 0:
        return 3
    if a.total_clicks > 0:
        return 2
    if a.times_exposed > 0:
        return 1
    return 0


# Meta's breakdown age bands → persona age ranges (P3c-lite conditioning).
_AGE_BANDS = {
    "13-17": (13, 17), "18-24": (18, 24), "25-34": (25, 34),
    "35-44": (35, 44), "45-54": (45, 54), "55-64": (55, 64),
    "65+": (65, 120),
}


def _cell_of(persona: dict) -> str:
    """Age-band × gender label for one persona ("25-34|female") — lets the
    Living Market view group timeline agents into real demographic districts."""
    try:
        age = int(persona.get("age", 0) or 0)
    except (TypeError, ValueError):
        age = 0
    band = next((b for b, (lo, hi) in _AGE_BANDS.items() if lo <= age <= hi), "?")
    g = str(persona.get("gender", "") or "").lower()
    if g not in ("male", "female"):
        g = "other"
    return f"{band}|{g}"


def _condition_to_mix(audience, mix: list[dict]):
    """Resample the persona population so its age × gender composition
    matches the account's REAL delivery shares (from ad_breakdowns).

    This is population conditioning, lite: cells with more of the account's
    delivery get proportionally more agents. Cells the persona pool can't
    represent — and cells with an unrecognised age band ('unknown') — are
    skipped, their share redistributing across the matched cells. Returns
    None when NO cell matched, so the caller never claims a population was
    conditioned when it wasn't.
    """
    import pandas as pd
    total = sum(float(m.get("share", 0) or 0) for m in mix)
    if total <= 0:
        return None
    parts = []
    for m in mix:
        share = float(m.get("share", 0) or 0) / total
        if share <= 0:
            continue
        band = _AGE_BANDS.get(str(m.get("age", "")))
        if band is None:
            continue      # 'unknown' / unrecognised band can't condition
        lo, hi = band
        sel = audience[(audience["age"] >= lo) & (audience["age"] <= hi)]
        g = str(m.get("gender", "")).lower()
        if g in ("male", "female") and "gender" in sel.columns:
            sel = sel[sel["gender"] == g]
        if len(sel) == 0:
            continue
        n = max(1, round(MAX_AGENTS * share))
        parts.append(sel.sample(n=n, replace=len(sel) < n, random_state=_SEED))
    if not parts:
        return None
    # Shuffle so any downstream subsample (the ≤400-agent timeline) keeps the
    # mix's proportions instead of over-representing the first cell.
    out = pd.concat(parts, ignore_index=True) \
        .sample(frac=1, random_state=_SEED).reset_index(drop=True)
    return out.head(MAX_AGENTS)


def _narrate(recs: list[dict], currency: str, roas_p50: float | None,
             conv_p50: float | None) -> list[dict]:
    """Turn ONE representative run's daily records into an honest event
    stream. Every line traces to a simulated number — no invented drama."""
    evs: list[dict] = []
    if not recs:
        return evs
    evs.append({"day": 1, "kind": "reach",
                "text": f"{recs[0]['exposed']:,} people saw the ad for the first time"})
    first_conv = next((r for r in recs if r["cumulative_purchases"] > 0), None)
    if first_conv:
        evs.append({"day": first_conv["day"], "kind": "convert",
                    "text": f"First conversions land — {first_conv['cumulative_purchases']} buyer"
                            f"{'s' if first_conv['cumulative_purchases'] != 1 else ''} so far"})
    best = max(recs, key=lambda r: r["clicks"])
    if best["clicks"] > 0:
        evs.append({"day": best["day"], "kind": "click",
                    "text": f"Peak day: {best['clicks']} clicks in one day"})
    first_wom = next((r for r in recs if r.get("wom_clicks", 0) > 0), None)
    if first_wom:
        total_wom = sum(r.get("wom_clicks", 0) for r in recs)
        evs.append({"day": first_wom["day"], "kind": "wom",
                    "text": f"Word of mouth kicks in — {total_wom} clicks arrive via friends of buyers over the flight"})
    # Fatigue onset: clicks fall below 60% of the peak after the peak.
    tired = next((r for r in recs
                  if r["day"] > best["day"] and best["clicks"] > 5
                  and r["clicks"] < 0.6 * best["clicks"]), None)
    if tired:
        evs.append({"day": tired["day"], "kind": "fatigue",
                    "text": f"Response cooling — daily clicks down to {tired['clicks']} "
                            f"(peak was {best['clicks']}). In a real flight this is refresh territory."})
    last = recs[-1]
    summary = (f"Flight ends: {last['cumulative_clicks']:,} clicks · "
               f"{last['cumulative_purchases']} conversions in this run")
    if conv_p50 is not None and roas_p50 is not None:
        summary += f" · across all runs: {conv_p50:.0f} conversions, {roas_p50:.2f}× ROAS at p50"
    evs.append({"day": last["day"], "kind": "summary", "text": summary})
    evs.sort(key=lambda e: e["day"])
    return evs


def _fatigue_source(fit: dict | None) -> str:
    """Honest one-liner about how the fatigue constant was set. lambda is a
    ln-CTR slope, so the per-view CTR drop is 1−e^−λ (NOT λ×100); a
    non-converged fit is the engine's CEILING, not a successful match."""
    import math
    if fit is None:
        return "generic default 0.10"
    lam = fit["lambda_target"]
    if lam <= 0:
        return "no fatigue (decay set to 0)"
    pct = (1 - math.exp(-lam)) * 100
    if not fit.get("converged"):
        sim_pct = (1 - math.exp(-fit["lambda_sim"])) * 100
        return (f"observed −{pct:.0f}%/view exceeds what the model can "
                f"express — using its steepest decay (−{sim_pct:.0f}%/view, "
                f"θ={fit['theta']:.3f})")
    return (f"simulation-calibrated (observed −{pct:.0f}%/view "
            f"→ engine θ={fit['theta']:.3f})")


def run_lab(*, platform_id: str, format_id: str, objective: str,
            budget: float, days: int, daily_reach: float, n_runs: int,
            segment: str, creative_quality: float,
            target_ctr: float | None, cpm_override: float | None,
            target_conversion_rate: float | None,
            aov: float | None, fatigue_per_exposure: float | None,
            reachable_audience: int | None,
            audience_mix: list[dict] | None = None,
            currency: str = "GBP") -> dict:
    """One Lab simulation. Pure numeric — safe to call repeatedly."""
    days = max(3, min(int(days), MAX_DAYS))
    n_runs = max(2, min(int(n_runs), MAX_RUNS))
    q = min(max(float(creative_quality), 0.05), 0.95)

    params = {k: v for k, v in locals().items() if k != "params"}
    key = _cache_key(params)
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    fmt = get_format(format_id)
    channel = fmt.simulation_channel

    personas, calibration = get_resources()
    audience = filter_personas(personas, segment)
    if len(audience) < 20:
        raise ValueError(f"Audience '{segment}' has too few personas.")
    # P3c-lite: reshape the population to the account's REAL delivery mix
    # (age × gender shares from their synced breakdowns).
    conditioned = False
    if audience_mix:
        shaped = _condition_to_mix(audience, audience_mix)
        if shaped is not None and len(shaped) >= 20:
            audience = shaped
            conditioned = True
    if len(audience) > MAX_AGENTS:
        audience = audience.sample(MAX_AGENTS, random_state=_SEED)

    # Synthetic creative from the quality slider: every visual axis at q,
    # psychology neutral at the calibration means. Labelled hypothetical.
    psych_means = getattr(calibration, "mean_features", None) or \
        {k: 0.4 for k in PSYCHOLOGY_FEATURES}
    ad = AdStimulus(
        visual_scores={k: q for k in VISUAL_SCORE_KEYS},
        psychology_features={k: float(psych_means.get(k, 0.4))
                             for k in PSYCHOLOGY_FEATURES},
        product_category="general",
        channel=channel,
    )

    # Simulation-based calibration: the incoming fatigue number is the
    # OBSERVED decay per repeat view (the account's fitted lambda, or the
    # slider's "−X% per repeat view"). It can't be pasted into the logit —
    # the sigmoid squashes it (theta=0.20 shows up as ~0.08 observed decay).
    # The simcal loop bisects until the engine's simulated decay matches it.
    theta = fatigue_per_exposure
    fatigue_fit = None
    if fatigue_per_exposure is not None:
        # Clamp to the same plausibility bounds the account fit uses — the
        # API layer doesn't validate this field.
        lam_in = min(max(float(fatigue_per_exposure), 0.0), 0.35)
        fatigue_fit = fit_fatigue_theta(
            lambda_target=lam_in, audience=audience,
            ad=ad, calibration=calibration, channel=channel,
            target_ctr=target_ctr)
        theta = fatigue_fit["theta"]

    mc = monte_carlo(
        audience, ad, calibration,
        channel=channel, budget=budget, sim_days=days,
        n_runs=n_runs, daily_reach=daily_reach, base_seed=_SEED,
        target_ctr=target_ctr,
        target_conversion_rate=target_conversion_rate,
        cpm_override=cpm_override,
        aov_override=aov,
        reachable_audience=reachable_audience,
        visual_weights=visual_weights_for(objective),
        fatigue_per_exposure=theta,
    )

    # One extra representative run, stepped manually to capture the
    # population's day-by-day states for the animation.
    tm = AdSimulationModel(
        audience, ad, calibration,
        channel=channel, daily_reach=daily_reach, sim_days=days,
        target_ctr=target_ctr,
        target_conversion_rate=target_conversion_rate,
        fatigue_per_exposure=theta,
        seed=_SEED,
    )
    n_show = min(TIMELINE_AGENTS, len(tm.consumer_agents))
    stride = max(1, len(tm.consumer_agents) // n_show)
    shown = tm.consumer_agents[::stride][:n_show]
    frames: list[str] = []
    for _ in range(days):
        tm.step()
        frames.append("".join(str(_agent_state(a)) for a in shown))
    release_model(tm)     # else mesa.Agent._ids pins this model forever
    del tm

    env_clicks = mc.daily_envelope("clicks")
    env_purch = mc.daily_envelope("purchases")
    daily = [{
        "day": d,
        "clicks": {k: round(float(v), 1) for k, v in env_clicks.get(d, {}).items()},
        "conversions": {k: round(float(v), 2) for k, v in env_purch.get(d, {}).items()},
    } for d in sorted(env_clicks.keys())]

    mean_ctr = (sum(mc.sample_ctrs) / len(mc.sample_ctrs)) if mc.sample_ctrs else 0.0
    spend = float(budget)
    cpm = spend / mc.total_impressions * 1000 if mc.total_impressions else None

    events = _narrate(tm.daily_records, currency,
                      float(mc.predicted_roas.get("p50", 0)) or None,
                      float(mc.predicted_conversions.get("p50", 0)) or None)

    result = {
        "events": events,
        "kpis": {
            "impressions": int(mc.total_impressions),
            "ctr": round(mean_ctr, 5),
            "cpm": round(cpm, 2) if cpm else None,
            "spend": round(spend, 2),
            "clicks": _band(mc.predicted_clicks),
            "conversions": _band(mc.predicted_conversions),
            "revenue": _band(mc.predicted_revenue),
            "roas": _band(mc.predicted_roas),
            "reach_agents": int(mc.audience_size),
        },
        "daily": daily,
        "factors": {k: round(float(v), 4)
                    for k, v in (mc.aggregate_click_factors or {}).items()},
        "timeline": {"agents": n_show, "days": days, "frames": frames,
                     "cells": [_cell_of(a.persona) for a in shown]},
        "saturation": mc.saturation or None,
        "meta": {
            "n_runs": n_runs, "sim_days": days, "channel": channel,
            "audience_personas": int(len(audience)), "segment": segment,
            "audience_source": ("your real delivery mix (age × gender)"
                                if conditioned else "generic segment"),
            "creative": "hypothetical (quality slider)",
            "fatigue_source": _fatigue_source(fatigue_fit),
            "fatigue_fit": fatigue_fit,
        },
    }
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = result
    return result
