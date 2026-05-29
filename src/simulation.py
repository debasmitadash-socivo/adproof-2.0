"""Monte Carlo runner and sensitivity analysis.

This is the layer that turns a single :class:`AdSimulationModel` run -- which
produces sample CTR/conversion *rates* -- into a campaign forecast with
uncertainty bands.

Pipeline
--------
1. Run the model ``n_runs`` times with different seeds to get a distribution
   of sample CTR, conversion rate, and buy rate.
2. Translate the user's ``budget`` + ``channel`` into total impressions via
   industry-typical CPM rates.
3. Scale the sample rates to the real campaign:
       predicted_clicks       = total_impressions * sample_CTR
       predicted_conversions  = predicted_clicks   * sample_conversion_rate
       predicted_revenue      = predicted_conversions * mean_buyer_AOV
       predicted_ROI          = (revenue - budget) / budget
4. Report p10/p50/p90 bands for each headline metric.
5. ``sensitivity_sweep`` runs small MCs across a parameter range so the UI
   can show how outputs respond to each lever.

Limitations
-----------
The CPM table below is a *directional* industry range, not a quote for any
specific buyer/seller/market. Predicted volumes are honest under the model's
assumptions (calibration, persona sample, anchoring) but should be treated
as decision-support ranges, not committed forecasts.
"""
from __future__ import annotations

import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

# Allow `python src/simulation.py` to find config.py in the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import DEFAULT_MONTE_CARLO_RUNS, DEFAULT_SIM_DAYS  # noqa: E402

try:
    from src.agent import AdStimulus  # noqa: F401
    from src.model import AdSimulationModel
except ImportError:                                # `python src/simulation.py`
    from agent import AdStimulus  # noqa: F401
    from model import AdSimulationModel

__all__ = [
    "CHANNEL_CPM",
    "MonteCarloResults",
    "monte_carlo",
    "sensitivity_sweep",
    "budget_to_impressions",
]

# ===========================================================================
# Industry CPM directional ranges (USD per 1000 impressions)
# ---------------------------------------------------------------------------
# These are mid-range public benchmarks across major US channels. Real CPMs
# vary widely by vertical, geo, format, and demand. Treat as a defensible
# default that the UI can let the user override if they have a real number.
# ===========================================================================

CHANNEL_CPM = {
    "display": 5.0,
    "social_feed": 10.0,
    "search": 20.0,
    "video": 15.0,
    "email": 3.0,
}


def budget_to_impressions(budget: float, channel: str,
                           cpm_override: float | None = None) -> int:
    """Convert a campaign budget into the total impressions it buys.

    ``cpm_override`` lets a caller (e.g. a platform/format-aware brief) pass
    a specific CPM instead of the coarse channel default.
    """
    cpm = (cpm_override if cpm_override and cpm_override > 0
           else CHANNEL_CPM.get(channel, CHANNEL_CPM["social_feed"]))
    return int(round(max(0.0, budget) / cpm * 1000))


# ===========================================================================
# Distribution helpers
# ===========================================================================

def _dist(values: np.ndarray | list, ndigits: int = 3) -> dict:
    """Summarise a run-level array as a {mean, std, p10, p50, p90} dict."""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0 or np.all(np.isnan(arr)):
        return {"mean": 0.0, "std": 0.0, "p10": 0.0, "p50": 0.0, "p90": 0.0}
    arr = arr[~np.isnan(arr)]
    return {
        "mean": round(float(arr.mean()), ndigits),
        "std":  round(float(arr.std(ddof=0)), ndigits),
        "p10":  round(float(np.percentile(arr, 10)), ndigits),
        "p50":  round(float(np.percentile(arr, 50)), ndigits),
        "p90":  round(float(np.percentile(arr, 90)), ndigits),
    }


# ===========================================================================
# Monte Carlo results container
# ===========================================================================

