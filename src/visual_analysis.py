"""Multimodal LLM analysis of ad creatives.

Scores an uploaded ad image + copy on four dimensions, each in [0, 1]:

  emotional_arousal    -- emotional activation the creative triggers
  visual_clarity       -- how easily the message + focal point are grasped
  attention_capture    -- stopping power in a crowded feed
  relevance_potential  -- how clearly a specific, relevant value prop lands

Providers
---------
Claude (Anthropic) or GPT-4o (OpenAI), selected automatically from whichever
API key is present in the environment / .env. If neither key is available a
transparent heuristic fallback runs from image statistics + copy keywords, so
the pipeline still works end-to-end (clearly flagged ``is_heuristic=True``).

The ``anthropic`` / ``openai`` / ``python-dotenv`` packages are imported lazily
-- the heuristic path needs only Pillow + numpy.

Limitations
-----------
These scores are an LLM's structured judgement against general advertising
principles. They are NOT measured attention or eye-tracking data -- treat them
as directional creative diagnostics, not guarantees. The heuristic fallback is
cruder still (image colour/contrast statistics + copy keywords) and is meant
for plumbing and demos, not for client-facing numbers.

Run directly for a heuristic demo on a generated test image:
    python src/visual_analysis.py
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# Allow `python src/visual_analysis.py` to find config.py in the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import (  # noqa: E402
    CLAUDE_MODEL,
    GEMINI_VISION_CHAIN,
    GEMINI_VISION_MODEL,
    GROQ_VISION_MODEL,
    MISTRAL_BASE_URL,
    MISTRAL_VISION_MODEL,
    OPENAI_MODEL,
    OPENROUTER_BASE_URL,
    OPENROUTER_VISION_MODEL,
    PROJECT_ROOT,
    TOGETHER_BASE_URL,
    TOGETHER_VISION_MODEL,
    VISUAL_SCORE_KEYS,
    XAI_BASE_URL,
    XAI_VISION_MODEL,
)

# Reuse the copy-keyword tagger from the data layer for the heuristic path.
try:
    from src.data_loader import tag_creative_features
except ImportError:  # when run as `python src/visual_analysis.py`
    from data_loader import tag_creative_features

# Provider-health telemetry — records quota/ok events so the diagnostics page
# can show the moment the vision provider runs out. Defensive: a telemetry
# import failure must never break the vision path.
try:
    try:
        from src.provider_health import (
            record_ok as _ph_ok, record_quota as _ph_quota)
    except ImportError:
        from provider_health import (
            record_ok as _ph_ok, record_quota as _ph_quota)
except Exception:  # pragma: no cover
    def _ph_ok(*a, **k): pass
    def _ph_quota(*a, **k): pass

__all__ = [
    "VisualAnalysisResult",
    "analyze_ad",
    "available_providers",
]

# Anthropic recommends a max image edge of ~1568px; larger images are
# downscaled before encoding to keep the request payload small.
MAX_IMAGE_DIM = 1568
HEURISTIC_VERSION = "heuristic-v1"


# ===========================================================================
# Scoring rubric -- the "advertising benchmark" grounding for the LLM
# ===========================================================================

_RUBRIC = """\
emotional_arousal -- How strongly the creative triggers an emotional response.
  0.0-0.2  flat, purely informational, no emotional cue
  0.3-0.5  mild emotional tone
  0.6-0.8  clear emotional appeal (expressive faces, evocative imagery/copy)
  0.9-1.0  strong, visceral emotional impact
  Grounding: emotional response is one of the strongest drivers of ad
  memorability and long-term engagement.

visual_clarity -- How easily a viewer grasps the message and focal point.
  low   cluttered, competing elements, no focal point, hard-to-read text
  high  single clear focal point, legible hierarchy, uncluttered layout
  Grounding: comprehension and a single dominant focal point correlate with
  effectiveness; visual clutter slows processing.

attention_capture -- Stopping power in a fast-scrolling feed.
  low   blends in, low contrast, generic composition
  high  strong contrast, bold focal point, distinctive colour, pattern break
  Grounding: visual saliency (contrast, colour, faces) drives initial
  attention before any copy is read.

relevance_potential -- How clearly the creative signals a specific, relevant
  value proposition and target audience.
  low   vague, no clear benefit, unclear who it is for
  high  explicit, specific benefit; obvious target and value proposition
  Grounding: message relevance and a clear value proposition are core
  conversion drivers."""

_RESPONSE_SHAPE = """\
{
  "image_description": "<MANDATORY: describe in 1-2 sentences exactly what you see in the image -- objects, people, setting, text overlay, mood. This proves you actually examined the image.>",
  "image_copy_coherence": <float 0-1>,
  "image_copy_coherence_explanation": "<2-3 sentences answering: does what is IN the image visually depict / support / contradict what the COPY says? A picture of a sunset for a SaaS ad copy = low. A picture of running shoes for 'Hit your first 10K' = high. Be strict.>",
  "scores": {
    "emotional_arousal": <float 0-1>,
    "visual_clarity": <float 0-1>,
    "attention_capture": <float 0-1>,
    "relevance_potential": <float 0-1>
  },
  "explanations": {
    "emotional_arousal": "<1-2 sentence rationale citing what is in the ad>",
    "visual_clarity": "<1-2 sentences>",
    "attention_capture": "<1-2 sentences>",
    "relevance_potential": "<1-2 sentences>"
  },
  "brand_relevance": <float 0-1>,
  "brand_relevance_explanation": "<2-3 sentences answering: does the image actually fit the brand category, product, and the ad copy? Be strict -- a generic stock photo for a niche product should score under 0.4.>",
  "ban_risk": {
    "level": "<none | low | medium | high>",
    "flags": ["<specific things in the IMAGE that could get an ad account suspended or rejected: nudity / sexual content, shocking or violent imagery, alcohol/drugs/weapons, before-after body imagery, hateful symbols, deceptive/clickbait visuals, prohibited-category products, visible personal data. Empty array if clean.>"],
    "explanation": "<1-2 sentences. If level is none, say the imagery looks policy-safe.>"
  },
  "creative_type": "<one of: product_shot | lifestyle | text_heavy | ugc | illustration | screenshot | meme | talking_head | broll | motion_graphic | product_demo | before_after | animated. Choose the SINGLE best fit. For images you'll typically pick one of the first 7; for videos, the last 6. talking_head = a person speaking to camera as the primary focus (lip sync visible); broll = footage cut to music or voiceover with no speaker on camera; motion_graphic = animated text/shapes, no live footage; product_demo = the product in use; before_after = transformation reveal.>",
  "creative_type_explanation": "<one short sentence — what concretely tells you it's this type. Cite an observable feature.>",
  "strengths": ["<short phrase>", "..."],
  "weaknesses": ["<short phrase>", "..."],
  "overall": "<2-3 sentence summary of how this creative is likely to perform>"
}"""

_SYSTEM_PROMPT = f"""\
You are a senior advertising creative strategist and media-effectiveness
analyst. You evaluate ad creatives (image + copy) against established
advertising-effectiveness principles and return a disciplined, calibrated
score on four dimensions, each from 0.0 to 1.0.

