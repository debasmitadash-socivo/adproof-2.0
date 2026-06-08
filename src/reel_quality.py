"""Reel Quality Rubric — short-video creative craft scoring (video-only).

Independent of the main vision pass: scores a video on five paid-ad-relevant
craft dimensions and emits 2-3 actionable suggestions. NOT a virality score:
this rates the creative under paid-ad constraints (muted feeds, 3-second
attention budgets, intent-driven feeds), separate from organic-feed dynamics.

Dimensions, each 0-10:
  hook_strength            -- first 3s: pattern interrupt / curiosity gap?
  sound_off_comprehension  -- is the message intelligible muted?
  pain_benefit_clarity     -- is the problem / value visible by mid-clip?
  pacing_retention         -- does each beat earn the next? dead air?
  emotional_resonance      -- does it provoke a felt reaction?

Composite: weighted (Hook 30%, Sound-off 20%, Clarity 20%, Pacing 15%,
Emotion 15%) on a 0-100 scale. Weights chosen because hook + soundless are
the highest-leverage failure modes for paid placement.

Cost-conscious by design:
- Only runs on video uploads (no image waste).
- One Gemini call per video. ~£0.002 for a 30s reel at 2.5 Flash rates.
- Caller is expected to cache the result on the campaign row.
- Skipped silently when no Gemini key is set.

This is NOT a virality predictor and NOT a paid-CTR predictor. It is a
craft-quality input — high score does not guarantee high CTR, and a strong
offer can still win with a lower score. The result page must surface that
caveat in the UI.
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
    # Reuse the video prep + key loader + telemetry from visual_analysis so the
    # Reel Quality pass shares quota gating with the main vision pass.
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
    "REEL_QUALITY_DIMENSIONS",
    "is_video_path",
]


# Public so the API/UI layers can introspect the rubric for tooltips, etc.
REEL_QUALITY_DIMENSIONS = (
    "hook_strength",
    "sound_off_comprehension",
    "pain_benefit_clarity",
    "pacing_retention",
    "emotional_resonance",
)

# Composite weights chosen because hook + sound-off are the top two failure
# modes in paid muted-feed placement (Meta / TikTok / Reels).
_COMPOSITE_WEIGHTS = {
    "hook_strength": 0.30,
    "sound_off_comprehension": 0.20,
    "pain_benefit_clarity": 0.20,
    "pacing_retention": 0.15,
    "emotional_resonance": 0.15,
}


@dataclass
class ReelQualityResult:
    """Five 0-10 sub-scores + a 0-100 composite + actionable suggestions."""
    scores: dict                       # five keys from REEL_QUALITY_DIMENSIONS
    composite: float                   # 0-100, weighted (see _COMPOSITE_WEIGHTS)
    grade: str                         # A/B/C/D for the composite
    explanations: dict                 # one-line "why this score" per dimension
    suggestions: list                  # 2-3 specific, ad-relevant edit notes
    provider: str = "gemini"
    model: str = ""
    is_skipped: bool = False           # True if we didn't actually score
    skipped_reason: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Gemini prompts
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a senior paid-ad creative director scoring short videos "
    "(Reels / TikToks / Shorts) for use as PAID ADS — not organic viral "
    "content. Be strict and concrete; never inflate scores. Respond ONLY "
    "with the requested JSON, no commentary."
)


def _user_prompt(ad_text: str) -> str:
    return (
        "Score the attached short video on the FIVE dimensions below, each "
        "0-10 integer (10 = excellent), plus a one-line explanation per "
        "dimension and 2-3 SPECIFIC, ACTIONABLE edit suggestions. Score for "
        "PAID-AD use (muted feeds, 3-second attention budgets, intent-driven "
        "auctions), not organic virality.\n\n"
        f"Ad copy: \"{ad_text.strip()}\"\n\n"
        "Dimensions:\n"
        "1. hook_strength — first 3 seconds: pattern interrupt / curiosity "
        "gap / bold claim that stops the scroll?\n"
        "2. sound_off_comprehension — with audio MUTED, is the message clear "
        "from visuals + captions? (most paid impressions play silent)\n"
        "3. pain_benefit_clarity — is the problem (or benefit) visible by "
        "mid-clip? Vague concept videos score low here.\n"
        "4. pacing_retention — does each beat earn the next? Any dead air, "
        "padding, or sections likely to lose viewers?\n"
        "5. emotional_resonance — does it provoke a felt reaction worth "
        "sharing? (laughter, surprise, recognition, relief — not just "
        "'pretty'.)\n\n"
        "Return EXACTLY this JSON schema (no extra keys, no prose outside):\n"
        "{\n"
        "  \"hook_strength\": int 0-10,\n"
        "  \"sound_off_comprehension\": int 0-10,\n"
        "  \"pain_benefit_clarity\": int 0-10,\n"
        "  \"pacing_retention\": int 0-10,\n"
        "  \"emotional_resonance\": int 0-10,\n"
        "  \"explanations\": {\n"
        "    \"hook_strength\": \"one short sentence why\",\n"
        "    \"sound_off_comprehension\": \"…\",\n"
        "    \"pain_benefit_clarity\": \"…\",\n"
        "    \"pacing_retention\": \"…\",\n"
        "    \"emotional_resonance\": \"…\"\n"
        "  },\n"
        "  \"suggestions\": [\n"
        "    \"specific edit, e.g. 'Lead with the muted-text claim — your "
        "hook currently relies on voiceover.'\",\n"
        "    \"…\"\n"
        "  ]\n"
        "}"
    )


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    """Permissive JSON extract — Gemini occasionally wraps in markdown fences."""
    if not text:
        raise ValueError("Empty response from Gemini.")
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError(f"No JSON object found in response: {text[:200]}")
    return json.loads(m.group(0))


def _clip_score(v) -> int:
    try:
        return max(0, min(10, int(round(float(v)))))
    except (TypeError, ValueError):
        return 5


def _compute_composite(scores: dict) -> float:
    total = sum(scores[k] * _COMPOSITE_WEIGHTS[k]
                for k in REEL_QUALITY_DIMENSIONS) * 10        # 0-10 -> 0-100
    return round(total, 1)


def _grade_for(composite: float) -> str:
    if composite >= 80:
        return "A"
    if composite >= 65:
        return "B"
    if composite >= 50:
        return "C"
    return "D"


def is_video_path(path) -> bool:
    """True if the path's extension is one we know how to score."""
    if not path:
        return False
    return Path(path).suffix.lower() in _VIDEO_MIME_TYPES


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _skipped(reason: str) -> ReelQualityResult:
    return ReelQualityResult(
        scores={k: 0 for k in REEL_QUALITY_DIMENSIONS},
        composite=0.0,
        grade="—",
        explanations={k: "" for k in REEL_QUALITY_DIMENSIONS},
        suggestions=[],
        is_skipped=True,
        skipped_reason=reason,
    )