@dataclass
class MonteCarloResults:
    """Aggregated output of a Monte Carlo over many model runs."""
    n_runs: int
    sim_days: int
    channel: str
    budget: float
    audience_size: int

    # Per-run sample rates (length n_runs each).
    sample_ctrs: list
    sample_conversion_rates: list
    sample_buy_rates: list

    # Real-campaign scale.
    total_impressions: int
    mean_aov: float
    predicted_clicks: dict        # {mean, std, p10, p50, p90}
    predicted_conversions: dict
    predicted_revenue: dict
    predicted_roi: dict           # ROI as a ratio (e.g. 0.30 == +30%)
    predicted_roas: dict          # revenue / spend

    # Day-by-day records for every run -- feeds the UI envelope plots.
    daily_records_per_run: list = field(default_factory=list)
    # Mean logit contributions across runs, for the explanation module.
    aggregate_click_factors: dict = field(default_factory=dict)
    # Budget-saturation accounting (empty unless a reachable audience is set).
    saturation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def daily_envelope(self, metric: str = "clicks") -> dict:
        """Per-day distribution of a metric across runs.

        Returns ``{day: {mean, p10, p50, p90}}`` so the UI can shade a
        confidence band around the median daily curve.
        """
        if not self.daily_records_per_run:
            return {}
        days = sorted({rec["day"] for rec in self.daily_records_per_run[0]})
        out: dict = {}
        for d in days:
            vals = [rec[metric] for run in self.daily_records_per_run
                    for rec in run if rec["day"] == d and metric in rec]
            if vals:
                out[d] = _dist(vals, ndigits=2)
        return out

    def summary(self) -> str:
        clicks = self.predicted_clicks
        convs = self.predicted_conversions
        rev = self.predicted_revenue
        roi = self.predicted_roi
        roas = self.predicted_roas
        sample_ctr_pct = np.mean(self.sample_ctrs) * 100
        return "\n".join([
            f"Monte Carlo -- {self.n_runs} runs x {self.sim_days} days on "
            f"{self.audience_size:,} personas ({self.channel})",
            "-" * 64,
            f"  budget                 ${self.budget:,.0f}  "
            f"-> {self.total_impressions:,} impressions",
            f"  sample CTR (mean)      {sample_ctr_pct:.3f}%  "
            f"(n_runs={self.n_runs})",
            f"  predicted clicks       p10 {clicks['p10']:,.0f}  "
            f"median {clicks['p50']:,.0f}  p90 {clicks['p90']:,.0f}",
            f"  predicted conversions  p10 {convs['p10']:,.0f}  "
            f"median {convs['p50']:,.0f}  p90 {convs['p90']:,.0f}",
            f"  predicted revenue      p10 ${rev['p10']:,.0f}  "
            f"median ${rev['p50']:,.0f}  p90 ${rev['p90']:,.0f}",
            f"  predicted ROI          p10 {roi['p10']*100:+.1f}%  "
            f"median {roi['p50']*100:+.1f}%  p90 {roi['p90']*100:+.1f}%",
            f"  predicted ROAS         p10 {roas['p10']:.2f}x  "
            f"median {roas['p50']:.2f}x  p90 {roas['p90']:.2f}x",
            f"  mean buyer AOV         ${self.mean_aov:,.0f}",
        ])


# ===========================================================================
# Monte Carlo runner
# ===========================================================================