RUBRIC
{_RUBRIC}

CALIBRATION GUIDANCE
- Use the full range. Most real ads cluster between 0.3 and 0.7; reserve
  0.8+ for genuinely exceptional execution and below 0.2 for clear failures.
- Score what is actually present in the creative, not what the brand might
  intend. Be specific and critical; do not default to generous middles.
- Base every score on concrete, observable features of the image and copy.

OUTPUT
Return ONLY a single JSON object, no prose before or after, matching exactly
this shape:
{_RESPONSE_SHAPE}"""


def _build_user_prompt(ad_text: str, audience_hint: str | None,
                       brand_hint: str | None = None) -> str:
    """Compose the user-turn text accompanying the ad image."""
    parts = ["Analyse the attached ad image together with its copy."]
    parts.append(f'Ad copy: "{ad_text.strip()}"' if ad_text.strip()
                 else "Ad copy: (none provided -- judge the image alone)")
    if brand_hint:
        parts.append(f"Brand context: {brand_hint.strip()}")
    if audience_hint:
        parts.append(f"Intended audience: {audience_hint.strip()}")
    parts.append("Pay particular attention to brand_relevance -- does the "
                  "image semantically fit the brand and copy, or is it a "
                  "generic stock-photo mismatch? Be strict.")
    parts.append("Return the JSON object now.")
    return "\n".join(parts)


# Light category-keyword map for the heuristic brand-relevance check.
# These are intentionally short lists -- the heuristic CAN'T see the image,
# so it falls back to copy-vs-category keyword overlap and is upfront about
# that limitation in the explanation.
_CATEGORY_HINTS = {
    "beauty": ["skin", "beauty", "glow", "serum", "cosmetic", "makeup",
                "fragrance", "skincare", "self-care"],
    "fitness": ["fit", "run", "running", "workout", "training", "gym",
                 "pace", "yoga", "cycle", "marathon", "club", "sport",
                 "athletic"],
    "apparel": ["fashion", "style", "wear", "outfit", "dress", "shirt",
                 "shoe", "drop"],
    "food_bev": ["food", "drink", "coffee", "tea", "taste", "flavor",
                  "meal", "recipe"],
    "finance": ["save", "invest", "money", "bank", "credit", "loan",
                 "wealth", "rate", "return"],
    "electronics": ["tech", "device", "phone", "laptop", "gadget"],
    "home": ["home", "decor", "furniture", "kitchen"],
    "travel": ["travel", "trip", "hotel", "flight", "destination"],
    "auto": ["car", "drive", "ride", "electric"],
    "entertainment": ["music", "movie", "show", "game", "stream"],
    "saas": ["software", "app", "platform", "workflow", "team", "cloud",
              "api", "build", "ship"],
    "marketing_agency": ["marketing", "growth", "campaign", "creative",
                          "brand", "agency", "scale"],
    "professional_services": ["advice", "consult", "strategy", "expert"],
    "general": [],
}


def _heuristic_brand_relevance(ad_text: str,
                                category: str | None,
                                industry: str | None) -> tuple[float, str]:
    """Honest heuristic relevance check: can ONLY look at copy + category.

    The heuristic cannot inspect image content -- a photo of a cat for a SaaS
    ad will not be caught here. We score the copy-vs-category overlap as a
    weak proxy and tell the user exactly what we *can't* check.
    """
    text = (ad_text or "").lower()
    cat = (category or "general").lower()
    hints = _CATEGORY_HINTS.get(cat, [])

    if not text:
        return 0.45, (
            "No copy to compare. Heuristic relevance check can't inspect "
            "image content -- connect a multimodal LLM (Claude / GPT-4o) "
            "to actually score whether the image fits the brand."
        )
    if not hints:
        return 0.50, (
            f"Category '{cat}' has no keyword hints to match against. "
            "Heuristic relevance check can't inspect image content -- "
            "connect a multimodal LLM for a real semantic check."
        )

    matches = [h for h in hints if h in text]
    industry_lower = (industry or "").lower()

    if matches:
        # Copy mentions category keywords -- modest positive signal, with
        # caveat the IMAGE isn't being checked.
        score = min(0.45 + 0.08 * len(matches), 0.70)
        explanation = (
            f"Copy mentions {len(matches)} category-relevant term"
            f"{'' if len(matches) == 1 else 's'} "
            f"({', '.join(matches[:3])}). "
            "⚠ Heuristic doesn't inspect the image itself -- if you uploaded "
            "a generic stock photo it would still score the same. Connect a "
            "multimodal LLM key for a real image-vs-brand check."
        )
        return score, explanation

    if industry_lower and any(w in text for w in industry_lower.split() if len(w) > 3):
        return 0.45, (
            f"Copy aligns with your industry ('{industry}') but not your "
            f"product category ('{cat}'). Heuristic can't check the image."
        )

    return 0.30, (
        f"Copy doesn't reference your category ('{cat}') or industry. "
        "This is a weak signal that copy and brand may be mismatched -- "
        "but the bigger gap (image not being checked) requires an LLM."
    )


# ===========================================================================
# Result container
# ===========================================================================

@dataclass
class VisualAnalysisResult:
    """Structured output of a creative analysis."""
    scores: dict                       # 4 dimensions, each 0-1
    explanations: dict                 # 4 dimensions -> rationale
    strengths: list = field(default_factory=list)
    weaknesses: list = field(default_factory=list)
    overall: str = ""
    provider: str = "heuristic"        # 'claude' | 'openai' | 'heuristic'
    model: str = HEURISTIC_VERSION
    is_heuristic: bool = True
    image_meta: dict = field(default_factory=dict)
    ad_text: str = ""
    created_at: str = ""
    # Relevance check — does the image match the brand + copy?
    # Separate from the 4 visual scores because it's about semantic fit,
    # not aesthetic quality.
    brand_relevance: float = 0.5
    brand_relevance_explanation: str = ""
    brand_relevance_source: str = "heuristic"  # 'llm' | 'heuristic'
    # New: an explicit "what the model sees in the image" so the user can
    # verify the LLM actually looked at the file, AND an image-↔-copy
    # coherence score (does the picture even depict what the headline says?).
    image_description: str = ""
    image_copy_coherence: float = 0.5
    image_copy_coherence_explanation: str = ""
    # Account-ban / appropriateness risk from the IMAGE (LLM only). Heuristic
    # mode can't see the picture so it returns level "unknown".
    ban_risk: dict = field(default_factory=lambda: {
        "level": "unknown", "flags": [],
        "explanation": "Image not inspected (heuristic mode).",
    })
    # Pillar B: creative type detection (image: product_shot, lifestyle,
    # text_heavy, ugc, illustration, screenshot, meme; video: talking_head,
    # broll, motion_graphic, product_demo, before_after, animated). Lets the
    # report give type-specific advice and gates the talking-head script
    # critic (Phase C).
    creative_type: str = ""
    creative_type_explanation: str = ""
    # When the chosen LLM failed and we fell back to the heuristic, this
    # carries the underlying error message so the UI can show "Gemini failed:
    # quota exhausted" instead of leaving the user guessing.
    provider_error: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat(
                timespec="seconds")

    @property
    def composite_score(self) -> float:
        """Unweighted mean of the four dimensions -- a rough overall index."""
        return round(float(np.mean(list(self.scores.values()))), 3)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["composite_score"] = self.composite_score
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def summary(self) -> str:
        lines = [f"Visual analysis ({self.provider} / {self.model})",
                 "-" * 48]
        for k in VISUAL_SCORE_KEYS:
            lines.append(f"  {k:<20s} {self.scores[k]:.2f}")
        lines.append(f"  {'COMPOSITE':<20s} {self.composite_score:.2f}")
        lines.append("-" * 48)
        lines.append(f"  {self.overall}")
        if self.is_heuristic:
            lines.append("  NOTE: heuristic fallback -- no vision model used; "
                         "directional only.")
        return "\n".join(lines)


# ===========================================================================
# Image preparation
# ===========================================================================

def _prepare_image(image_path: str | Path):
    """Load, downscale, and base64-encode an image for a vision API.

    Returns ``(b64, media_type, rgb_image, meta)`` where ``rgb_image`` is the
    (possibly downscaled) PIL image used by the heuristic path.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Ad image not found: {path}")

    img = Image.open(path)
    img.load()
    original_size = img.size

    if max(img.size) > MAX_IMAGE_DIM:
        scale = MAX_IMAGE_DIM / max(img.size)
        new_size = (max(1, int(img.size[0] * scale)),
                    max(1, int(img.size[1] * scale)))
        img = img.resize(new_size, Image.LANCZOS)

    has_alpha = img.mode in ("RGBA", "LA", "P")
    buf = BytesIO()
    if has_alpha:
        img.convert("RGBA").save(buf, "PNG")
        media_type = "image/png"
    else:
        img.convert("RGB").save(buf, "JPEG", quality=90)
        media_type = "image/jpeg"
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    meta = {
        "original_size": list(original_size),
        "encoded_size": list(img.size),
        "media_type": media_type,
        "payload_kb": round(len(b64) * 3 / 4 / 1024, 1),
    }
    return b64, media_type, img.convert("RGB"), meta


