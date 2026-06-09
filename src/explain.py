"""Human-readable explanation of a simulation result.

Turns the Monte Carlo output, visual analysis, ad stimulus, and calibration
into a structured "why this ad performs the way it does" narrative -- the
piece the Gradio UI surfaces alongside the charts.

Deliberately template-based (not LLM-generated): deterministic, no extra API
cost, predictable in regulated-marketing contexts. An LLM enhancement layer
could be added on top later without changing this module's signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow `python src/explain.py` to find config.py if needed.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

__all__ = ["explain_simulation"]


# ===========================================================================
# Thresholds (tunable -- documented as directional)
# ===========================================================================

_ROAS_STRONG = 4.0       # >= -> "strong"
_ROAS_POSITIVE = 2.0     # >= -> "positive"
_ROAS_BREAKEVEN = 1.0    # >= -> "break-even"
_ROAS_IMPLAUSIBLE = 12.0  # > -> almost certainly an overstated input, not real
_FATIGUE_FLAG = -0.50    # logit threshold for "fatigue is biting"
_WOM_NOTABLE = 0.05      # mean WoM contribution to call out
_VISUAL_WEAK = 0.45
_VISUAL_STRONG = 0.65


# ===========================================================================
# Verdict
# ===========================================================================

def _verdict(mc, sample_ctr: float | None = None,
             bench_ctr: float | None = None,
             objective: str = "conversion",
             bench_cpm: float | None = None,
             budget: float | None = None,
             total_impressions: int | None = None,
             currency: str = "GBP") -> tuple[str, str, str]:
    """Return (verdict_class, headline, one-liner) graded against the
    objective the user actually picked.

    The base ROAS-magnitude verdict is the right answer ONLY for a
    conversion brief. An awareness brief is fundamentally about CPM /
    reach; a consideration brief about CTR / CPC. Grading either of
    those on ROAS magnitude is the bug the owner caught on 2026-06-08
    (Variant A · Facebook · Reels: 9.5x ROAS, 0.58% CTR vs 1.30%
    benchmark, label said 'BREAK EVEN' grade C even though the
    consideration objective is failing on engagement). This function
    is now objective-aware so insights.verdict_class agrees with
    plain_verdict.class end-to-end.

    For conversion (the original logic): two believability guardrails
    still apply so a fantasy number can't read as a green 'Strong' win.
    """
    obj = (objective or "conversion").lower()
    roas_p50 = mc.predicted_roas["p50"]
    roi_p50 = mc.predicted_roi["p50"] * 100

    if obj == "awareness":
        # CPM-led grade. Lower CPM is better.
        cpm = ((budget / total_impressions) * 1000
               if budget and total_impressions else None)
        ref = bench_cpm or 8.0
        if cpm is None or ref is None:
            cls = "moderate_reach"
        elif cpm <= ref * 0.75:
            cls = "wide_reach"
        elif cpm <= ref * 1.10:
            cls = "moderate_reach"
        else:
            cls = "narrow_reach"
        headline = {
            "wide_reach": "Wide reach forecast",
            "moderate_reach": "Moderate reach forecast",
            "narrow_reach": "Narrow reach forecast",
        }[cls]
        one_liner = (
            f"Awareness brief — graded on CPM. Modelled CPM "
            f"{currency} {cpm:.2f} vs format benchmark "
            f"{currency} {ref:.2f}."
            if cpm is not None else
            f"Awareness brief — CPM benchmark {currency} {ref:.2f}."
        )
        return cls, headline, one_liner

    if obj == "consideration":
        # CTR-led grade. Higher CTR vs format benchmark is better.
        if sample_ctr is None or bench_ctr is None or bench_ctr <= 0:
            cls = "fair_engagement"
        elif sample_ctr >= bench_ctr * 1.25:
            cls = "strong_engagement"
        elif sample_ctr >= bench_ctr * 0.90:
            cls = "fair_engagement"
        else:
            cls = "weak_engagement"
        headline = {
            "strong_engagement": "Strong engagement forecast",
            "fair_engagement": "Fair engagement forecast",
            "weak_engagement": "Weak engagement forecast",
        }[cls]
        if sample_ctr is not None and bench_ctr:
            delta = (sample_ctr - bench_ctr) / bench_ctr * 100
            one_liner = (
                f"Consideration brief — graded on CTR. Modelled "
                f"{sample_ctr*100:.2f}% vs {bench_ctr*100:.2f}% benchmark "
                f"({delta:+.0f}%). ROAS shown elsewhere is a directional "
                f"artefact — don't grade a consideration ad on it."
            )
        else:
            one_liner = "Consideration brief — graded on CTR."
        return cls, headline, one_liner

    # objective == "conversion" (or unknown -> conversion). Original logic
    # preserved verbatim so existing conversion-brief behaviour is unchanged.
    roas_p10 = mc.predicted_roas["p10"]

    if roas_p50 >= _ROAS_STRONG:
        cls = "strong"
    elif roas_p50 >= _ROAS_POSITIVE:
        cls = "positive"
    elif roas_p50 >= _ROAS_BREAKEVEN:
        cls = "break_even"
    else:
        cls = "underperforming"

    notes: list = []
    if sample_ctr and bench_ctr and sample_ctr < bench_ctr * 0.90 \
            and cls in ("strong", "positive"):
        cls = "break_even"
        notes.append("the creative's click-through is below the format "
                     "benchmark, so any high return is driven by your economics, "
                     "not the ad's strength")
    if roas_p50 > _ROAS_IMPLAUSIBLE:
        cls = "underperforming" if cls == "underperforming" else "break_even"
        notes.append(f"a {roas_p50:.0f}x ROAS is far above what real campaigns "
                     "achieve (1-8x) — almost always an overstated conversion "
                     "rate or order value; verify those inputs")

    headline = {
        "strong": "Strong forecast", "positive": "Positive forecast",
        "break_even": ("Check your inputs" if roas_p50 > _ROAS_IMPLAUSIBLE
                       else "Near break-even"),
        "underperforming": "Underperforming forecast",
    }[cls]

    risk = ""
    if roas_p10 < _ROAS_BREAKEVEN and cls != "underperforming":
        risk = " — but the p10 downside slips below break-even, so treat the upside as conditional"
    extra = (" Note: " + "; ".join(notes) + ".") if notes else ""
    one_liner = (
        f"Median ROAS {roas_p50:.2f}x (ROI {roi_p50:+.0f}%); "
        f"p10 {mc.predicted_roas['p10']:.2f}x — p90 "
        f"{mc.predicted_roas['p90']:.2f}x.{risk}{extra}"
    )
    return cls, headline, one_liner


# ===========================================================================
# Driver attribution
# ===========================================================================

def _rank_factors(factors: dict) -> tuple[list, list]:
    """Split aggregate click logit factors into positives and negatives,
    each sorted by magnitude. Excludes 'base' (it's just the anchor)."""
    items = [(k, float(v)) for k, v in factors.items() if k != "base"]
    positives = sorted([i for i in items if i[1] > 0],
                       key=lambda kv: -kv[1])
    negatives = sorted([i for i in items if i[1] < 0],
                       key=lambda kv: kv[1])
    return positives, negatives


_TERM_LABEL = {
    "visual": "the creative's visual scores",
    "psychology": "psychology cues in the copy",
    "persona_match": "audience / channel / category fit",
    "word_of_mouth": "word-of-mouth on the social graph",
    "fatigue": "ad fatigue from repeat exposure",
    "plausibility_cap": "plausibility cap (kept the forecast realistic)",
}


def _term_label(term: str) -> str:
    return _TERM_LABEL.get(term, term)


# ===========================================================================
# Visual analysis bullets
# ===========================================================================

def _visual_bullets(visual_result) -> tuple[list, list]:
    """Bullets describing creative strengths and weaknesses."""
    if visual_result is None:
        return [], []
    strengths, weaknesses = [], []
    for key, score in visual_result.scores.items():
        label = key.replace("_", " ")
        if score >= _VISUAL_STRONG:
            strengths.append(f"**{label}** scored {score:.2f} — "
                             f"{visual_result.explanations.get(key, '').strip() or 'a clear strength'}")
        elif score <= _VISUAL_WEAK:
            weaknesses.append(f"**{label}** scored {score:.2f} — "
                              f"{visual_result.explanations.get(key, '').strip() or 'an area to improve'}")
    return strengths, weaknesses


# ===========================================================================
# Recommendations
# ===========================================================================

def _recommendations(mc, visual_result, ad, calibration) -> list:
    recs: list = []

    # Visual weak spots get a concrete copy/creative suggestion. ONLY emit
    # these when a real vision model produced the scores — the heuristic
    # scores come from colour/contrast/edge stats and can't tell a face from
    # a wall, so the advice ("bring in an expressive face") fires confidently
    # wrong on a heuristic run. The honesty banner at the top already tells
    # the user the visual layer is degraded.
    if visual_result is not None and not getattr(
            visual_result, "is_heuristic", True):
        vs = visual_result.scores
        if vs.get("attention_capture", 1.0) < _VISUAL_WEAK:
            recs.append("Visual **attention capture is weak** — strengthen "
                        "contrast, isolate one focal point, and remove "
                        "competing elements.")
        if vs.get("emotional_arousal", 1.0) < _VISUAL_WEAK:
            recs.append("Visual **emotional arousal is low** — bring in an "
                        "expressive face, a more evocative scene, or warmer "
                        "/ more saturated colour.")
        if vs.get("visual_clarity", 1.0) < _VISUAL_WEAK:
            recs.append("**Layout reads as cluttered** — simplify the "
                        "hierarchy so the message is grasped in <2 seconds.")
        if vs.get("relevance_potential", 1.0) < _VISUAL_WEAK:
            recs.append("The **value proposition isn't clear from the "
                        "creative alone** — surface a specific benefit and "
                        "who it is for in the headline.")

    # Psychology gaps in the copy.
    if ad is not None:
        psych = ad.psychology_features
        if psych.get("scarcity", 0) < 0.1:
            recs.append("Copy has **no urgency cues** — test a scarcity "
                        "line (e.g. 'ends Sunday', 'only 24 left') to lift "
                        "deal-driven conversion.")
        if psych.get("social_proof", 0) < 0.1:
            recs.append("Copy has **no social proof** — try a customer "
                        "count, a rating, or a 'loved by …' line.")

    # Persona-match drag.
    factors = mc.aggregate_click_factors or {}
    if factors.get("persona_match", 0) < -0.10:
        recs.append("**Audience/channel/category fit is dragging "
                    "performance** — reconsider the target segment or run "
                    "on a channel that aligns with their primary platform.")

    # Fatigue is biting.
    if factors.get("fatigue", 0) <= _FATIGUE_FLAG:
        recs.append("**Ad fatigue is material** — reduce daily frequency or "
                    "rotate in a second creative.")

    # WoM lift worth pushing on.
    if factors.get("word_of_mouth", 0) >= _WOM_NOTABLE:
        recs.append("**Word-of-mouth is contributing meaningfully** — "
                    "consider a referral, UGC, or influencer push to "
                    "amplify the network effect.")

    # Downside risk.
    if mc.predicted_roi["p10"] < -0.5:
        recs.append("**Downside risk is wide** (p10 ROI < -50%): run a "
                    "small budget pilot before committing the full spend.")

    if not recs:
        recs.append("No urgent levers stand out — the creative is balanced. "
                    "Look for incremental gains via A/B tests on headline "
                    "variants and audience expansion.")
    return recs


# ===========================================================================
# Caveats
# ===========================================================================

def _caveats(mc, visual_result, calibration) -> list:
    caveats = [
        f"Forecast is built on a synthetic audience of "
        f"{mc.audience_size:,} personas — representative in structure, not "
        f"a real research panel.",
        f"Outputs are aggregated over {mc.n_runs} Monte Carlo runs; the "
        f"p10–p90 bands reflect modelling uncertainty, not real-world "
        f"confidence intervals.",
        "Channel benchmark CTR and CPM are directional industry ranges, "
        "not market-specific quotes.",
    ]
    if visual_result is not None and getattr(visual_result, "is_heuristic",
                                              False):
        caveats.append("Visual scores came from the **heuristic fallback** "
                       "(image stats + copy keywords) — connect an "
                       "ANTHROPIC_API_KEY or OPENAI_API_KEY for a "
                       "multimodal-model assessment.")
    if calibration is not None and getattr(calibration, "is_synthetic",
                                            False):
        caveats.append("Psychology weights were calibrated on the "
                       "**synthetic CTR dataset** — download a real "
                       "creative-labelled CTR dataset (see "
                       "`data_loader.download_instructions`) before "
                       "presenting calibrated effect sizes to a client.")
    return caveats


# ===========================================================================
# Markdown assembly
# ===========================================================================

def _build_markdown(insights: dict) -> str:
    parts = [
        f"## {insights['headline']}",
        f"_{insights['one_liner']}_",
    ]
    if insights.get("benchmark_note"):
        parts += ["", insights["benchmark_note"]]
    parts += [
        "",
        "### What's working",
    ]
    parts += [f"- {b}" for b in insights["what_works"]] or ["- (no standout positives)"]
    parts += ["", "### What's holding it back"]
    parts += [f"- {b}" for b in insights["what_holds_back"]] or ["- (no material drags identified)"]
    parts += ["", "### Recommendations"]
    parts += [f"- {b}" for b in insights["recommendations"]]
    parts += ["", "### Caveats"]
    parts += [f"- {b}" for b in insights["caveats"]]
    return "\n".join(parts)


# ===========================================================================
# Public API
# ===========================================================================

def explain_simulation(mc,
                       *,
                       visual_result=None,
                       ad=None,
                       calibration=None,
                       segment: str = "all",
                       channel: str | None = None,
                       context: dict | None = None) -> dict:
    """Produce a structured + markdown narrative for the simulation.

    ``context`` (optional) carries the wizard's CompanyProfile / AudienceMatch
    / CampaignBrief / AdFormat so the narrative can be written with the
    company name, platform, and format-specific benchmark in view -- not just
    in abstract simulator terms.
    """
    # Pull the format benchmark CTR/CPM (if the wizard passed the format) so the
    # verdict can tell whether the creative is actually pulling its weight on
    # the OBJECTIVE the user chose (awareness -> CPM, consideration -> CTR,
    # conversion -> ROAS). Without the objective here the verdict would
    # silently default to ROAS-grade like the legacy code did, which is the
    # bug Pillar A was meant to fix.
    _fmt = (context or {}).get("format")
    _bench_ctr = (_fmt.benchmarks.get("ctr", 0.012)
                  if _fmt is not None and hasattr(_fmt, "benchmarks") else None)
    _bench_cpm = (_fmt.benchmarks.get("cpm", 8.0)
                  if _fmt is not None and hasattr(_fmt, "benchmarks") else None)
    _sample_ctr = (sum(mc.sample_ctrs) / max(len(mc.sample_ctrs), 1)
                   if mc.sample_ctrs else None)
    _brief = (context or {}).get("brief")
    _objective = (getattr(_brief, "objective", "conversion") or "conversion")
    _budget = getattr(_brief, "budget", None)
    _currency = getattr(_brief, "currency", "GBP") or "GBP"
    _total_impressions = getattr(mc, "total_impressions", None)
    verdict_class, headline, one_liner = _verdict(
        mc, _sample_ctr, _bench_ctr,
        objective=_objective, bench_cpm=_bench_cpm,
        budget=_budget, total_impressions=_total_impressions,
        currency=_currency,
    )

    positives, negatives = _rank_factors(mc.aggregate_click_factors or {})
    what_works = []
    for i, (term, value) in enumerate(positives[:3]):
        tag = "  _(top positive driver)_" if i == 0 else ""
        what_works.append(
            f"**{_term_label(term).capitalize()}**: {value:+.2f} logit"
            f"{tag}")

    vis_strengths, vis_weaknesses = _visual_bullets(visual_result)
    what_works += vis_strengths[:2]

    what_holds_back = []
    for term, value in negatives[:3]:
        what_holds_back.append(
            f"**{_term_label(term).capitalize()}**: {value:+.2f} logit")
    what_holds_back += vis_weaknesses[:2]

    # Use the context to title the narrative with the brand + platform if
    # the wizard supplied them; falls back to the generic verdict label.
    ctx = context or {}
    profile = ctx.get("profile")
    brief = ctx.get("brief")
    fmt = ctx.get("format")
    title_bits = []
    if profile is not None and getattr(profile, "company_name", ""):
        title_bits.append(profile.company_name)
    if fmt is not None:
        title_bits.append(getattr(fmt, "platform_name", ""))
        title_bits.append(getattr(fmt, "name", ""))
    titled_headline = headline
    if title_bits:
        titled_headline = f"{headline} -- {' / '.join(title_bits)}"

    # Compare projected sample CTR to the format's benchmark range so the
    # narrative gives the user a concrete "where we landed vs typical".
    benchmark_note = ""
    if fmt is not None and hasattr(fmt, "benchmarks"):
        bench_ctr = fmt.benchmarks.get("ctr", 0.012)
        ctr_range = fmt.benchmarks.get("ctr_range", (bench_ctr * 0.5,
                                                      bench_ctr * 1.5))
        sample_ctr = (sum(mc.sample_ctrs) /
                      max(len(mc.sample_ctrs), 1)) if mc.sample_ctrs else 0.0
        position = ("above" if sample_ctr > bench_ctr * 1.10
                    else "below" if sample_ctr < bench_ctr * 0.90
                    else "in line with")
        benchmark_note = (
            f"Projected CTR {sample_ctr*100:.2f}% is {position} the "
            f"{getattr(fmt, 'name', 'format')} benchmark of "
            f"{bench_ctr*100:.2f}% "
            f"(typical range {ctr_range[0]*100:.2f}-{ctr_range[1]*100:.2f}%)."
        )

    insights = {
        "verdict_class": verdict_class,
        "headline": titled_headline,
        "one_liner": one_liner,
        "benchmark_note": benchmark_note,
        "headline_metrics": {
            "roi_p50_pct": round(mc.predicted_roi["p50"] * 100, 1),
            "roas_p50": mc.predicted_roas["p50"],
            "ctr_pct": round(float(sum(mc.sample_ctrs)
                                    / max(len(mc.sample_ctrs), 1)) * 100, 3),
            "conversions_p50": mc.predicted_conversions["p50"],
            "revenue_p50": mc.predicted_revenue["p50"],
            "audience_size": mc.audience_size,
            "segment": segment,
            "channel": channel or mc.channel,
            "budget": mc.budget,
        },
        "what_works": what_works,
        "what_holds_back": what_holds_back,
        "recommendations": _recommendations(mc, visual_result, ad,
                                             calibration),
        "caveats": _caveats(mc, visual_result, calibration),
    }
    insights["markdown"] = _build_markdown(insights)
    return insights
