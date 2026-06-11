"""Reel Quality — short-video creative critic powered by the Virality
Intelligence Engine (VIE) rubric.

Replaces the old 5-axis Reel Quality with an 8-dimension VIE-based
scorer ON THE SAME Gemini call. The owner's "virality-intelligence-
engine" skill (saved in /Users/debs/Downloads/...) is the authoritative
prompt; we encode its 8 dimensions, calibration rule ("never above 85
unless exceptional"), hook autopsy with alt-hooks, viral pattern
detection, algorithm-risk analysis, and the final "publish today
YES/NO" verdict.

Honest framing — must be enforced in the UI:
    VIE predicts ORGANIC short-form virality dimensions (hook strength,
    retention, emotional pull). Those dimensions correlate with paid-ad
    craft quality, but a high VIE score does NOT guarantee paid CTR or
    ROAS. The result-page card carries this caveat at the bottom.

Cost: one Gemini call per video, ~£0.004 per 30s reel at 2.5 Flash
rates (slightly higher than the old 5-axis version because the prompt
+ output is denser). Same cache + gating as before.

Phase 1 also injects 2026 context (Hootsuite trends + Sprout platform
section + Rival IQ industry baseline) so the model is current.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Allow direct execution for ad-hoc testing.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import GEMINI_VISION_CHAIN  # noqa: E402

try:
    from src.visual_analysis import (_VIDEO_MIME_TYPES, _MAX_VIDEO_BYTES,
                                     _VISION_EXHAUSTED, _get_key,
                                     _is_quota_error, _ph_ok, _ph_quota)
except ImportError:                                    # standalone
    from visual_analysis import (_VIDEO_MIME_TYPES, _MAX_VIDEO_BYTES,
                                 _VISION_EXHAUSTED, _get_key,
                                 _is_quota_error, _ph_ok, _ph_quota)

__all__ = [
    "ReelQualityResult",
    "score_reel_quality",
    "VIE_DIMENSIONS",
    "VIE_DIMENSION_MAX",
    "is_video_path",
]


# VIE's 8 weighted dimensions. Max scores per the skill rubric:
# Attention 15 / Curiosity 15 / Emotion 15 / Retention 20 / Shareability 10
# / Saveability 10 / Uniqueness 10 / Platform Fit 5 = 100.
VIE_DIMENSIONS = (
    "attention",
    "curiosity",
    "emotion",
    "retention",
    "shareability",
    "saveability",
    "uniqueness",
    "platform_fit",
)
VIE_DIMENSION_MAX = {
    "attention":     15,
    "curiosity":     15,
    "emotion":       15,
    "retention":     20,
    "shareability":  10,
    "saveability":   10,
    "uniqueness":    10,
    "platform_fit":  5,
}
# Sanity check at import: weights sum to 100.
assert sum(VIE_DIMENSION_MAX.values()) == 100


@dataclass
class ReelQualityResult:
    """VIE scorecard + hook autopsy + algorithm risk + verdict."""
    # Scorecard
    scores: dict                       # 8 dims, each 0..VIE_DIMENSION_MAX[k]
    composite: float                   # 0-100, simple sum of sub-scores
    grade: str                         # A/B/C/D for the composite
    explanations: dict                 # one-line "why this score" per dim
    # Diagnosis
    biggest_strength: str = ""
    biggest_weakness: str = ""
    drop_off_point: str = ""
    # Hook autopsy
    hook_score: int = 0                # /10 — VIE Step 7
    hook_alternatives: list = field(default_factory=list)
    # Viral pattern
    viral_pattern: str = ""
    # Algorithm risk
    algorithm_risk: dict = field(default_factory=dict)   # 10 axes → low/med/high
    # Final verdict
    publish_verdict: str = ""          # "YES" / "NO"
    publish_changes_required: list = field(default_factory=list)
    # Provenance
    provider: str = "gemini"
    model: str = ""
    is_skipped: bool = False
    skipped_reason: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are an elite content analyst (the Virality Intelligence "
    "Engine v1.0) scoring short-form video for use as a PAID AD. "
    "You score ORGANIC-craft potential — hook, retention, emotional pull, "
    "uniqueness — because those dimensions correlate with paid-ad creative "
    "quality. You are NOT scoring paid CTR / ROAS / conversions and you "
    "do NOT block creatives from being published. Paid distribution can "
    "carry a creative that would never survive an organic feed.\n\n"
    "CALIBRATION (NON-NEGOTIABLE): Never give a composite above 85 "
    "unless the content has a genuinely exceptional hook, strong "
    "curiosity, emotional pull AND a clear retention mechanism. Most "
    "content scores between 40 and 80. Reserve 90+ for content that "
    "could realistically compete with top creators in its niche.\n\n"
    "TONE: Be ruthlessly honest about weaknesses, but frame suggestions "
    "as 'how to strengthen the creative for paid' — NEVER 'do not "
    "publish'. The user has already decided to ship paid; your job is "
    "to make it better, not gatekeep it.\n\n"
    "Respond ONLY with the requested JSON, no prose outside."
)


def _format_2026_context(industry_engagement, platform_2026, hootsuite_trends) -> str:
    """Format the 2026-context snippet for injection into the user prompt.
    All inputs may be None — we degrade silently.
    """
    parts = []
    if hootsuite_trends:
        parts.append("HOOTSUITE 2026 TRENDS that should shape your read:")
        for t in (hootsuite_trends.get("trends") or [])[:4]:
            tk = (t.get("takeaways") or [""])[0] if t.get("takeaways") else ""
            parts.append(f"  • Trend {t.get('n')}: {t.get('title')}"
                         + (f" — {tk[:160]}" if tk else ""))
        hd = hootsuite_trends.get("headline_stats") or {}
        if hd.get("consumers_less_likely_if_ads_ai_generated_pct"):
            parts.append(
                f"  • {hd['consumers_less_likely_if_ads_ai_generated_pct']}% of "
                f"consumers are LESS likely to buy if they know the ad is "
                f"AI-generated (Hootsuite 2026). Penalise obvious AI slop "
                f"heavily on Uniqueness + Emotion."
            )
    if industry_engagement:
        eng = industry_engagement.get("value", {})
        if eng:
            parts.append(
                f"\nINDUSTRY BASELINE: {eng.get('industry', '?')} on "
                f"{eng.get('platform', '?')} runs at "
                f"{(eng.get('engagement_rate') or 0) * 100:.3f}% organic "
                f"engagement (Rival IQ 2025, {eng.get('data_year', '?')} "
                f"data). Use this as the niche-norm anchor — content well "
                f"below this is failing on Attention or Platform Fit."
            )
    if platform_2026 and platform_2026.get("value"):
        text = platform_2026["value"].get("text", "")[:1200]
        if text:
            parts.append(
                f"\nPLATFORM-SPECIFIC 2026 CONTEXT (Sprout Social):\n{text}"
            )
    return "\n".join(parts) if parts else ""


def _user_prompt(ad_text: str, platform_label: str = "",
                  audience_hint: str = "", objective: str = "",
                  context_block: str = "") -> str:
    parts = []
    parts.append(
        "Apply the Virality Intelligence Engine v1.0 to the attached "
        "short video. Score for PAID-AD use on the following platform "
        "+ audience + objective.")
    if platform_label:
        parts.append(f"Platform: {platform_label}")
    if audience_hint:
        parts.append(f"Intended audience: {audience_hint[:300]}")
    if objective:
        parts.append(f"Campaign objective: {objective}")
    parts.append(f'Ad copy / on-screen text: "{ad_text.strip()}"' if ad_text.strip()
                 else "Ad copy: (none — judge the video alone)")
    if context_block:
        parts.append(f"\n--- 2026 CONTEXT FOR THE CRITIQUE ---\n{context_block}")
    parts.append(
        "\n--- TASK ---\n"
        "Score on the 8 VIE dimensions (each integer up to its max), "
        "produce a hook autopsy, classify the viral pattern, rate 10 "
        "algorithm risks, and give the final publish verdict. Return "
        "EXACTLY this JSON (no extra keys, no prose outside):\n\n"
        "{\n"
        "  \"scores\": {\n"
        "    \"attention\":     int 0-15,   // scroll-stopping power, first sentence/hook strength, pattern interrupt\n"
        "    \"curiosity\":     int 0-15,   // open loops, information gaps, mystery\n"
        "    \"emotion\":       int 0-15,   // surprise/fear/aspiration/validation/humour/inspiration\n"
        "    \"retention\":     int 0-20,   // flow, momentum, tension-payoff structure\n"
        "    \"shareability\":  int 0-10,   // relatability, identity signal, send-to-a-friend factor\n"
        "    \"saveability\":   int 0-10,   // reference value, actionable advice worth returning to\n"
        "    \"uniqueness\":    int 0-10,   // fresh framing vs saturated formats\n"
        "    \"platform_fit\":  int 0-5     // native conventions for THIS platform\n"
        "  },\n"
        "  \"explanations\": {\n"
        "    \"attention\":    \"one short sentence — cite a concrete moment\",\n"
        "    \"curiosity\":    \"...\", \"emotion\": \"...\", \"retention\": \"...\",\n"
        "    \"shareability\": \"...\", \"saveability\": \"...\",\n"
        "    \"uniqueness\":   \"...\", \"platform_fit\": \"...\"\n"
        "  },\n"
        "  \"biggest_strength\": \"the single strongest viral component\",\n"
        "  \"biggest_weakness\": \"the factor most limiting performance\",\n"
        "  \"drop_off_point\":   \"WHERE viewers will exit + WHY\",\n"
        "  \"hook_score\": int 0-10,\n"
        "  \"hook_alternatives\": [\n"
        "    {\"hook\": \"new opening line\", \"reason\": \"why it's stronger\"},\n"
        "    {\"hook\": \"...\", \"reason\": \"...\"},\n"
        "    {\"hook\": \"...\", \"reason\": \"...\"}\n"
        "  ],\n"
        "  \"viral_pattern\": \"one of: Curiosity / Story / Transformation / Warning / Mistake / Secret / Contrarian / Prediction / Tutorial / List / Controversy / Case Study\",\n"
        "  \"algorithm_risk\": {\n"
        "    \"too_generic\":    \"Low|Medium|High\",\n"
        "    \"too_educational\":\"Low|Medium|High\",\n"
        "    \"too_broad\":      \"Low|Medium|High\",\n"
        "    \"too_niche\":      \"Low|Medium|High\",\n"
        "    \"weak_payoff\":    \"Low|Medium|High\",\n"
        "    \"weak_story\":     \"Low|Medium|High\",\n"
        "    \"low_emotion\":    \"Low|Medium|High\",\n"
        "    \"low_novelty\":    \"Low|Medium|High\",\n"
        "    \"low_curiosity\":  \"Low|Medium|High\",\n"
        "    \"low_tension\":    \"Low|Medium|High\"\n"
        "  },\n"
        "  \"publish_verdict\": \"YES\" or \"NO\",\n"
        "  \"publish_changes_required\": [\n"
        "    \"if NO, the SPECIFIC minimum change required before publishing\",\n"
        "    \"...\"\n"
        "  ]\n"
        "}\n\n"
        "Be harsh where harshness is warranted. Compose the composite "
        "as the sum of the 8 sub-scores (max 100). Remember: composites "
        "above 85 are reserved for genuinely exceptional content."
    )
    return "\n\n".join(parts)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    if not text:
        raise ValueError("Empty response.")
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError(f"No JSON object found: {text[:200]}")
    return json.loads(m.group(0))


def _clip_score(v, max_val: int) -> int:
    try:
        return max(0, min(max_val, int(round(float(v)))))
    except (TypeError, ValueError):
        return max_val // 2


def _compute_composite(scores: dict) -> float:
    return float(sum(scores.get(k, 0) for k in VIE_DIMENSIONS))


def _grade_for(composite: float) -> str:
    if composite >= 90:
        return "A+"
    if composite >= 80:
        return "A"
    if composite >= 70:
        return "B"
    if composite >= 60:
        return "C"
    if composite >= 50:
        return "D"
    return "F"


def is_video_path(path) -> bool:
    if not path:
        return False
    return Path(path).suffix.lower() in _VIDEO_MIME_TYPES


def _skipped(reason: str) -> ReelQualityResult:
    return ReelQualityResult(
        scores={k: 0 for k in VIE_DIMENSIONS},
        composite=0.0, grade="—",
        explanations={k: "" for k in VIE_DIMENSIONS},
        is_skipped=True, skipped_reason=reason,
    )


def score_reel_quality(video_path,
                        ad_text: str = "",
                        *,
                        platform_label: str = "",
                        audience_hint: str = "",
                        objective: str = "",
                        context_block: str = "") -> ReelQualityResult:
    """Score a short video on the 8-axis VIE rubric.

    Optional kwargs let the caller inject platform + audience + objective
    so the critic is tuned, plus a ``context_block`` carrying 2026 trends
    / industry baseline / platform demographics built by the pipeline.
    """
    if os.environ.get("ADPROOF_REEL_QUALITY_ENABLED", "1").lower() in ("0", "false", "no"):
        return _skipped("Reel Quality is disabled via env flag.")
    if not is_video_path(video_path):
        return _skipped("Not a video upload — Reel Quality applies to video creatives only.")
    if not _get_key("GEMINI_API_KEY"):
        return _skipped("GEMINI_API_KEY not set — Reel Quality needs Gemini video vision.")

    p = Path(video_path)
    if not p.exists():
        return _skipped(f"Video not found at {p}.")
    size = p.stat().st_size
    if size > _MAX_VIDEO_BYTES:
        return _skipped(
            f"Video is {size / 1_048_576:.1f}MB — Reel Quality skips files "
            f"above {_MAX_VIDEO_BYTES // 1_048_576}MB (Gemini inline limit).")
    mime = _VIDEO_MIME_TYPES.get(p.suffix.lower(), "video/mp4")
    video_bytes = p.read_bytes()

    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        return _skipped("google-genai not installed.")

    client = genai.Client(api_key=_get_key("GEMINI_API_KEY"))
    user = _user_prompt(ad_text, platform_label, audience_hint,
                         objective, context_block)
    last_exc: Exception | None = None
    raw: dict = {}
    used_model = ""
    for model_id in GEMINI_VISION_CHAIN:
        if ("gemini-reel-quality", model_id) in _VISION_EXHAUSTED:
            continue
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=[
                    gtypes.Part.from_bytes(data=video_bytes, mime_type=mime),
                    user,
                ],
                config=gtypes.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    response_mime_type="application/json",
                    max_output_tokens=4096,
                ),
            )
        except Exception as exc:                              # noqa: BLE001
            last_exc = exc
            if _is_quota_error(exc):
                _VISION_EXHAUSTED.add(("gemini-reel-quality", model_id))
                _ph_quota("gemini-reel-quality", model_id, str(exc))
                continue
            return _skipped(f"Gemini call failed: {exc}")
        text = getattr(response, "text", None)
        if not text:
            last_exc = RuntimeError("Empty response.")
            continue
        try:
            raw = _extract_json(text)
            used_model = model_id
            _ph_ok("gemini-reel-quality", model_id)
            break
        except (ValueError, json.JSONDecodeError) as exc:
            last_exc = exc
            continue
    if not raw:
        return _skipped(f"Gemini reel-quality unavailable: {last_exc or 'all models exhausted'}.")

    # Normalise scores (clip to dimension max)
    scores_raw = raw.get("scores") or {}
    scores = {k: _clip_score(scores_raw.get(k), VIE_DIMENSION_MAX[k])
              for k in VIE_DIMENSIONS}
    explanations_raw = raw.get("explanations") or {}
    explanations = {k: str(explanations_raw.get(k, "")).strip()
                    for k in VIE_DIMENSIONS}

    # Hook alternatives — accept either list-of-dicts or list-of-strings
    hook_alts_raw = raw.get("hook_alternatives") or []
    hook_alts = []
    for ha in hook_alts_raw[:5]:
        if isinstance(ha, dict):
            h = str(ha.get("hook", "")).strip()
            r_ = str(ha.get("reason", "")).strip()
        else:
            h = str(ha).strip(); r_ = ""
        if h:
            hook_alts.append({"hook": h, "reason": r_})

    # Algorithm risk — clamp to expected vocabulary
    risk_raw = raw.get("algorithm_risk") or {}
    algorithm_risk = {}
    for k, v in risk_raw.items():
        lvl = str(v).strip().lower()
        if lvl in ("low", "medium", "high"):
            algorithm_risk[k] = lvl.capitalize()

    publish_verdict = str(raw.get("publish_verdict", "")).strip().upper()
    if publish_verdict not in ("YES", "NO"):
        publish_verdict = "NO" if _compute_composite(scores) < 55 else "YES"

    changes_raw = raw.get("publish_changes_required") or []
    changes = [str(c).strip() for c in changes_raw if str(c).strip()][:5]

    composite = _compute_composite(scores)
    return ReelQualityResult(
        scores=scores,
        composite=composite,
        grade=_grade_for(composite),
        explanations=explanations,
        biggest_strength=str(raw.get("biggest_strength", "")).strip(),
        biggest_weakness=str(raw.get("biggest_weakness", "")).strip(),
        drop_off_point=str(raw.get("drop_off_point", "")).strip(),
        hook_score=_clip_score(raw.get("hook_score"), 10),
        hook_alternatives=hook_alts,
        viral_pattern=str(raw.get("viral_pattern", "")).strip(),
        algorithm_risk=algorithm_risk,
        publish_verdict=publish_verdict,
        publish_changes_required=changes,
        provider="gemini",
        model=used_model,
        raw=raw,
    )