# ===========================================================================
# Provider selection + API keys
# ===========================================================================

def _load_env() -> None:
    """Load .env into the environment if python-dotenv is installed."""
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass


def _get_key(name: str) -> str | None:
    _load_env()
    key = os.environ.get(name)
    return key or None


_VISION_PROVIDERS = (
    "claude", "openai", "gemini", "groq",
    "mistral", "openrouter", "xai", "together",
)

# Score-consistency switch. Different providers rate the same image on
# different scales, so a "0.8" from Gemini isn't a "0.8" from Groq. When True
# (default), an 'auto' run pins scoring to ONE provider (keeping that
# provider's own same-prompt model rotation) and degrades to heuristic — i.e.
# an honest "couldn't analyse" block — rather than scoring on a different
# scale. Set False to restore full cross-provider fallback (max availability,
# less comparable scores). An explicit provider choice is always honoured.
PIN_VISION_PROVIDER = True
_VISION_KEY_ENV = {
    "claude":     "ANTHROPIC_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "gemini":     "GEMINI_API_KEY",
    "groq":       "GROQ_API_KEY",
    "mistral":    "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "xai":        "XAI_API_KEY",
    "together":   "TOGETHER_API_KEY",
}


def available_providers() -> dict:
    """Report which analysis providers are usable right now."""
    out = {p: _get_key(env) is not None
           for p, env in _VISION_KEY_ENV.items()}
    out["heuristic"] = True
    return out


def _select_provider(provider: str) -> str:
    """Resolve 'auto' to a concrete provider based on available API keys.

    Order: paid quality (Claude > OpenAI) → free vision-capable
    (Gemini > Groq > Mistral > OpenRouter > xAI > Together) → heuristic.
    """
    if provider != "auto":
        return provider
    for p in _VISION_PROVIDERS:
        if _get_key(_VISION_KEY_ENV[p]):
            return p
    return "heuristic"


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in (
        "429", "resource_exhausted", "quota", "rate limit", "rate_limit",
        "503", "unavailable", "overloaded",
        # Retired/unknown model ids (Google 404s models per-account as it
        # deprecates them) — skip to the next model in the chain rather
        # than failing the whole request on one dead id.
        "404", "not_found", "not found", "no longer available",
    ))


# Session-level memory of (provider, model) combos that hit quota, so
# subsequent calls in the same uvicorn process skip them.
_VISION_EXHAUSTED: set = set()


# ===========================================================================
# Response parsing
# ===========================================================================

