"""Pipeline core -- shared between the Gradio UI and the static HTML report.

Plain-Python orchestration that runs the full simulator end-to-end and
returns its outputs as a dict. No UI-framework dependency, so both
``app.py`` (Gradio) and ``report.py`` (static HTML) can drive the same
engine.
"""
from __future__ import annotations

import gc
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from src.agent import AdStimulus, visual_weights_for
    from src.audience_match import AudienceMatch, match_audience
    from src.brief import CampaignBrief, CreativeAssets, validate_creative
    from src.calibration import load_calibration, run_calibration
    from src.charts import (click_factors_chart, daily_envelope_chart,
                            roi_distribution_chart, sensitivity_chart,
                            visual_scores_chart)
    from src.company_profile import CompanyProfile, parse_company
    from src.data_loader import BENCHMARK_BASE_RATES
    from src.explain import explain_simulation
    from src.personas import (AUDIENCE_SEGMENTS, filter_personas,
                              generate_personas, load_personas, save_personas)
    from src.platforms import get_format, list_platforms, platform_formats
    from src.simcal import fit_fatigue_theta
    from src.simulation import monte_carlo, sensitivity_sweep
    from src.visual_analysis import analyze_ad, available_providers  # noqa
except ImportError:                                # `python src/pipeline.py`
    from agent import AdStimulus, visual_weights_for
    from audience_match import AudienceMatch, match_audience
    from brief import CampaignBrief, CreativeAssets, validate_creative
    from calibration import load_calibration, run_calibration
    from charts import (click_factors_chart, daily_envelope_chart,
                        roi_distribution_chart, sensitivity_chart,
                        visual_scores_chart)
    from company_profile import CompanyProfile, parse_company
    from data_loader import BENCHMARK_BASE_RATES
    from explain import explain_simulation
    from personas import (AUDIENCE_SEGMENTS, filter_personas,
                          generate_personas, load_personas, save_personas)
    from platforms import get_format, list_platforms, platform_formats
    from simcal import fit_fatigue_theta
    from simulation import monte_carlo, sensitivity_sweep
    from visual_analysis import analyze_ad, available_providers  # noqa

__all__ = [
    "run_pipeline_core",
    "run_wizard_simulation",
    "get_resources",
    "format_headline_md",
    "format_visual_md",
    "VisionUnavailableError",
    "CHANNELS", "SEGMENTS", "CATEGORIES", "PROVIDERS",
    "DEFAULT_AD_TEXT", "DISCLAIMER",
]


class VisionUnavailableError(RuntimeError):
    """Raised when an image was supplied but no real vision model could
    inspect it (all providers exhausted/down), so the run is refused.

    A forecast for an image we never actually looked at can't confirm the
    creative is policy-safe or judge its quality, so we block rather than
    show a number we can't stand behind. Carries ``provider_error`` with the
    underlying per-provider failure detail for diagnostics.
    """

    def __init__(self, message: str, provider_error: str = ""):
        super().__init__(message)
        self.provider_error = provider_error

# ---------------------------------------------------------------------------
# UI option lists -- imported by app.py for dropdowns and report.py for CLI.
# ---------------------------------------------------------------------------
CHANNELS = list(BENCHMARK_BASE_RATES.keys())
SEGMENTS = list(AUDIENCE_SEGMENTS.keys())
CATEGORIES = ["general", "apparel", "electronics", "beauty", "home",
              "food_bev", "fitness", "travel", "finance", "auto",
              "entertainment"]
PROVIDERS = ["auto", "heuristic", "claude", "openai"]
DEFAULT_AD_TEXT = "Limited offer! Save 40% today -- loved by thousands."

DISCLAIMER = (
    "**Limitations.** Personas are synthetic (sampled from plausible "
    "distributions, not a real research panel). Channel CTRs and CPMs are "
    "directional industry ranges, not market quotes. p10-p90 bands reflect "
    "modelling uncertainty, not real-world confidence intervals. Treat "
    "outputs as a structured second opinion for comparing creatives and "
    "audiences -- always validate with a real-world test before committing "
    "significant spend."
)

_RESOURCES: tuple | None = None


def get_resources() -> tuple:
    """Lazy-load personas + calibration once per process."""
    global _RESOURCES
    if _RESOURCES is None:
        try:
            personas = load_personas()
        except FileNotFoundError:
            personas = generate_personas(1000)
            save_personas(personas)
        try:
            calibration = load_calibration()
        except FileNotFoundError:
            calibration = run_calibration()
        _RESOURCES = (personas, calibration)
    return _RESOURCES


# ===========================================================================
# Main pipeline
# ===========================================================================

