"""Phase C: Gemini-powered script critic for talking-head video ads.

Runs ONLY when the vision pass tagged the creative as ``talking_head``.
One Gemini call that:
  1. Transcribes the spoken script from the audio.
  2. Critiques it as a paid-ad copywriter would, against the campaign
     objective (awareness / consideration / conversion).
  3. Offers a tightened rewrite optimised for the same objective.

Cost: one Gemini-video call per talking-head upload (~£0.002 for a
30s clip at 2.5 Flash rates), cached on the campaign row by the API
layer. Skipped silently for any other creative type.

Honest framing — must be enforced in the UI: this is a craft critique,
not a virality predictor and not a CTR forecast. Blotato's Viral AI
Coach was explicitly verified to NOT be in their API (see project
memory), so we built a comparable craft critique on the model we
already have. The result page labels it as such.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Reuse the prep + key + telemetry helpers from visual_analysis so the
# critic shares quota gating with the main vision pass.
try:
    from src.visual_analysis import (_VIDEO_MIME_TYPES, _MAX_VIDEO_BYTES,
                                     _VISION_EXHAUSTED, _get_key,
                                     _is_quota_error, _ph_ok, _ph_quota)
    from src.reel_quality import is_video_path
except ImportError:                                    # standalone
    from visual_analysis import (_VIDEO_MIME_TYPES, _MAX_VIDEO_BYTES,
                                 _VISION_EXHAUSTED, _get_key,
                                 _is_quota_error, _ph_ok, _ph_quota)
    from reel_quality import is_video_path

import sys
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import GEMINI_VISION_CHAIN  # noqa: E402

__all__ = [
    "ScriptCritique",
    "critique_talking_head",
]


@dataclass
class ScriptCritique:
    """Transcript + per-objective critique + a tightened rewrite."""
    transcript: str
    critique: list                       # bullet points (3-5 items)
    rewrite: str                          # the suggested replacement script
    rewrite_explanation: str              # 1-line summary of what changed
    objective: str = ""                   # awareness | consideration | conversion
    provider: str = "gemini"
    model: str = ""
    is_skipped: bool = False
    skipped_reason: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _skipped(reason: str) -> ScriptCritique:
    return ScriptCritique(
        transcript="", critique=[], rewrite="", rewrite_explanation="",
        is_skipped=True, skipped_reason=reason,
    )


_SYSTEM = (
    "You are a senior paid-ad copywriter who has shipped thousands of "
    "talking-head ads on Meta, TikTok and YouTube. You critique a script "
    "the way a head of performance would: brutally honest about hook, "
    "pacing, payoff, and whether the call-to-action actually converts. "
    "Output ONLY the requested JSON object."
)

_USER = (
    "Transcribe the SPOKEN SCRIPT from this talking-head video, then "
    "critique it for a PAID-AD use case targeting the '{objective}' "
    "objective. Finally, produce a tightened rewrite of the script "
    "optimised for the SAME objective.\n\n"
    "Objective-specific lens:\n"
    "- awareness: brand recall + memorable hook; do NOT push a CTA hard.\n"
    "- consideration: name the PAIN in the first 3 seconds; close on a "
    "soft 'learn more' CTA.\n"
    "- conversion: lead with the SOLUTION + a concrete proof point; "
    "close on a hard, specific CTA ('try free / book a demo / shop now').\n\n"
    "Return EXACTLY this JSON (no extra keys, no prose outside):\n"
    "{{\n"
    "  \"transcript\": \"<the spoken script as you hear it, verbatim>\",\n"
    "  \"critique\": [\n"
    "    \"<3-5 specific, actionable observations — cite words or moments>\"\n"
    "  ],\n"
    "  \"rewrite\": \"<the rewritten script, optimised for the {objective} "
    "objective. Same length or shorter than the original.>\",\n"
    "  \"rewrite_explanation\": \"<one short sentence explaining what "
    "moved + why>\"\n"
    "}}"
)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    if not text:
        raise ValueError("Empty response.")
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError(f"No JSON object found: {text[:200]}")
    return json.loads(m.group(0))


def critique_talking_head(video_path,
                           objective: str = "conversion") -> ScriptCritique:
    """Transcribe + critique + rewrite a talking-head ad script.

    Returns a ScriptCritique. When the creative isn't a video, Gemini
    isn't configured, the file is missing, or the env kill-switch is
    set, returns a skipped result so the caller can degrade gracefully.
    """
    if os.environ.get("ADPROOF_SCRIPT_CRITIC_ENABLED", "1").lower() in ("0", "false", "no"):
        return _skipped("Script Critic is disabled via env flag.")
    if not is_video_path(video_path):
        return _skipped("Script Critic only runs on video creatives.")
    if not _get_key("GEMINI_API_KEY"):
        return _skipped("GEMINI_API_KEY not set — Script Critic needs Gemini audio.")

    p = Path(video_path)
    if not p.exists():
        return _skipped(f"Video not found at {p}.")
    size = p.stat().st_size
    if size > _MAX_VIDEO_BYTES:
        return _skipped(
            f"Video is {size / 1_048_576:.1f}MB — Script Critic skips files "
            f"above {_MAX_VIDEO_BYTES // 1_048_576}MB (Gemini inline limit).")
    mime = _VIDEO_MIME_TYPES.get(p.suffix.lower(), "video/mp4")
    video_bytes = p.read_bytes()

    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        return _skipped("google-genai not installed.")

    client = genai.Client(api_key=_get_key("GEMINI_API_KEY"))
    obj = (objective or "conversion").lower()
    user_prompt = _USER.format(objective=obj)
    last_exc: Exception | None = None
    raw: dict = {}
    used_model = ""
    for model_id in GEMINI_VISION_CHAIN:
        if ("gemini-script-critic", model_id) in _VISION_EXHAUSTED:
            continue
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=[
                    gtypes.Part.from_bytes(data=video_bytes, mime_type=mime),
                    user_prompt,
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
                _VISION_EXHAUSTED.add(("gemini-script-critic", model_id))
                _ph_quota("gemini-script-critic", model_id, str(exc))
                continue
            return _skipped(f"Gemini call failed: {exc}")
        text = getattr(response, "text", None)
        if not text:
            last_exc = RuntimeError("Empty response.")
            continue
        try:
            raw = _extract_json(text)
            used_model = model_id
            _ph_ok("gemini-script-critic", model_id)
            break
        except (ValueError, json.JSONDecodeError) as exc:
            last_exc = exc
            continue
    if not raw:
        return _skipped(f"Gemini script critic unavailable: {last_exc or 'all models exhausted'}.")

    transcript = str(raw.get("transcript", "")).strip()
    critique = [str(c).strip() for c in (raw.get("critique") or [])
                if str(c).strip()][:5]
    rewrite = str(raw.get("rewrite", "")).strip()
    rewrite_explanation = str(raw.get("rewrite_explanation", "")).strip()
    return ScriptCritique(
        transcript=transcript,
        critique=critique,
        rewrite=rewrite,
        rewrite_explanation=rewrite_explanation,
        objective=obj,
        provider="gemini",
        model=used_model,
        raw=raw,
    )