def monte_carlo(personas,
                ad: AdStimulus,
                calibration,
                *,
                channel: str | None = None,
                budget: float = 10_000.0,
                sim_days: int = DEFAULT_SIM_DAYS,
                n_runs: int = DEFAULT_MONTE_CARLO_RUNS,
                daily_reach: float = 0.35,
                base_seed: int = 42,
                anchor_to_benchmark: bool = True,
                target_ctr: float | None = None,
                target_conversion_rate: float | None = 0.025,
                visual_weights: dict | None = None,
                network_type: str = "small_world",
                avg_connections: int = 6,
                cpm_override: float | None = None,
                aov_multiplier: float = 1.0,
                aov_override: float | None = None,
                reachable_audience: int | None = None,
                ) -> MonteCarloResults:
    """Run the model many times and produce a campaign forecast with bands.

    ``reachable_audience`` enables budget saturation: if set, raw impressions
    are passed through a log diminishing-returns curve so that pouring more
    budget into the SAME finite audience yields fewer incremental clicks
    (frequency rises, marginal value falls). This is a deliberate MODELLING
    ASSUMPTION (a standard reach/frequency curve), not a figure calibrated from
    the advertiser's data — the caller is responsible for labelling it as such.
    Left None, the forecast scales linearly with budget (no saturation).
    """
    channel = channel or ad.channel
    raw_imp = budget_to_impressions(budget, channel, cpm_override=cpm_override)
    # Budget saturation (assumption-based, opt-in). effective = N·ln(1 + I/N):
    # ~linear while impressions are small vs the audience, strongly diminishing
    # once they exceed it.
    saturation: dict = {}
    if reachable_audience and reachable_audience > 0:
        N = float(reachable_audience)
        effective_imp = int(round(N * math.log1p(raw_imp / N)))
        reach = N * (1.0 - math.exp(-raw_imp / N))
        saturation = {
            "reachable_audience": int(N),
            "raw_impressions": int(raw_imp),
            "effective_impressions": effective_imp,
            "efficiency": round(effective_imp / raw_imp, 3) if raw_imp else 1.0,
            "est_frequency": round(raw_imp / reach, 2) if reach else None,
            "assumption": True,
        }
    else:
        effective_imp = raw_imp
    total_imp = raw_imp          # impressions the budget actually buys (reported)

    sample_ctr, sample_conv, sample_conv_expected = [], [], []
    sample_buy, aovs = [], []
    daily_records, factor_runs = [], []

    for i in range(n_runs):
        model = AdSimulationModel(
            personas, ad, calibration,
            channel=channel, daily_reach=daily_reach, sim_days=sim_days,
            network_type=network_type, avg_connections=avg_connections,
            visual_weights=visual_weights,
            anchor_to_benchmark=anchor_to_benchmark, target_ctr=target_ctr,
            target_conversion_rate=target_conversion_rate,
            seed=base_seed + i,
        )
        r = model.run()
        sample_ctr.append(r.ctr)
        sample_conv.append(r.conversion_rate)
        sample_conv_expected.append(r.expected_conversion_rate)
        sample_buy.append(r.buy_rate)
        aovs.append(r.mean_buyer_aov)        # always non-zero thanks to fallback
        daily_records.append(r.daily_records)
        factor_runs.append(r.aggregate_click_factors)

    arr_ctr = np.asarray(sample_ctr, dtype=float)
    # Use the expected per-click conversion probability rather than the noisy
    # empirical sample. The empirical series stays in ``sample_conversion_rates``
    # so the UI can still chart the realised spread.
    arr_conv = np.asarray(sample_conv_expected, dtype=float)
    valid_aovs = [a for a in aovs if a > 0]
    synthetic_mean_aov = float(np.mean(valid_aovs)) if valid_aovs else 0.0

    # AOV resolution — honesty hierarchy:
    #   1. aov_override (the user's REAL average order value / customer value)
    #      wins outright. This is the accurate path: revenue = conversions ×
    #      the number the advertiser actually told us, not a synthetic guess.
    #   2. Otherwise fall back to the synthetic persona mean × a crude
    #      business-model multiplier. Clearly inferior; only used when the
    #      user hasn't supplied their economics.
    if aov_override is not None and aov_override > 0:
        mean_aov = float(aov_override)
    else:
        mean_aov = synthetic_mean_aov
        if aov_multiplier and aov_multiplier != 1.0:
            mean_aov *= float(aov_multiplier)

    # Scale sample rates to the real campaign volume. Clicks use EFFECTIVE
    # impressions (after saturation); the reported impression count stays at
    # what the budget actually buys.
    pred_clicks = arr_ctr * effective_imp
    pred_conversions = pred_clicks * arr_conv
    pred_revenue = pred_conversions * mean_aov
    pred_roi = (pred_revenue - budget) / budget if budget > 0 else \
        np.zeros_like(pred_revenue)
    pred_roas = pred_revenue / budget if budget > 0 else \
        np.zeros_like(pred_revenue)

    # Mean aggregate click factors across runs -- used by the explanation.
    factor_keys = sorted({k for d in factor_runs for k in d})
    aggregated_factors = {
        k: round(float(np.mean([d.get(k, 0.0) for d in factor_runs])), 4)
        for k in factor_keys
    }

    return MonteCarloResults(
        n_runs=n_runs, sim_days=sim_days, channel=channel,
        budget=float(budget), audience_size=len(personas),
        sample_ctrs=sample_ctr,
        sample_conversion_rates=sample_conv,
        sample_buy_rates=sample_buy,
        total_impressions=total_imp,
        mean_aov=mean_aov,
        predicted_clicks=_dist(pred_clicks, ndigits=1),
        predicted_conversions=_dist(pred_conversions, ndigits=1),
        predicted_revenue=_dist(pred_revenue, ndigits=2),
        predicted_roi=_dist(pred_roi, ndigits=4),
        predicted_roas=_dist(pred_roas, ndigits=3),
        daily_records_per_run=daily_records,
        aggregate_click_factors=aggregated_factors,
        saturation=saturation,
    )


# ===========================================================================
# Sensitivity analysis
# ===========================================================================

