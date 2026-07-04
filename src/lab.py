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
    from src.model import AdSimulationModel
    from src.personas import filter_personas
    from src.pipeline import get_resources
    from src.platforms import get_format
    from src.simulation import monte_carlo
except ImportError:
    from agent import AdStimulus, visual_weights_for
    from model import AdSimulationModel
    from personas import filter_personas
    from pipeline import get_resources
    from platforms import get_format
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


def run_lab(*, platform_id: str, format_id: str, objective: str,
            budget: float, days: int, daily_reach: float, n_runs: int,
            segment: str, creative_quality: float,
            target_ctr: float | None, cpm_override: float | None,
            target_conversion_rate: float | None,
            aov: float | None, fatigue_per_exposure: float | None,
            reachable_audience: int | None) -> dict:
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
        fatigue_per_exposure=fatigue_per_exposure,
    )

    # One extra representative run, stepped manually to capture the
    # population's day-by-day states for the animation.
    tm = AdSimulationModel(
        audience, ad, calibration,
        channel=channel, daily_reach=daily_reach, sim_days=days,
        target_ctr=target_ctr,
        target_conversion_rate=target_conversion_rate,
        fatigue_per_exposure=fatigue_per_exposure,
        seed=_SEED,
    )
    n_show = min(TIMELINE_AGENTS, len(tm.consumer_agents))
    stride = max(1, len(tm.consumer_agents) // n_show)
    shown = tm.consumer_agents[::stride][:n_show]
    frames: list[str] = []
    for _ in range(days):
        tm.step()
        frames.append("".join(str(_agent_state(a)) for a in shown))

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

    result = {
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
        "timeline": {"agents": n_show, "days": days, "frames": frames},
        "saturation": mc.saturation or None,
        "meta": {
            "n_runs": n_runs, "sim_days": days, "channel": channel,
            "audience_personas": int(len(audience)), "segment": segment,
            "creative": "hypothetical (quality slider)",
            "fatigue_source": ("account/custom" if fatigue_per_exposure is not None
                               else "generic default 0.10"),
        },
    }
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = result
    return result