def _extract_json(text: str) -> dict:
    """Extract the first balanced JSON object from an LLM response.

    Real LLM responses often violate strict JSON: trailing commas before
    ``}`` / ``]``, single-quoted keys ('foo': 1), comments, smart quotes.
    Gemini in particular sometimes drops trailing commas after the last
    field of a long object (the 'Expecting property name' error). We try
    strict ``json.loads`` first (fast path); if it fails, we apply a small
    set of cleanups (NOT a full JSON5 parser — just the common LLM slips)
    and retry. Helpers raise the ORIGINAL parse error on final failure so
    the caller can decide whether to rotate models.
    """
    text = text.strip()
    if text.startswith("```"):                       # strip markdown fences
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model response.")
    depth = 0
    end = -1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise ValueError("Unbalanced JSON in model response.")
    candidate = text[start:end]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as primary:
        # Cleanup pass — the failures we actually see from Gemini in prod:
        #   1. trailing comma before } or ]   {"a": 1,}
        #   2. single-quoted property names    {'a': 1}
        #   3. smart double quotes              {“a”: 1}
        # Whitespace-only normalisation; never alters string contents.
        cleaned = re.sub(r",(\s*[}\]])", r"\1", candidate)
        cleaned = cleaned.replace("“", '"').replace("”", '"')
        cleaned = re.sub(r"(?<=[{,]\s)\'([A-Za-z_][\w\-]*)\'(?=\s*:)",
                          r'"\1"', cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Re-raise the ORIGINAL error so the caller's "is this a quota
            # vs a parse failure?" check works against the unmodified text.
            raise primary


def _normalise_raw(parsed: dict) -> dict:
    """Coerce a parsed LLM dict into the internal normalised shape."""
    try:
        br = float(parsed.get("brand_relevance", 0.5))
    except (TypeError, ValueError):
        br = 0.5
    try:
        coh = float(parsed.get("image_copy_coherence", 0.5))
    except (TypeError, ValueError):
        coh = 0.5
    # Account-ban / appropriateness risk (multimodal models only).
    br_raw = parsed.get("ban_risk") or {}
    if not isinstance(br_raw, dict):
        br_raw = {}
    ban_level = str(br_raw.get("level", "none")).strip().lower()
    if ban_level not in ("none", "low", "medium", "high"):
        ban_level = "none"
    ban_risk = {
        "level": ban_level,
        "flags": [str(f).strip() for f in (br_raw.get("flags") or [])][:8],
        "explanation": str(br_raw.get("explanation", "")).strip(),
    }
    # Pillar B: creative type — accept whichever slug the model returned,
    # validate against the known taxonomy, fall back to empty (UI hides
    # the card) if the model picked an unknown label.
    _ct = str(parsed.get("creative_type", "")).strip().lower()
    if _ct not in {"product_shot", "lifestyle", "text_heavy", "ugc",
                   "illustration", "screenshot", "meme", "talking_head",
                   "broll", "motion_graphic", "product_demo",
                   "before_after", "animated"}:
        _ct = ""
    return {
        "scores": parsed.get("scores", {}),
        "explanations": parsed.get("explanations", {}),
        "brand_relevance": max(0.0, min(1.0, br)),
        "brand_relevance_explanation": str(
            parsed.get("brand_relevance_explanation", "")).strip(),
        "image_description": str(parsed.get("image_description", "")).strip(),
        "image_copy_coherence": max(0.0, min(1.0, coh)),
        "image_copy_coherence_explanation": str(
            parsed.get("image_copy_coherence_explanation", "")).strip(),
        "ban_risk": ban_risk,
        "strengths": list(parsed.get("strengths", []))[:6],
        "weaknesses": list(parsed.get("weaknesses", []))[:6],
        "overall": str(parsed.get("overall", "")).strip(),
        "creative_type": _ct,
        "creative_type_explanation": str(
            parsed.get("creative_type_explanation", "")).strip(),
    }


def _validate_scores(scores: dict) -> dict:
    """Ensure all four scores are present and clamped to [0, 1]."""
    clean = {}
    for key in VISUAL_SCORE_KEYS:
        try:
            clean[key] = float(np.clip(float(scores.get(key, 0.5)), 0.0, 1.0))
        except (TypeError, ValueError):
            clean[key] = 0.5  # unpar, neutral default if the model misbehaves
    return clean


# ===========================================================================
# Provider: Claude (Anthropic)
# ===========================================================================

def _analyze_claude(b64: str, media_type: str, ad_text: str,
                    audience_hint: str | None) -> dict:
    """Call the Claude multimodal API and return the normalised raw dict."""
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "anthropic package not installed -- run `pip install anthropic`."
        ) from exc

    key = _get_key("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set (see .env.example).")

    client = anthropic.Anthropic(api_key=key)
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text",
                 "text": _build_user_prompt(ad_text, audience_hint)},
            ]},
            # Prefill an opening brace so the reply is forced to be pure JSON.
            {"role": "assistant", "content": "{"},
        ],
    )
    text = "{" + "".join(
        block.text for block in message.content
        if getattr(block, "type", None) == "text")
    return _normalise_raw(_extract_json(text))


# ===========================================================================
# Provider: GPT-4o (OpenAI)
# ===========================================================================