def sensitivity_sweep(personas,
                       ad: AdStimulus,
                       calibration,
                       lever: str,
                       values: list,
                       *,
                       base_kwargs: dict | None = None,
                       n_runs: int = 8) -> list:
    """Sweep one lever across ``values`` and report mean outputs per setting.

    Supported levers: ``budget``, ``daily_reach``, ``sim_days``, ``channel``,
    ``target_ctr``, ``avg_connections``, ``network_type``. The result is a
    list of dicts, one per swept value, ready for tabling/charting.
    """
    base = dict(base_kwargs or {})
    base.setdefault("budget", 10_000.0)
    base.setdefault("sim_days", DEFAULT_SIM_DAYS)
    base.setdefault("daily_reach", 0.35)

    out = []
    for v in values:
        kwargs = dict(base)
        kwargs[lever] = v
        kwargs["n_runs"] = n_runs
        # Don't pass nullable controls when not set -- keep monte_carlo's
        # signature clean.
        kwargs = {k: vv for k, vv in kwargs.items() if vv is not None
                  or k in ("target_ctr", "target_conversion_rate",
                           "cpm_override", "visual_weights")}
        mc = monte_carlo(personas, ad, calibration, **kwargs)
        out.append({
            "lever": lever,
            "value": v,
            "mean_ctr": round(float(np.mean(mc.sample_ctrs)), 5),
            "mean_clicks": mc.predicted_clicks["mean"],
            "mean_conversions": mc.predicted_conversions["mean"],
            "mean_revenue": mc.predicted_revenue["mean"],
            "mean_roi": mc.predicted_roi["mean"],
            "mean_roas": mc.predicted_roas["mean"],
        })
    return out


# ===========================================================================
# CLI demo
# ===========================================================================

def _main() -> None:
    try:
        from src.personas import filter_personas, load_personas
        from src.calibration import load_calibration, run_calibration
    except ImportError:
        from personas import filter_personas, load_personas
        from calibration import load_calibration, run_calibration

    try:
        personas = load_personas()
    except FileNotFoundError:
        from personas import generate_personas, save_personas
        personas = generate_personas(800); save_personas(personas)
    try:
        calibration = load_calibration()
    except FileNotFoundError:
        calibration = run_calibration()

    audience = filter_personas(personas, "millennials")
    ad = AdStimulus.build(
        visual_scores={"emotional_arousal": 0.70, "visual_clarity": 0.80,
                       "attention_capture": 0.75,
                       "relevance_potential": 0.65},
        ad_text="Limited offer! Save 40% today -- loved by thousands.",
        product_category="beauty", channel="social_feed",
    )

    print("=" * 64)
    mc = monte_carlo(audience, ad, calibration,
                     budget=10_000.0, sim_days=14, n_runs=20, base_seed=42)
    print(mc.summary())

    print("\nMean click-logit contributions across all runs:")
    for k, v in mc.aggregate_click_factors.items():
        print(f"  {k:<16s} {v:+.3f}")

    print("\n" + "=" * 64)
    print("SENSITIVITY SWEEP -- budget")
    print("=" * 64)
    print(f"  {'budget':>10s}  {'clicks':>8s}  {'convs':>7s}  "
          f"{'revenue':>10s}  {'ROI':>8s}  {'ROAS':>6s}")
    for row in sensitivity_sweep(
        audience, ad, calibration, "budget",
        [2_000, 5_000, 10_000, 25_000, 50_000],
        base_kwargs={"sim_days": 14, "daily_reach": 0.35}, n_runs=8,
    ):
        print(f"  ${row['value']:>9,.0f}  {row['mean_clicks']:>8,.0f}  "
              f"{row['mean_conversions']:>7,.0f}  "
              f"${row['mean_revenue']:>9,.0f}  "
              f"{row['mean_roi']*100:>+7.1f}%  "
              f"{row['mean_roas']:>5.2f}x")

    print("\nSENSITIVITY SWEEP -- daily_reach")
    print(f"  {'reach':>7s}  {'CTR':>8s}  {'clicks':>8s}  {'ROI':>8s}")
    for row in sensitivity_sweep(
        audience, ad, calibration, "daily_reach",
        [0.10, 0.20, 0.35, 0.50, 0.70],
        base_kwargs={"sim_days": 14, "budget": 10_000.0}, n_runs=8,
    ):
        print(f"  {row['value']*100:>5.0f}%  {row['mean_ctr']*100:>7.3f}%  "
              f"{row['mean_clicks']:>8,.0f}  "
              f"{row['mean_roi']*100:>+7.1f}%")


if __name__ == "__main__":
    _main()