def score_reel_quality(video_path,
                        ad_text: str = "") -> ReelQualityResult:
    """Score a short video on the 5-axis Reel Quality rubric.

    Returns a ReelQualityResult; if scoring isn't possible (no Gemini key,
    quota exhausted, non-video) the result has ``is_skipped=True`` and
    ``skipped_reason`` populated so the caller can degrade gracefully.

    The function never raises for user-facing errors — vision unavailability
    is normal-path here, not a fatal. The main viability gate (see
    strict-vision-safety) still blocks the campaign if the main vision pass
    can't run; this rubric is an additive signal that simply omits itself
    when the provider is down.
    """
    # Env kill-switch lets the owner disable the whole feature globally if
    # Gemini bills surprise us.
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
    last_exc: Exception | None = None
    raw: dict = {}
    used_model = ""
    # Reuse the same chain as the main vision pass so the rotation/quota
    # bookkeeping is unified. A separate (provider, model) tag isolates
    # quota state so reel-quality exhaustion doesn't poison the main path.
    for model_id in GEMINI_VISION_CHAIN:
        if ("gemini-reel-quality", model_id) in _VISION_EXHAUSTED:
            continue
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=[
                    gtypes.Part.from_bytes(data=video_bytes, mime_type=mime),
                    _user_prompt(ad_text),
                ],
                config=gtypes.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    response_mime_type="application/json",
                    max_output_tokens=2048,
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
            last_exc = RuntimeError("Gemini reel-quality response had no text.")
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

    # Normalise the response. Scores defensively clipped to 0-10 ints; missing
    # explanations / suggestions fall back to empty strings / empty list.
    scores = {k: _clip_score(raw.get(k)) for k in REEL_QUALITY_DIMENSIONS}
    explanations_raw = raw.get("explanations") or {}
    explanations = {k: str(explanations_raw.get(k, "")).strip()
                    for k in REEL_QUALITY_DIMENSIONS}
    suggestions_raw = raw.get("suggestions") or []
    suggestions = [str(s).strip() for s in suggestions_raw if str(s).strip()][:3]

    composite = _compute_composite(scores)
    return ReelQualityResult(
        scores=scores,
        composite=composite,
        grade=_grade_for(composite),
        explanations=explanations,
        suggestions=suggestions,
        provider="gemini",
        model=used_model,
        raw=raw,
    )