def _analyze_openai(b64: str, media_type: str, ad_text: str,
                    audience_hint: str | None) -> dict:
    """Call the GPT-4o multimodal API and return the normalised raw dict."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "openai package not installed -- run `pip install openai`."
        ) from exc

    key = _get_key("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set (see .env.example).")

    client = OpenAI(api_key=key)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        max_tokens=1024,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text",
                 "text": _build_user_prompt(ad_text, audience_hint)},
                {"type": "image_url", "image_url": {
                    "url": f"data:{media_type};base64,{b64}"}},
            ]},
        ],
    )
    return _normalise_raw(_extract_json(response.choices[0].message.content))


# ===========================================================================
# Provider: heuristic fallback (no API)
# ===========================================================================

def _image_stats(rgb_image: Image.Image) -> dict:
    """Cheap colour/contrast statistics used by the heuristic scorer."""
    arr = np.asarray(rgb_image, dtype=float)            # H x W x 3, 0-255
    # Perceptual luminance via an element-wise weighted sum (avoids matmul).
    lum = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1]
           + 0.114 * arr[:, :, 2])

    brightness = float(lum.mean() / 255.0)
    contrast = float(np.clip(lum.std() / 80.0, 0.0, 1.0))

    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    saturation = float(np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0).mean())

    # Mean absolute luminance gradient -- a crude "busyness" proxy.
    grad = (np.abs(np.diff(lum, axis=0)).mean()
            + np.abs(np.diff(lum, axis=1)).mean()) / 2.0
    edge_density = float(np.clip(grad / 40.0, 0.0, 1.0))

    warmth = float(np.clip(
        ((arr[:, :, 0] - arr[:, :, 2]).mean() / 255.0 + 1.0) / 2.0, 0.0, 1.0))
    return {
        "brightness": brightness, "contrast": contrast,
        "saturation": saturation, "edge_density": edge_density,
        "warmth": warmth,
    }


def _analyze_heuristic(rgb_image: Image.Image, ad_text: str,
                       brand_category: str | None = None,
                       brand_industry: str | None = None) -> dict:
    """Score the creative without an LLM, from image statistics + copy cues.

    Deliberately simple and transparent -- a fallback so the pipeline runs
    without API keys. NOT a substitute for the multimodal model.
    """
    s = _image_stats(rgb_image)
    copy = tag_creative_features(ad_text)              # emotional/scarcity/...

    scores = {
        # Emotion: copy emotional language + colour saturation/warmth.
        "emotional_arousal": np.clip(
            0.50 * copy["emotional_appeal"] + 0.30 * s["saturation"]
            + 0.20 * s["warmth"], 0, 1),
        # Clarity: fewer edges (less clutter) reads as clearer.
        "visual_clarity": np.clip(
            0.70 * (1.0 - s["edge_density"]) + 0.30 * s["contrast"], 0, 1),
        # Attention: contrast + saturation are the main saliency cues.
        "attention_capture": np.clip(
            0.45 * s["contrast"] + 0.35 * s["saturation"]
            + 0.20 * max(copy["scarcity"], copy["emotional_appeal"]), 0, 1),
        # Relevance: driven mostly by copy clarity (image gives little signal).
        "relevance_potential": np.clip(
            0.70 * copy["relevance"] + 0.30 * 0.5, 0, 1),
    }
    scores = {k: round(float(v), 3) for k, v in scores.items()}

    explanations = {
        "emotional_arousal":
            f"Copy emotional-language score {copy['emotional_appeal']:.2f}; "
            f"image saturation {s['saturation']:.2f}, warmth {s['warmth']:.2f}.",
        "visual_clarity":
            f"Image edge density {s['edge_density']:.2f} (higher = busier); "
            f"contrast {s['contrast']:.2f}.",
        "attention_capture":
            f"Contrast {s['contrast']:.2f} and saturation "
            f"{s['saturation']:.2f} drive estimated saliency.",
        "relevance_potential":
            f"Copy relevance/benefit-clarity score {copy['relevance']:.2f}; "
            f"image contributes little relevance signal heuristically.",
    }
    strengths = [k for k, v in scores.items() if v >= 0.60]
    weaknesses = [k for k, v in scores.items() if v <= 0.40]
    br_score, br_expl = _heuristic_brand_relevance(
        ad_text, brand_category, brand_industry,
    )
    return {
        "scores": scores,
        "explanations": explanations,
        "brand_relevance": br_score,
        "brand_relevance_explanation": br_expl,
        # Heuristic can't see the image, so it CAN'T check image-↔-copy
        # coherence. We surface that limit honestly instead of inventing a score.
        "image_description": "(no image inspection -- heuristic mode)",
        "image_copy_coherence": 0.5,
        "image_copy_coherence_explanation": (
            "Image-↔-copy coherence cannot be checked in heuristic mode -- "
            "we can't see what's in the picture. Connect a Gemini / Claude / "
            "GPT-4o key in /settings to verify the image actually depicts "
            "what the copy says."
        ),
        "ban_risk": {
            "level": "unknown", "flags": [],
            "explanation": ("Image not inspected (heuristic mode) — can't "
                            "screen for nudity/shocking/prohibited imagery. "
                            "Connect a multimodal key for ban-risk screening."),
        },
        "strengths": strengths,
        "weaknesses": weaknesses,
        "overall": ("Heuristic estimate from image colour/contrast statistics "
                    "and copy keywords. Directional only -- connect an API "
                    "key for a multimodal-model assessment."),
    }


# ===========================================================================
# Main entry point
# ===========================================================================

def analyze_ad(image_path: str | Path,
               ad_text: str = "",
               provider: str = "auto",
               audience_hint: str | None = None,
               brand_category: str | None = None,
               brand_industry: str | None = None,
               fallback_on_error: bool = True) -> VisualAnalysisResult:
    """Analyse an ad creative (image + copy) and return calibrated scores.

    Parameters
    ----------
    image_path : path to the ad image file.
    ad_text : the ad copy/headline (may be empty).
    provider : 'auto' (default), 'claude', 'openai', or 'heuristic'.
    audience_hint : optional free-text description of the intended audience.
    fallback_on_error : if a vision API call fails, fall back to the heuristic
        scorer instead of raising (default True -- keeps a demo app running).

    Returns
    -------
    VisualAnalysisResult with scores, per-dimension explanations, strengths,
    weaknesses, and an overall summary.
    """
    b64, media_type, rgb_image, meta = _prepare_image(image_path)
    chosen = _select_provider(provider)

    brand_hint = None
    if brand_category and brand_category != "general":
        brand_hint = f"product category '{brand_category}'"
        if brand_industry:
            brand_hint += f", industry '{brand_industry}'"

    # Provider attempt order: start with `chosen`, then fall forward through
    # every other key-bearing provider before giving up to heuristic. With 8
    # providers wired, quota exhaustion on any one (or several) never strands
    # the user.
    import logging
    _log = logging.getLogger("visual_analysis")
    fallback_order = [chosen] + [p for p in _VISION_PROVIDERS if p != chosen]
    # Drop providers we don't have a key for (and that aren't the explicitly-
    # asked-for choice).
    fallback_order = [p for p in fallback_order
                      if p == provider or p == "heuristic"
                      or _get_key(_VISION_KEY_ENV.get(p, "")) is not None]
    # Pin scoring to one provider for scale-consistency (see PIN_VISION_PROVIDER).
    # The chosen provider keeps its own internal model rotation; we just don't
    # cross over to a different provider's scale for the score.
    if PIN_VISION_PROVIDER and provider == "auto" and chosen != "heuristic":
        fallback_order = [chosen, "heuristic"]

    vision_dispatch = {
        "claude":     lambda: (_analyze_claude_with_brand(
                          b64, media_type, ad_text, audience_hint,
                          brand_hint), CLAUDE_MODEL),
        "openai":     lambda: (_analyze_openai_with_brand(
                          b64, media_type, ad_text, audience_hint,
                          brand_hint), OPENAI_MODEL),
        "gemini":     lambda: _analyze_gemini_with_brand(
                          b64, media_type, ad_text, audience_hint,
                          brand_hint),
        "groq":       lambda: _analyze_groq_with_brand(
                          b64, media_type, ad_text, audience_hint,
                          brand_hint),
        "mistral":    lambda: _analyze_mistral_with_brand(
                          b64, media_type, ad_text, audience_hint,
                          brand_hint),
        "openrouter": lambda: _analyze_openrouter_with_brand(
                          b64, media_type, ad_text, audience_hint,
                          brand_hint),
        "xai":        lambda: _analyze_xai_with_brand(
                          b64, media_type, ad_text, audience_hint,
                          brand_hint),
        "together":   lambda: _analyze_together_with_brand(
                          b64, media_type, ad_text, audience_hint,
                          brand_hint),
    }

    raw = None
    model = HEURISTIC_VERSION
    attempted: list = []           # [(provider, error_or_None), ...]
    for prov in fallback_order:
        try:
            if prov == "heuristic":
                raw = _analyze_heuristic(
                    rgb_image, ad_text, brand_category, brand_industry,
                )
                model = HEURISTIC_VERSION
            elif prov in vision_dispatch:
                raw, model = vision_dispatch[prov]()
            else:
                raise ValueError(f"Unknown provider '{prov}'.")
            chosen = prov
            break
        except Exception as exc:                       # noqa: BLE001
            attempted.append((prov, str(exc)[:240]))
            _log.warning("%s vision attempt failed: %s", prov,
                          str(exc)[:200])
            if not fallback_on_error:
                raise
            continue

    if raw is None:
        # Every keyed provider failed AND fallback_on_error was True — go
        # heuristic last-resort so the page still renders.
        raw = _analyze_heuristic(
            rgb_image, ad_text, brand_category, brand_industry,
        )
        model, chosen = HEURISTIC_VERSION, "heuristic"

    if chosen == "heuristic" and attempted:
        # We tried real providers but they all failed — preserve why.
        raw["_provider_error"] = "; ".join(
            f"{p}: {e}" for p, e in attempted)

    scores = _validate_scores(raw["scores"])
    explanations = {k: str(raw.get("explanations", {}).get(k, "")).strip()
                    for k in VISUAL_SCORE_KEYS}
    return VisualAnalysisResult(
        scores=scores,
        explanations=explanations,
        strengths=raw.get("strengths", []),
        weaknesses=raw.get("weaknesses", []),
        overall=raw.get("overall", ""),
        provider=chosen,
        model=model,
        is_heuristic=(chosen == "heuristic"),
        image_meta=meta,
        ad_text=ad_text,
        brand_relevance=float(raw.get("brand_relevance", 0.5)),
        brand_relevance_explanation=str(
            raw.get("brand_relevance_explanation", "")),
        brand_relevance_source=("llm" if chosen != "heuristic" else "heuristic"),
        image_description=str(raw.get("image_description", "")),
        image_copy_coherence=float(raw.get("image_copy_coherence", 0.5)),
        image_copy_coherence_explanation=str(
            raw.get("image_copy_coherence_explanation", "")),
        creative_type=str(raw.get("creative_type", "")),
        creative_type_explanation=str(raw.get("creative_type_explanation", "")),
        ban_risk=raw.get("ban_risk") or {
            "level": "unknown", "flags": [],
            "explanation": "Image not inspected (heuristic mode).",
        },
        provider_error=str(raw.get("_provider_error", "")),
    )


# Tiny adapters so the existing _analyze_claude / _analyze_openai signatures
# don't have to change everywhere they're imported from.
def _analyze_claude_with_brand(b64, media_type, ad_text, audience_hint, brand_hint):
    try:
        import anthropic  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("anthropic not installed.") from exc
    key = _get_key("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set.")
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    message = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=1024, system=_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": _build_user_prompt(ad_text, audience_hint, brand_hint)},
            ]},
            {"role": "assistant", "content": "{"},
        ],
    )
    text = "{" + "".join(b.text for b in message.content
                          if getattr(b, "type", None) == "text")
    return _normalise_raw(_extract_json(text))


def _analyze_gemini_with_brand(b64, media_type, ad_text, audience_hint,
                                brand_hint):
    """Call Gemini vision, rotating through GEMINI_VISION_CHAIN so a 429 on
    one model falls forward to the next (each has its own daily quota).

    Returns ``(raw_dict, model_id_used)`` so the caller can record which
    specific model produced the result.
    """
    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError as exc:
        raise RuntimeError(
            "google-genai not installed -- run `pip install google-genai`."
        ) from exc
    key = _get_key("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set.")

    import base64 as _b64
    image_bytes = _b64.b64decode(b64)
    client = genai.Client(api_key=key)
    last_exc: Exception | None = None

    for model_id in GEMINI_VISION_CHAIN:
        if ("gemini", model_id) in _VISION_EXHAUSTED:
            continue
        config_kwargs: dict = {
            "system_instruction": _SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "max_output_tokens": 4096,
        }
        if "lite" not in model_id:
            # Thinking budget only applies to non-lite Gemini 2.5+ models.
            config_kwargs["thinking_config"] = gtypes.ThinkingConfig(
                thinking_budget=512)
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=[
                    gtypes.Part.from_bytes(data=image_bytes,
                                            mime_type=media_type),
                    _build_user_prompt(ad_text, audience_hint, brand_hint),
                ],
                config=gtypes.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:                       # noqa: BLE001
            last_exc = exc
            if _is_quota_error(exc):
                _VISION_EXHAUSTED.add(("gemini", model_id))
                _ph_quota("gemini", model_id, str(exc))
                continue
            raise
        raw_text = response.text
        if not raw_text:
            # Likely thinking budget ate the output. Try next model.
            continue
        _ph_ok("gemini", model_id)
        return _normalise_raw(_extract_json(raw_text)), model_id

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(
        "All Gemini vision models exhausted (each has 20 RPD on free tier).")


def _analyze_groq_with_brand(b64, media_type, ad_text, audience_hint,
                              brand_hint):
    """Groq's Llama 4 Scout multimodal — used as a free fallback when every
    Gemini model has hit its daily quota. Returns ``(raw_dict, model_id)``."""
    try:
        from groq import Groq
    except ImportError as exc:
        raise RuntimeError("groq not installed.") from exc
    key = _get_key("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set.")
    client = Groq(api_key=key)
    response = client.chat.completions.create(
        model=GROQ_VISION_MODEL,
        max_tokens=1500,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text",
                 "text": _build_user_prompt(ad_text, audience_hint,
                                             brand_hint)},
                {"type": "image_url",
                 "image_url": {"url": f"data:{media_type};base64,{b64}"}},
            ]},
        ],
    )
    text = response.choices[0].message.content
    if not text:
        raise RuntimeError(
            f"Groq vision returned no text. Model: {GROQ_VISION_MODEL}.")
    return _normalise_raw(_extract_json(text)), GROQ_VISION_MODEL


def _analyze_openai_compat_vision(env_key, base_url, model, b64, media_type,
                                    ad_text, audience_hint, brand_hint,
                                    json_format=True):
    """Generic OpenAI-compatible vision adapter. Used by Mistral / OpenRouter
    / xAI / Together — all four expose the same chat/completions schema with
    image_url content blocks."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai SDK not installed.") from exc
    key = _get_key(env_key)
    if not key:
        raise RuntimeError(f"{env_key} not set.")
    client = OpenAI(api_key=key, base_url=base_url)
    kwargs: dict = {
        "model": model,
        "max_tokens": 1500,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text",
                 "text": _build_user_prompt(ad_text, audience_hint,
                                             brand_hint)},
                {"type": "image_url",
                 "image_url": {"url": f"data:{media_type};base64,{b64}"}},
            ]},
        ],
    }
    if json_format:
        kwargs["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**kwargs)
    text = response.choices[0].message.content
    if not text:
        raise RuntimeError(f"{model} returned no text.")
    return _normalise_raw(_extract_json(text)), model


def _analyze_mistral_with_brand(b64, media_type, ad_text, audience_hint,
                                  brand_hint):
    return _analyze_openai_compat_vision(
        "MISTRAL_API_KEY", MISTRAL_BASE_URL, MISTRAL_VISION_MODEL,
        b64, media_type, ad_text, audience_hint, brand_hint)


def _analyze_openrouter_with_brand(b64, media_type, ad_text, audience_hint,
                                     brand_hint):
    return _analyze_openai_compat_vision(
        "OPENROUTER_API_KEY", OPENROUTER_BASE_URL, OPENROUTER_VISION_MODEL,
        b64, media_type, ad_text, audience_hint, brand_hint)


def _analyze_xai_with_brand(b64, media_type, ad_text, audience_hint,
                              brand_hint):
    return _analyze_openai_compat_vision(
        "XAI_API_KEY", XAI_BASE_URL, XAI_VISION_MODEL,
        b64, media_type, ad_text, audience_hint, brand_hint)


def _analyze_together_with_brand(b64, media_type, ad_text, audience_hint,
                                   brand_hint):
    # Together's free vision model 422s on response_format=json_object; the
    # system prompt + JSON extractor at parse time handles it.
    return _analyze_openai_compat_vision(
        "TOGETHER_API_KEY", TOGETHER_BASE_URL, TOGETHER_VISION_MODEL,
        b64, media_type, ad_text, audience_hint, brand_hint,
        json_format=False)


def _analyze_openai_with_brand(b64, media_type, ad_text, audience_hint, brand_hint):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai not installed.") from exc
    key = _get_key("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set.")
    client = OpenAI(api_key=key)
    response = client.chat.completions.create(
        model=OPENAI_MODEL, max_tokens=1024,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": _build_user_prompt(ad_text, audience_hint, brand_hint)},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
            ]},
        ],
    )
    return _normalise_raw(_extract_json(response.choices[0].message.content))