def run_pipeline_core(image_path: str | None,
                      ad_text: str,
                      segment: str,
                      channel: str,
                      category: str,
                      budget: float,
                      sim_days: int,
                      n_runs: int,
                      daily_reach: float,
                      provider: str,
                      target_ctr_input: float,
                      target_conversion_rate: float,
                      progress_callback=None) -> dict:
    """Run analysis + simulation. Returns dict with markdown, figures, JSON.

    ``progress_callback`` is called as ``cb(fraction, description)`` so any
    UI (Gradio progress, CLI prints, etc.) can show status.
    """
    def _step(p, desc):
        if progress_callback is not None:
            progress_callback(p, desc)

    personas, calibration = get_resources()

    _step(0.05, "Scoring the creative...")
    if image_path:
        visual = analyze_ad(image_path, ad_text or "",
                            provider=provider, audience_hint=segment)
    else:
        visual = None

    _step(0.20, "Building ad stimulus...")
    visual_scores = (visual.scores if visual is not None
                     else {"emotional_arousal": 0.5, "visual_clarity": 0.5,
                           "attention_capture": 0.5,
                           "relevance_potential": 0.5})
    ad = AdStimulus.build(
        visual_scores=visual_scores,
        ad_text=ad_text or "",
        product_category=category,
        channel=channel,
    )

    _step(0.30, f"Filtering audience: {segment}...")
    audience = filter_personas(personas, segment)
    if len(audience) < 20:
        raise ValueError(
            f"Audience '{segment}' has only {len(audience)} personas -- "
            "regenerate a larger persona set first.")

    target_ctr = (target_ctr_input if target_ctr_input and
                  target_ctr_input > 0 else None)
    tcr = (target_conversion_rate if target_conversion_rate and
           target_conversion_rate > 0 else None)

    _step(0.40,
          f"Running Monte Carlo: {int(n_runs)} runs x {sim_days} days...")
    mc = monte_carlo(
        audience, ad, calibration,
        channel=channel, budget=budget, sim_days=sim_days,
        n_runs=int(n_runs), daily_reach=daily_reach,
        target_ctr=target_ctr, target_conversion_rate=tcr,
    )

    _step(0.75, "Running sensitivity sweeps...")
    small_runs = max(6, int(n_runs) // 2)
    budget_sweep = sensitivity_sweep(
        audience, ad, calibration, "budget",
        [round(budget * f) for f in (0.25, 0.5, 1.0, 2.0, 4.0)],
        base_kwargs={"sim_days": sim_days, "daily_reach": daily_reach,
                     "channel": channel, "target_ctr": target_ctr,
                     "target_conversion_rate": tcr},
        n_runs=small_runs,
    )
    reach_sweep = sensitivity_sweep(
        audience, ad, calibration, "daily_reach",
        [0.15, 0.30, 0.50, 0.70],
        base_kwargs={"sim_days": sim_days, "budget": budget,
                     "channel": channel, "target_ctr": target_ctr,
                     "target_conversion_rate": tcr},
        n_runs=small_runs,
    )

    _step(0.92, "Building explanation + charts...")
    insights = explain_simulation(
        mc, visual_result=visual, ad=ad,
        calibration=calibration, segment=segment, channel=channel,
    )

    figures = {
        "daily": daily_envelope_chart(mc, "clicks"),
        "roi": roi_distribution_chart(mc),
        "factors": click_factors_chart(mc.aggregate_click_factors),
        "visual": visual_scores_chart(visual),
        "sens_budget": sensitivity_chart(
            budget_sweep, "value", "mean_roas",
            "Budget ($)", "ROAS (x)", "ROAS vs budget"),
        "sens_reach": sensitivity_chart(
            reach_sweep, "value", "mean_ctr",
            "Daily reach (fraction)", "Sample CTR",
            "CTR vs daily reach (shows fatigue / saturation)"),
    }

    payload = {
        "monte_carlo": mc.to_dict(),
        "insights": insights,
        "visual_analysis": (visual.to_dict() if visual is not None
                            else None),
        "ad": {"text": ad.ad_text, "category": ad.product_category,
               "channel": ad.channel,
               "visual_scores": ad.visual_scores,
               "psychology_features": ad.psychology_features},
    }
    # The heavy daily records aren't useful in the visible JSON pane.
    payload["monte_carlo"].pop("daily_records_per_run", None)
    json_str = json.dumps(payload, indent=2, default=str)

    _step(1.0, "Done.")
    return {
        "headline_md": format_headline_md(mc, segment),
        "visual_md": format_visual_md(visual),
        "narrative_md": insights["markdown"],
        "figures": figures,
        "json_str": json_str,
        "mc": mc, "ad": ad, "visual": visual, "insights": insights,
    }


# ===========================================================================
# Markdown formatters (consumed by both Gradio markdown widgets and the
# tiny HTML renderer in report.py)
# ===========================================================================

def format_headline_md(mc, segment: str) -> str:
    roi, roas = mc.predicted_roi, mc.predicted_roas
    clicks = mc.predicted_clicks
    conv = mc.predicted_conversions
    rev = mc.predicted_revenue
    sample_ctr_pct = (sum(mc.sample_ctrs)
                      / max(len(mc.sample_ctrs), 1)) * 100
    return f"""
## Forecast -- {mc.channel}, {segment}, ${mc.budget:,.0f} over {mc.sim_days} days

| Metric | p10 | median | p90 |
|---|---:|---:|---:|
| Predicted clicks | {clicks['p10']:,.0f} | **{clicks['p50']:,.0f}** | {clicks['p90']:,.0f} |
| Predicted conversions | {conv['p10']:,.0f} | **{conv['p50']:,.0f}** | {conv['p90']:,.0f} |
| Predicted revenue | ${rev['p10']:,.0f} | **${rev['p50']:,.0f}** | ${rev['p90']:,.0f} |
| Predicted ROI | {roi['p10']*100:+.0f}% | **{roi['p50']*100:+.0f}%** | {roi['p90']*100:+.0f}% |
| Predicted ROAS | {roas['p10']:.2f}x | **{roas['p50']:.2f}x** | {roas['p90']:.2f}x |

Sample CTR (mean across {mc.n_runs} runs): **{sample_ctr_pct:.3f}%**  ·  total impressions bought: **{mc.total_impressions:,}**  ·  mean buyer AOV: **${mc.mean_aov:,.0f}**  ·  audience: **{mc.audience_size:,} personas**
""".strip()


def format_visual_md(visual_result) -> str:
    if visual_result is None:
        return ("_No image uploaded -- visual scores default to 0.5 across "
                "the board._")
    flag = (" _(heuristic fallback -- connect an API key for a multimodal "
            "score)_" if visual_result.is_heuristic else "")
    lines = [
        f"### Visual analysis -- `{visual_result.provider}/"
        f"{visual_result.model}`{flag}",
        "",
        f"_{visual_result.overall}_",
        "",
        "**Per-dimension reasoning:**",
    ]
    for key, score in visual_result.scores.items():
        rationale = visual_result.explanations.get(key, "").strip()
        lines.append(f"- **{key.replace('_',' ').title()}** "
                     f"({score:.2f}): {rationale}")
    if visual_result.strengths:
        lines += ["", "**Strengths:** "
                  + ", ".join(visual_result.strengths)]
    if visual_result.weaknesses:
        lines += ["", "**Weaknesses:** "
                  + ", ".join(visual_result.weaknesses)]
    return "\n".join(lines)


# ===========================================================================
# Wizard-aware pipeline -- the SaaS flow's entry point
# ===========================================================================

def _best_ad_text(assets: CreativeAssets) -> str:
    """Combine the creative copy into a single string for the visual tagger."""
    parts = [assets.headline, assets.primary_text, assets.description]
    return " ".join(p for p in parts if p).strip()


# Personas have a B2C-flavoured AOV (~$80 mean). For B2B / SaaS / agency a
# converted "buyer" represents an annual contract or project worth far more,
# so the AOV needs to scale up before we multiply by conversions.
_AOV_MULTIPLIERS: dict = {
    # by product_category
    "saas":                  25.0,   # $80 → ~$2000 ACV
    "marketing_agency":      30.0,   # $80 → ~$2400 project
    "professional_services": 20.0,   # $80 → ~$1600 engagement
    "finance":               10.0,   # banking / lending product
    "auto":                   8.0,   # purchase considered, lower funnel
    "travel":                 4.0,   # weekend break to international trip
    "electronics":            2.5,
    "home":                   1.8,
    "fitness":                1.5,
    "beauty":                 1.0,
    "apparel":                1.0,
    "food_bev":               0.6,   # impulse / consumable
    "entertainment":          0.5,
    "general":                1.0,
}


def _aov_multiplier_for_profile(profile: CompanyProfile) -> float:
    """Map a parsed CompanyProfile onto an AOV scaling factor. B2B businesses
    get a stronger bump even when the category mapper put them in 'general'."""
    base = _AOV_MULTIPLIERS.get(profile.product_category, 1.0)
    if profile.business_model == "b2b":
        base = max(base, 15.0)        # B2B floor: $80 × 15 = ~$1200 ACV
    if profile.price_position == "luxury":
        base *= 3.0
    elif profile.price_position == "premium":
        base *= 1.8
    return base


def _parse_ratio(s: str) -> float | None:
    try:
        w, h = s.split(":")
        return float(w) / float(h)
    except Exception:
        return None


def _orientation(r: float) -> str:
    if r < 0.9:
        return "vertical"
    if r > 1.15:
        return "horizontal"
    return "square"


def check_image_specs(image_path, fmt):
    """Cheap, NO-API pre-flight on an image creative. Confirms the file opens
    and that its orientation can actually run on this placement. If a creative
    fundamentally can't be published here (corrupt file, or a landscape photo
    on a vertical-only Reel), there's nothing worth forecasting — so we refuse
    BEFORE spending a vision-model call. Returns (hard_error|None, warnings).
    """
    from PIL import Image
    warnings: list = []
    try:
        with Image.open(image_path) as im:
            im.verify()                       # detects truncation/corruption
        with Image.open(image_path) as im:
            w, h = im.size
    except FileNotFoundError:
        # Specific: the upload is gone (typically a Railway redeploy wiped
        # the ephemeral upload dir). Telling the user the file is "corrupt"
        # here is wrong and wastes their time — be honest about the cause.
        return ("Your uploaded image is no longer on the server, so we "
                "couldn't analyse it. Uploads are held in temporary storage "
                "that's cleared when the app restarts or redeploys — the file "
                "can vanish between uploading it and running the forecast. "
                "Please re-upload the image and run it again."), warnings
    except Exception as exc:                  # noqa: BLE001
        return (f"We couldn't open this image — it looks corrupt or is an "
                f"unsupported file type. Upload a valid JPG/PNG/WebP, then "
                f"re-run. (detail: {str(exc)[:80]})"), warnings
    if not w or not h:
        return "This image reports no dimensions — it may be corrupt.", warnings

    allowed = [r for r in (_parse_ratio(s) for s in (fmt.aspect_ratios or ())) if r]
    if not allowed:
        return None, warnings                 # no ratio constraint for this format

    img_ratio = w / h
    if any(abs(img_ratio - r) / r <= 0.20 for r in allowed):
        return None, warnings                 # close enough to an allowed ratio

    img_o = _orientation(img_ratio)
    allowed_os = sorted({_orientation(r) for r in allowed})
    nice = ", ".join(fmt.aspect_ratios)
    # Hard block ONLY on a clear orientation clash (square stays lenient).
    if img_o != "square" and img_o not in allowed_os and "square" not in allowed_os:
        return (f"This image is {img_o} ({w}×{h}px), but {fmt.name} needs a "
                f"{'/'.join(allowed_os)} creative ({nice}). It can't run properly "
                f"on this placement, so there's no point analysing it — crop or "
                f"replace it, then re-run."), warnings
    warnings.append({"severity": "warning",
        "message": f"Image is {w}×{h}px (ratio {img_ratio:.2f}); {fmt.name} prefers "
                   f"{nice}. It'll be cropped to fit — check the framing."})
    return None, warnings


def _resolve_creative_for_visual(assets: CreativeAssets):
    """Pick the file to send to the visual analyser.

    Returns ``(kind, path)`` where kind is 'video', 'image', or None.
    Videos are analysed via Gemini's native video ingest (Phase 6); images
    via the multi-provider scorer.
    """
    if assets.video_path:
        return "video", assets.video_path
    if assets.image_path:
        return "image", assets.image_path
    return None, None


def run_wizard_simulation(profile: CompanyProfile,
                          match: AudienceMatch,
                          brief: CampaignBrief,
                          assets: CreativeAssets,
                          *,
                          visual_provider: str = "auto",
                          progress_callback=None) -> dict:
    """End-to-end pipeline for the new wizard flow.

    Returns the same dict shape as ``run_pipeline_core`` (markdown, figures,
    JSON, mc, ad, visual, insights) **plus** ``profile``, ``match``, ``brief``,
    ``assets``, ``validation`` so the UI can render context-rich panels.
    """
    def _step(p, desc):
        if progress_callback is not None:
            progress_callback(p, desc)

    personas, calibration = get_resources()
    fmt = brief.format

    _step(0.05, f"Validating the creative against {fmt.name}...")
    validation = validate_creative(brief, assets)
    blocking = [v for v in validation if v["severity"] == "error"]
    if blocking:
        raise ValueError("; ".join(v["message"] for v in blocking))

    ad_text_combined = _best_ad_text(assets)
    creative_kind, creative_source = _resolve_creative_for_visual(assets)

    # Tier 2: when the wizard uploaded straight to Supabase Storage,
    # creative_source is a signed URL — not a local path. Download it
    # ONCE per run into a per-request temp file the rest of the pipeline
    # (PIL specs check + vision providers) can read like any local file.
    # The RemoteFile context manager guarantees the temp file is deleted
    # even if a later step raises, so the worker never accumulates state.
    try:
        from src.storage import RemoteFile
    except ImportError:                                   # `python src/...`
        from storage import RemoteFile

    with RemoteFile(creative_source) as creative_path:
        return _run_simulation_inner(
            profile=profile, match=match, brief=brief, assets=assets,
            fmt=fmt, ad_text_combined=ad_text_combined,
            creative_kind=creative_kind, creative_path=creative_path,
            validation=validation, _step=_step,
            visual_provider=visual_provider, personas=personas,
            calibration=calibration,
        )


def _run_simulation_inner(*, profile, match, brief, assets, fmt,
                           ad_text_combined, creative_kind, creative_path,
                           validation, _step, visual_provider,
                           personas, calibration):
    """The bulk of run_wizard_simulation, factored so the parent function
    can wrap it in a RemoteFile context (Tier 2). Same return shape.

    ``creative_path`` here is ALWAYS a local Path (or None) — the URL
    download already happened upstream.
    """
    image_path = creative_path if creative_kind == "image" else None
    video_path = creative_path if creative_kind == "video" else None

    # Platform-spec pre-flight (cheap, NO API): if an image was supplied,
    # confirm it can actually RUN on this placement before we spend a vision
    # call. A corrupt file or a wrong-orientation creative is unpublishable, so
    # analysing it would just burn API on an ad that can never go live.
    if image_path:
        spec_error, spec_warnings = check_image_specs(image_path, fmt)
        if spec_error:
            raise ValueError(spec_error)      # 400 to the client; no API spent
        validation.extend(spec_warnings)

    # Geo-aware lens: tell the vision model which market this ad is for so it
    # flags tone / spelling / cultural mismatches for that audience (e.g. US
    # exclamation-mark hype reads as cringe to a UK audience; "color" vs
    # "colour"; references that don't translate across markets).
    geo = getattr(brief, "geo", "UK") or "UK"
    audience_hint = (
        f"{match.rationale or match.segment}. "
        f"Target market: {geo}. Evaluate this creative specifically for a "
        f"{geo} audience — flag any tone, spelling, idiom, or cultural "
        f"references that won't land (or could offend) in {geo}."
    )

    _step(0.15, "Scoring the creative on the four visual dimensions...")
    # Multi-placement cache: when the wizard runs the same creative against
    # multiple formats in one go (Reels + In-Feed Video + Facebook Reels),
    # the vision read is identical — image content, copy, brand all the
    # same — so reuse the first call's result. Stops the 'two void, one
    # runnable for the same creative' inconsistency AND saves ~66% of
    # Gemini cost on multi-placement runs.
    try:
        from src.vision_cache import (vision_cache_key, get_cached_vision,
                                       set_cached_vision)
    except ImportError:                                                # standalone
        from vision_cache import (vision_cache_key, get_cached_vision,
                                   set_cached_vision)
    _vc_key = vision_cache_key(
        creative_path, ad_text_combined, audience_hint,
        profile.product_category, profile.industry)
    visual = get_cached_vision(_vc_key) if _vc_key else None

    if visual is None:
        if video_path:
            from src.visual_analysis import analyze_ad_video    # noqa
            visual = analyze_ad_video(
                video_path, ad_text_combined,
                audience_hint=audience_hint,
                brand_category=profile.product_category,
                brand_industry=profile.industry,
            )
        elif image_path:
            visual = analyze_ad(
                image_path, ad_text_combined,
                provider=visual_provider, audience_hint=audience_hint,
                brand_category=profile.product_category,
                brand_industry=profile.industry,
            )
            # Second pair of eyes on the ban-screen: AWS Rekognition's
            # specialised moderation model. Opt-in (silent skip if no AWS
            # keys). Belt + braces — a creative has to clear BOTH Gemini's
            # read AND Rekognition.
            try:
                from src.safety_aws import screen_image_aws, merge_ban_risk
                aws_risk = screen_image_aws(image_path)
                if aws_risk and visual is not None:
                    gemini_risk = visual.ban_risk or {}
                    visual.ban_risk = merge_ban_risk(gemini_risk, aws_risk)
            except Exception:                                              # noqa: BLE001
                pass    # AWS check is best-effort — never break a run on it
        else:
            visual = None
        # Cache only NON-heuristic results — a heuristic fallback is the
        # 'vision was unavailable' state, not a stable answer worth reusing.
        if (visual is not None and _vc_key
                and not getattr(visual, "is_heuristic", True)):
            set_cached_vision(_vc_key, visual)

    # SAFETY GATE — refuse the forecast if a creative was supplied but no real
    # vision model could inspect it. Without actually seeing the image/video
    # we can't screen for policy violations or judge quality; pretending we did
    # would be exactly the kind of overclaim this product exists to prevent.
    if creative_path and visual is not None and visual.is_heuristic:
        kind_word = "video" if creative_kind == "video" else "image"
        perr = getattr(visual, "provider_error", "") or ""
        perr_l = perr.lower()
        # Distinguish the cause — a MISSING upload file is NOT a quota problem,
        # and telling the user to add a Gemini key (which won't help) sends them
        # down the wrong path. Uploaded files live on the server's temporary
        # disk, which is wiped on restart/redeploy, so a file can vanish between
        # upload and analysis.
        file_missing = ("not found" in perr_l or "no such file" in perr_l
                        or "errno 2" in perr_l)
        if file_missing:
            raise VisionUnavailableError(
                f"Your uploaded {kind_word} is no longer on the server, so we "
                f"couldn't analyse it. Uploads are held in temporary storage "
                f"that's cleared when the app restarts or redeploys — the file "
                f"can vanish between uploading it and running the forecast. "
                f"Please re-upload the {kind_word} and run it again.",
                provider_error=perr,
            )
        watch_word = "watching" if creative_kind == "video" else "seeing"
        # Distinguish a malformed-JSON response (the model returned garbled
        # JSON for THIS specific creative — retrying usually works) from a
        # genuine quota / unavailable signal (waiting won't help, the user
        # needs to add a key). Telling the user "wait for quota" when the
        # actual cause was a one-off parse blip would be misleading.
        perr_l = perr.lower()
        is_parse = ("malformed json" in perr_l
                    or "json" in perr_l and "decode" in perr_l
                    or "expecting" in perr_l
                    or "no json object" in perr_l
                    or "unbalanced json" in perr_l)
        if is_parse:
            raise VisionUnavailableError(
                f"We couldn't analyse your {kind_word} — the analysis service "
                f"returned an unexpected response on this attempt. This is "
                f"usually a one-off; please try again. Without actually "
                f"{watch_word} the {kind_word} we can't confirm it's policy-"
                f"safe or judge its quality, so we won't show a forecast we "
                f"can't stand behind.",
                provider_error=perr,
            )
        raise VisionUnavailableError(
            f"We couldn't analyse your {kind_word} — the analysis service is "
            "temporarily unavailable (free-tier quota likely used up). We "
            f"won't show a forecast we can't stand behind: without actually "
            f"{watch_word} the {kind_word} we can't confirm it's policy-safe or "
            "judge its quality. Please try again in a few minutes, or add "
            "your own Gemini API key in Settings.",
            provider_error=perr,
        )

    # Reel Quality Rubric — short-video craft scorecard (hook / sound-off /
    # pain-benefit / pacing / emotion + actionable suggestions). Video-only,
    # one extra Gemini call, ~£0.002 per 30s reel. Silently skipped for
    # images, when ADPROOF_REEL_QUALITY_ENABLED=0, or when Gemini is down.
    # NOT a virality signal — labelled as paid-ad craft quality in the UI.
    reel_quality = None
    script_critique = None
    if video_path and visual is not None and not visual.is_heuristic:
        # MEMORY: free the main vision pass's video bytes + genai client
        # state BEFORE loading the file again for the reel-quality call,
        # otherwise the two video buffers + two genai clients pile on the
        # Mesa model and OOM-kill the Railway worker (the 502 root cause).
        gc.collect()
        try:
            from src.reel_quality import score_reel_quality
        except ImportError:                               # `python src/...`
            from reel_quality import score_reel_quality
        # Phase 1: build the 2026 context block injected into VIE's prompt
        # — industry baseline + platform demographics + trend signals.
        # Best-effort; an import or lookup failure must NEVER block the run.
        _ctx_block = ""
        try:
            try:
                from src.benchmarks import (industry_platform_engagement,
                                             platform_2026_context,
                                             trends_2026_for_prompt)
                from src.industry_classifier import map_to_rival_iq_industry
            except ImportError:
                from benchmarks import (industry_platform_engagement,
                                         platform_2026_context,
                                         trends_2026_for_prompt)
                from industry_classifier import map_to_rival_iq_industry
            from src.reel_quality import _format_2026_context
            ind_slug = map_to_rival_iq_industry(
                product_category=profile.product_category,
                industry=profile.industry,
                business_model=profile.business_model,
                what_they_sell=getattr(profile, "what_they_sell", None),
                value_proposition=profile.value_proposition,
                company_name=profile.company_name,
            )
            ind_lookup = (industry_platform_engagement(
                ind_slug, brief.platform_id).to_dict()
                if ind_slug else None)
            plat_lookup = platform_2026_context(brief.platform_id).to_dict()
            trends_lookup = trends_2026_for_prompt(max_trends=4).value or {}
            _ctx_block = _format_2026_context(
                ind_lookup if ind_lookup and ind_lookup.get("found") else None,
                plat_lookup if plat_lookup.get("found") else None,
                trends_lookup,
            )
        except Exception:                                 # noqa: BLE001
            _ctx_block = ""
        try:
            reel_quality = score_reel_quality(
                video_path, ad_text_combined,
                platform_label=getattr(fmt, "platform_name", "") or "",
                audience_hint=audience_hint,
                objective=brief.objective,
                context_block=_ctx_block,
            )
        except Exception:                                 # noqa: BLE001
            reel_quality = None         # never fail the run on the extra pass

        # Phase C: talking-head script critic — only runs when the main
        # vision pass tagged the creative as talking_head. One Gemini call,
        # ~£0.002 per 30s clip, totally skipped otherwise (so a b-roll
        # video doesn't waste tokens on transcription).
        if (visual.creative_type or "").lower() == "talking_head":
            gc.collect()                  # same memory-pressure reasoning
            try:
                from src.script_critic import critique_talking_head
            except ImportError:
                from script_critic import critique_talking_head
            try:
                script_critique = critique_talking_head(
                    video_path, objective=brief.objective)
            except Exception:                             # noqa: BLE001
                script_critique = None    # never fail the run on the critic

    # Session 1: LinkedIn-specific critic (Socivo + LDA). Runs only when the
    # placement is LinkedIn. Cheap text-only Gemini call, ~£0.003.
    linkedin_critique = None
    try:
        from src.linkedin_critic import critique_linkedin, is_linkedin_platform
    except ImportError:                                   # `python src/...`
        from linkedin_critic import critique_linkedin, is_linkedin_platform
    if is_linkedin_platform(brief.platform_id):
        try:
            linkedin_critique = critique_linkedin(
                headline=assets.headline,
                primary_text=assets.primary_text,
                description=assets.description,
                cta=assets.cta,
                link=assets.link,
                objective=brief.objective,
                platform_id=brief.platform_id,
                audience_hint=audience_hint,
                industry=profile.industry or profile.product_category or "",
                geo=getattr(brief, "geo", "UK") or "UK",
                image_path=image_path,
                video_path=video_path,
            )
        except Exception:                                  # noqa: BLE001
            linkedin_critique = None      # never fail the run on the critic

    # Session 2: Meta-specific critic (Socivo). Runs only on Meta placements.
    # Focuses on offer strength + message-market fit + creative-as-targeting
    # — the levers VIE and the LinkedIn critic don't touch.
    meta_critique = None
    try:
        from src.meta_critic import critique_meta, is_meta_platform
    except ImportError:
        from meta_critic import critique_meta, is_meta_platform
    if is_meta_platform(brief.platform_id):
        try:
            meta_critique = critique_meta(
                headline=assets.headline,
                primary_text=assets.primary_text,
                description=assets.description,
                cta=assets.cta,
                link=assets.link,
                objective=brief.objective,
                platform_id=brief.platform_id,
                audience_hint=audience_hint,
                industry=profile.industry or profile.product_category or "",
                geo=getattr(brief, "geo", "UK") or "UK",
                avg_order_value=getattr(brief, "avg_order_value", None),
                image_path=image_path,
                video_path=video_path,
            )
        except Exception:                                  # noqa: BLE001
            meta_critique = None

    # Vision (esp. the video path, which buffers the clip + the genai client)
    # can leave tens of MB resident; release it BEFORE the memory-heavy Monte
    # Carlo so the two peaks don't stack and OOM a small instance.
    gc.collect()

    _step(0.25, "Building ad stimulus...")
    visual_scores = (visual.scores if visual is not None
                     else {"emotional_arousal": 0.5, "visual_clarity": 0.5,
                           "attention_capture": 0.5,
                           "relevance_potential": 0.5})
    ad = AdStimulus.build(
        visual_scores=visual_scores,
        ad_text=ad_text_combined,
        product_category=profile.product_category,
        channel=fmt.simulation_channel,
    )

    _step(0.35, f"Filtering audience to '{match.segment}'...")
    audience = filter_personas(personas, match.segment)
    if len(audience) < 20:
        # Re-run with the broader "all" segment as a graceful fallback.
        audience = filter_personas(personas, "all")

    # Economics: the advertiser's REAL average order value wins. Only fall
    # back to the crude category multiplier when they haven't told us.
    aov_override = brief.avg_order_value
    aov_mult = 1.0 if aov_override else _aov_multiplier_for_profile(profile)

    # Objective-aware creative weighting: an awareness ad rewards different
    # axes than a conversion ad, so the same visual scores feed the click
    # logit through different weights depending on brief.objective.
    obj_visual_weights = visual_weights_for(brief.objective)

    # Simulation-based calibration: when the account has a fitted fatigue
    # decay (lambda, observed ln-CTR slope per unit frequency), bisect for
    # the engine constant whose SIMULATED decay reproduces it. Pasting
    # lambda into the logit directly understates fatigue ~2× (the sigmoid
    # squashes it) — see src/simcal.py and scripts/test_simcal.py.
    # lam == 0 means the account fit was floored (CTR rising with frequency
    # = confounding — "not identified", NOT "no fatigue"): keep the generic
    # constant rather than switching fatigue off and calling it calibration.
    fatigue_theta = None
    fatigue_fit = None
    lam = getattr(brief, "fatigue_lambda", None)
    if lam is not None and lam > 0:
        try:
            fatigue_fit = fit_fatigue_theta(
                lambda_target=float(lam), audience=audience, ad=ad,
                calibration=calibration, channel=fmt.simulation_channel,
                target_ctr=brief.effective_target_ctr)
            fatigue_theta = fatigue_fit["theta"]
        except Exception:                                  # noqa: BLE001
            fatigue_theta = None    # generic constant stays in charge

    _step(0.45,
          f"Running Monte Carlo: {brief.n_runs} runs x {brief.days} days...")
    mc = monte_carlo(
        audience, ad, calibration,
        channel=fmt.simulation_channel,
        budget=brief.budget, sim_days=brief.days,
        n_runs=brief.n_runs, daily_reach=brief.daily_reach,
        target_ctr=brief.effective_target_ctr,
        target_conversion_rate=brief.target_conversion_rate,
        cpm_override=brief.effective_cpm,
        reachable_audience=brief.reachable_audience,
        aov_multiplier=aov_mult,
        aov_override=aov_override,
        visual_weights=obj_visual_weights,
        fatigue_per_exposure=fatigue_theta,
    )

    _step(0.78, "Running sensitivity sweeps (budget + reach)...")
    small_runs = max(6, brief.n_runs // 2)
    budget_sweep = sensitivity_sweep(
        audience, ad, calibration, "budget",
        [round(brief.budget * f) for f in (0.25, 0.5, 1.0, 2.0, 4.0)],
        base_kwargs={"sim_days": brief.days,
                     "daily_reach": brief.daily_reach,
                     "channel": fmt.simulation_channel,
                     "target_ctr": brief.effective_target_ctr,
                     "target_conversion_rate": brief.target_conversion_rate,
                     "cpm_override": brief.effective_cpm,
                     "reachable_audience": brief.reachable_audience,
                     "aov_multiplier": aov_mult,
                     "aov_override": aov_override,
                     "visual_weights": obj_visual_weights},
        n_runs=small_runs,
    )
    reach_sweep = sensitivity_sweep(
        audience, ad, calibration, "daily_reach",
        [0.15, 0.30, 0.50, 0.70],
        base_kwargs={"sim_days": brief.days, "budget": brief.budget,
                     "channel": fmt.simulation_channel,
                     "target_ctr": brief.effective_target_ctr,
                     "target_conversion_rate": brief.target_conversion_rate,
                     "cpm_override": brief.effective_cpm,
                     "reachable_audience": brief.reachable_audience,
                     "aov_multiplier": aov_mult,
                     "aov_override": aov_override,
                     "visual_weights": obj_visual_weights},
        n_runs=small_runs,
    )

    _step(0.92, "Building explanation + charts...")
    insights = explain_simulation(
        mc, visual_result=visual, ad=ad,
        calibration=calibration,
        segment=match.segment, channel=fmt.platform_name,
        context={"profile": profile, "match": match,
                 "brief": brief, "format": fmt},
    )

    figures = {
        "daily": daily_envelope_chart(mc, "clicks"),
        "roi": roi_distribution_chart(mc),
        "factors": click_factors_chart(mc.aggregate_click_factors),
        "visual": visual_scores_chart(visual),
        "sens_budget": sensitivity_chart(
            budget_sweep, "value", "mean_roas",
            "Budget ($)", "ROAS (x)", "ROAS vs budget"),
        "sens_reach": sensitivity_chart(
            reach_sweep, "value", "mean_ctr",
            "Daily reach (fraction)", "Sample CTR",
            "CTR vs daily reach (shows fatigue / saturation)"),
    }

    headline_md = format_headline_md(mc, match.segment)
    visual_md = format_visual_md(visual)

    payload = {
        "company": profile.to_dict(),
        "audience_match": match.to_dict(),
        "brief": brief.to_dict(),
        "format": {"id": fmt.id, "name": fmt.name,
                   "platform": fmt.platform_name,
                   "benchmarks": fmt.benchmarks},
        "monte_carlo": mc.to_dict(),
        "insights": insights,
        "visual_analysis": (visual.to_dict() if visual is not None
                            else None),
        "ad": {"text": ad.ad_text, "category": ad.product_category,
               "channel": ad.channel,
               "visual_scores": ad.visual_scores,
               "psychology_features": ad.psychology_features},
    }
    payload["monte_carlo"].pop("daily_records_per_run", None)
    json_str = json.dumps(payload, indent=2, default=str)

    # Visual Prominence (Moat Step 2): spectral-residual saliency heatmap on
    # the image creative. Pure numpy/PIL, gc'd. Defensive — never fail the run.
    visual_prominence = None
    if image_path:
        try:
            try:
                from src.visual_prominence import analyze_visual_prominence
            except ImportError:
                from visual_prominence import analyze_visual_prominence
            vp = analyze_visual_prominence(image_path)
            visual_prominence = vp if vp.get("found") else None
        except Exception:                                  # noqa: BLE001
            visual_prominence = None

    _step(1.0, "Done.")
    return {
        "headline_md": headline_md,
        "visual_md": visual_md,
        "narrative_md": insights["markdown"],
        "figures": figures,
        "json_str": json_str,
        "mc": mc, "ad": ad, "visual": visual, "insights": insights,
        "profile": profile, "match": match, "brief": brief,
        "assets": assets, "validation": validation,
        "reel_quality": reel_quality,
        "script_critique": script_critique,
        "linkedin_critique": linkedin_critique,
        "meta_critique": meta_critique,
        "visual_prominence": visual_prominence,
        # Simulation-based calibration provenance: how the account's observed
        # fatigue decay was converted into the engine constant (None = the
        # generic 0.10 default ran).
        "fatigue_fit": fatigue_fit,
    }