# ===========================================================================
# VIDEO ANALYSIS  (Phase 6) — reels / video ads via Gemini
# ===========================================================================
# Gemini natively ingests video (samples frames + audio); other providers
# don't accept video uniformly, so this path is Gemini-only. Output uses the
# SAME VisualAnalysisResult schema as the image path so every downstream consumer
# (viability gate, scores, ban_risk, brand fit) works unchanged.

_VIDEO_MIME_TYPES = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
    ".webm": "video/webm", ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo", ".3gp": "video/3gpp", ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
}
# Inline-bytes ceiling for Gemini video. Larger files would need the File API.
_MAX_VIDEO_BYTES = 20 * 1024 * 1024


def _prepare_video(video_path):
    p = Path(video_path)
    if not p.exists():
        raise FileNotFoundError(f"Video not found: {p}")
    size = p.stat().st_size
    if size > _MAX_VIDEO_BYTES:
        raise ValueError(
            f"Video is {size / 1_048_576:.1f}MB — current limit is "
            f"{_MAX_VIDEO_BYTES // 1_048_576}MB. Compress or shorten the clip.")
    mime = _VIDEO_MIME_TYPES.get(p.suffix.lower(), "video/mp4")
    return p.read_bytes(), mime, size


def _build_video_user_prompt(ad_text: str, audience_hint: str | None,
                              brand_hint: str | None = None) -> str:
    parts = ["Analyse the attached AD VIDEO together with its copy.",
             "Use the SAME JSON schema as for images — return the 4 scores, "
             "ban_risk, brand_relevance, and image_copy_coherence (treat "
             "'image_copy_coherence' as creative-vs-copy coherence for video)."]
    parts.append(f'Ad copy: "{ad_text.strip()}"' if ad_text.strip()
                 else "Ad copy: (none provided — judge the video alone)")
    if brand_hint:
        parts.append(f"Brand context: {brand_hint.strip()}")
    if audience_hint:
        parts.append(f"Intended audience: {audience_hint.strip()}")
    parts.append(
        "Specific to video, weigh: (a) hook strength in the FIRST 3 SECONDS "
        "(reflect this in attention_capture), (b) pacing and retention cues, "
        "(c) on-screen text / captions readability, (d) audio / voiceover "
        "presence and clarity, (e) overall production quality (visual_clarity), "
        "(f) ban_risk across the WHOLE video — any prohibited content at any "
        "point counts. Be strict on brand_relevance: does the video genuinely "
        "match the brand and copy, or is it stock-feel?")
    parts.append("Return the JSON object now.")
    return "\n".join(parts)


def _analyze_gemini_video_with_brand(video_bytes, mime_type, ad_text,
                                      audience_hint, brand_hint):
    """Call Gemini with a video Part, rotating models on quota."""
    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError as exc:
        raise RuntimeError("google-genai not installed.") from exc
    key = _get_key("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set.")
    client = genai.Client(api_key=key)
    last_exc: Exception | None = None
    for model_id in GEMINI_VISION_CHAIN:
        if ("gemini-video", model_id) in _VISION_EXHAUSTED:
            continue
        config_kwargs: dict = {
            "system_instruction": _SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "max_output_tokens": 4096,
        }
        if "lite" not in model_id:
            config_kwargs["thinking_config"] = gtypes.ThinkingConfig(
                thinking_budget=512)
        try:
            response = client.models.generate_content(
                model=model_id,
                contents=[
                    gtypes.Part.from_bytes(data=video_bytes,
                                            mime_type=mime_type),
                    _build_video_user_prompt(ad_text, audience_hint, brand_hint),
                ],
                config=gtypes.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:                       # noqa: BLE001
            last_exc = exc
            if _is_quota_error(exc):
                _VISION_EXHAUSTED.add(("gemini-video", model_id))
                _ph_quota("gemini-video", model_id, str(exc))
                continue
            raise
        text = getattr(response, "text", None)
        if text:
            try:
                parsed = _normalise_raw(_extract_json(text))
                _ph_ok("gemini-video", model_id)
                return parsed, model_id
            except (ValueError, json.JSONDecodeError) as parse_exc:
                # Gemini occasionally returns slightly-broken JSON (trailing
                # commas, smart quotes). Don't poison the whole run on one
                # bad sample — try the next model in GEMINI_VISION_CHAIN. The
                # error is tagged with the original parse text so the
                # heuristic-fallback path can surface a HONEST "service
                # returned bad data" message instead of "quota exhausted".
                last_exc = RuntimeError(
                    f"Gemini video returned malformed JSON ({model_id}): "
                    f"{str(parse_exc)[:160]}")
                continue
        last_exc = RuntimeError("Gemini video response had no text payload.")
    raise (last_exc or RuntimeError("All Gemini video models exhausted."))


def analyze_ad_video(video_path,
                     ad_text: str,
                     *,
                     audience_hint: str | None = None,
                     brand_category: str = "general",
                     brand_industry: str = ""):
    """Analyse a video creative. Returns the same VisualAnalysisResult schema as
    analyze_ad so the viability gate, scores, ban_risk, brand fit and the
    explanation module all keep working unchanged."""
    brand_hint = None
    if brand_category and brand_category != "general":
        brand_hint = f"product category '{brand_category}'"
        if brand_industry:
            brand_hint += f", industry '{brand_industry}'"

    # Heuristic-marked fallback used when Gemini isn't usable — the safety
    # gate will then refuse the forecast (same philosophy as the image path).
    def _heuristic_block(error: str) -> VisualAnalysisResult:
        scores = {k: 0.5 for k in VISUAL_SCORE_KEYS}
        return VisualAnalysisResult(
            scores=scores,
            explanations={k: "Video not analysed (vision unavailable)."
                          for k in VISUAL_SCORE_KEYS},
            strengths=[], weaknesses=[
                "Couldn't analyse the video — vision model unavailable."],
            overall="Video creative could not be inspected.",
            provider="gemini", model="(unavailable)",
            is_heuristic=True, provider_error=error[:240],
            brand_relevance=0.5, brand_relevance_explanation="",
            brand_relevance_source="heuristic",
            image_description="(video — not analysed)",
            image_copy_coherence=0.5,
            image_copy_coherence_explanation="",
            ban_risk={"level": "unknown", "flags": [],
                       "explanation": "Vision unavailable for ban-risk screen."},
        )

    try:
        video_bytes, mime, _size = _prepare_video(video_path)
    except Exception as exc:                       # noqa: BLE001
        return _heuristic_block(f"prepare_video: {exc}")

    try:
        raw, model_id = _analyze_gemini_video_with_brand(
            video_bytes, mime, ad_text, audience_hint, brand_hint)
    except Exception as exc:                       # noqa: BLE001
        return _heuristic_block(f"gemini_video: {exc}")

    # Same construction as the image path's tail.
    br_raw = raw.get("ban_risk") or {}
    ban_risk = {
        "level": str(br_raw.get("level", "unknown")).lower(),
        "flags": list(br_raw.get("flags", [])),
        "explanation": str(br_raw.get("explanation", "")),
    }
    # Strict safety: a parseable-but-degenerate response (no real ban-risk screen,
    # or no scores) is NOT a genuine inspection — treat it as unavailable so the
    # pipeline's safety gate refuses the forecast rather than passing a video we
    # didn't actually evaluate.
    if ban_risk["level"] not in ("none", "low", "medium", "high") \
            or not raw.get("scores"):
        return _heuristic_block(
            "Gemini returned an incomplete video analysis (no usable ban-risk "
            "screen / scores) — treated as not inspected.")
    scores = _validate_scores(raw.get("scores", {}))
    def _flt(x, d=0.5):
        try: return float(x) if x is not None else d
        except Exception: return d
    return VisualAnalysisResult(
        scores=scores,
        explanations=raw.get("explanations", {}),
        strengths=list(raw.get("strengths", [])),
        weaknesses=list(raw.get("weaknesses", [])),
        overall=str(raw.get("overall", "")),
        provider="gemini", model=model_id,
        is_heuristic=False,
        brand_relevance=_flt(raw.get("brand_relevance")),
        brand_relevance_explanation=str(raw.get("brand_relevance_explanation", "")),
        brand_relevance_source="llm",
        image_description=str(raw.get("image_description", "")),
        image_copy_coherence=_flt(raw.get("image_copy_coherence")),
        image_copy_coherence_explanation=str(raw.get("image_copy_coherence_explanation", "")),
        creative_type=str(raw.get("creative_type", "")).strip().lower(),
        creative_type_explanation=str(raw.get("creative_type_explanation", "")).strip(),
        ban_risk=ban_risk,
    )


# ===========================================================================
# CLI entry point
# ===========================================================================

def _make_demo_image(path: Path) -> None:
    """Create a simple test ad image so the demo runs without an upload."""
    img = Image.new("RGB", (1080, 1080), (245, 240, 230))
    draw = ImageDraw.Draw(img)
    draw.ellipse([340, 220, 740, 620], fill=(220, 70, 60))      # focal point
    draw.rectangle([140, 720, 940, 820], fill=(30, 30, 40))
    draw.text((180, 755), "LIMITED OFFER -- 40% OFF TODAY", fill=(255, 255, 255))
    img.save(path)


def _main() -> None:
    print("Available providers:", available_providers())

    demo_path = _PROJECT_ROOT / "data" / "raw" / "demo_ad.png"
    _make_demo_image(demo_path)
    print(f"Created demo image -> {demo_path}\n")

    result = analyze_ad(
        demo_path,
        ad_text="Limited offer! Save 40% today -- loved by thousands.",
        provider="heuristic",                # force heuristic for the demo
        audience_hint="deal-seeking online shoppers, 25-44",
    )
    print(result.summary())
    print("\nPer-dimension explanations:")
    for k in VISUAL_SCORE_KEYS:
        print(f"  - {k}: {result.explanations[k]}")
    print("\nJSON output:")
    print(result.to_json())


if __name__ == "__main__":
    _main()
