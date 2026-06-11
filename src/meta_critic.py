"""Meta-specific paid-ad critic (Facebook + Instagram).

Built on Ivan Falco's `ads-skills` Meta knowledge base (licensed for use):
    creative-strategy.md              - Creative IS targeting, mosquito-
                                          repellent principle, 8 concept
                                          types, ad copy formula, 50/30/20
                                          budget, per-placement rules
    message-validation.md             - Quality scoring (Urgency / Budget /
                                          Fit, each 0-3), "sell the click
                                          not the product"
    offer-strategy.md                 - Offer-stage matching, ACV-tier
                                          guidance, no-brainer framework
    advantage-plus.md                 - A+ campaign creative requirements
    creative-cadence-operating-system.md (extends fatigue.py separately)
    creative-fatigue-detection.md     (extends fatigue.py separately)

Different positioning vs the LinkedIn critic + VIE:
- VIE scores ORGANIC craft potential for short-video (platform-agnostic).
- LinkedIn critic scores B2B copy + funnel fit for LinkedIn placements.
- Meta critic scores what Ivan calls "the #1 variable for Meta success":
  the OFFER strength + creative-as-targeting + ad-copy-formula compliance.
  These are Meta-specific levers VIE and the LinkedIn critic don't cover.

Runs only when ``brief.platform_id`` starts with ``meta_``. Skipped
silently otherwise. Cost: one Gemini text call per Meta forecast
(~£0.003), cached on the campaign row.

Attribution required in UI surfaces:
    "Knowledge base adapted from Ivan Falco's ads-skills, licensed
     for AdProof's use."
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import GEMINI_VISION_CHAIN  # noqa: E402

try:
    from src.visual_analysis import (_VISION_EXHAUSTED, _get_key,
                                     _is_quota_error, _ph_ok, _ph_quota)
except ImportError:                                    # standalone
    from visual_analysis import (_VISION_EXHAUSTED, _get_key,
                                 _is_quota_error, _ph_ok, _ph_quota)

__all__ = [
    "MetaCritique",
    "critique_meta",
    "META_DIMENSIONS",
    "META_DIMENSION_WEIGHTS",
    "CONCEPT_TYPES",
    "is_meta_platform",
]


# Six Meta-tuned dimensions (each 0-10, weighted into composite /10).
# The weighting reflects Ivan's order of importance: offer > message-fit
# > creative-as-targeting > hook > cta > format. Per Ivan, "ads never
# outperform a bad offer" — that gets the heaviest weight.
META_DIMENSIONS = (
    "offer_strength",          # Strongest lever per Ivan
    "message_market_fit",      # Copy must match the awareness stage
    "creative_as_targeting",   # Mosquito repellent — repels non-ICP
    "hook",                    # First sentence / 3 seconds
    "cta_alignment",           # CTA matches funnel stage (cold != demo)
    "format_execution",        # Placement-aware, density, etc.
)
META_DIMENSION_WEIGHTS = {
    "offer_strength":         0.25,
    "message_market_fit":     0.20,
    "creative_as_targeting":  0.15,
    "hook":                   0.15,
    "cta_alignment":          0.15,
    "format_execution":       0.10,
}
assert abs(sum(META_DIMENSION_WEIGHTS.values()) - 1.0) < 1e-6


# Ivan's 8 Meta concept types (creative-strategy.md). The critic
# classifies the detected concept and proposes 2-3 stronger alternatives.
CONCEPT_TYPES = (
    "problem_solution",   # Name specific pain, show fix
    "before_after",        # Transformation
    "ugc_founder",         # UGC or founder-talking-to-camera
    "meme_humor",          # Industry humor / pattern interrupt
    "data_statistics",     # Lead with a stat
    "testimonial",         # Customer quote
    "case_study",          # Specific company + result
    "comparison",          # Your solution vs status quo / competitor
)


# Funnel stage maps brief.objective to Meta's cold/warm/hot framing.
# Critical because Ivan's offer-strategy.md says demo asks fail on cold
# high-ACV — we want to flag that mismatch explicitly.
OBJECTIVE_TO_META_STAGE = {
    "awareness":     ("cold",  "Prospecting"),
    "consideration": ("warm",  "Remarketing"),
    "conversion":    ("hot",   "High-Intent Retargeting"),
}


# Placement-aware aspect ratios, from creative-strategy.md.
_PLACEMENT_RULES = {
    "meta_fb_feed_image":       {"ratio": "1:1 or 4:5", "media": "image", "notes": "Primary B2B placement"},
    "meta_fb_feed_video":       {"ratio": "1:1 or 4:5", "media": "video", "notes": "Long copy supported"},
    "meta_fb_reels":            {"ratio": "9:16",       "media": "video", "notes": "Full-screen vertical. 12% higher conversions when dedicated 9:16."},
    "meta_ig_feed_image":       {"ratio": "1:1 or 4:5", "media": "image", "notes": "Visual-led brands"},
    "meta_ig_reels":            {"ratio": "9:16",       "media": "video", "notes": "Full-screen vertical, dedicated creative required"},
    "meta_ig_stories":          {"ratio": "9:16",       "media": "video", "notes": "Time-sensitive offers"},
}


# Cold-traffic CTA red flags from offer-strategy.md
_COLD_CTA_RED_FLAGS = {
    "request a demo", "book a demo", "schedule a demo", "get a demo",
    "talk to sales", "contact sales", "speak to sales",
}


@dataclass
class MetaCritique:
    """6-dim Meta scorecard + Ivan-derived audit + actionable rewrites."""
    scores: dict
    composite: float
    grade: str
    explanations: dict
    # Concept + funnel
    detected_concept: str = ""
    recommended_concepts: list = field(default_factory=list)
    detected_funnel_stage: str = ""
    intended_funnel_stage: str = ""
    stage_mismatch_warning: str = ""
    # Offer audit (Ivan's no-brainer framework)
    offer_no_brainer_pass: dict = field(default_factory=dict)
    offer_issues: list = field(default_factory=list)
    # Ad copy formula compliance
    copy_formula_gaps: list = field(default_factory=list)
    # Creative-as-targeting (mosquito repellent)
    icp_specificity_score: int = 0     # /10 (would non-ICP scroll past?)
    icp_specificity_issues: list = field(default_factory=list)
    # Format / placement
    placement_findings: list = field(default_factory=list)
    # Hook autopsy
    hook_score: int = 0
    hook_alternatives: list = field(default_factory=list)
    # Quality-score prediction (Urgency/Budget/Fit, each /3 → /9)
    predicted_quality_score: dict = field(default_factory=dict)
    # Deterministic findings
    deterministic_findings: list = field(default_factory=list)
    # Diagnosis
    biggest_strength: str = ""
    biggest_weakness: str = ""
    one_specific_fix: str = ""
    # Provenance
    provider: str = "gemini"
    model: str = ""
    is_skipped: bool = False
    skipped_reason: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def is_meta_platform(platform_id: str) -> bool:
    return (platform_id or "").lower().startswith("meta_")


# ---------------------------------------------------------------------------
# Deterministic pre-flight checks (Ivan-aware)
# ---------------------------------------------------------------------------

def _deterministic_findings(*, headline: str, primary_text: str, cta: str,
                              platform_id: str, objective: str,
                              avg_order_value: float | None) -> list[str]:
    """Cheap, no-API Meta-specific checks before the LLM critic runs."""
    findings: list[str] = []

    stage, _label = OBJECTIVE_TO_META_STAGE.get(objective.lower(),
                                                 ("warm", "Remarketing"))

    # Demo-on-cold red flag for high-ACV (per offer-strategy.md)
    cta_l = (cta or "").strip().lower()
    if stage == "cold" and cta_l in _COLD_CTA_RED_FLAGS:
        is_high_acv = bool(avg_order_value and avg_order_value >= 30_000)
        if is_high_acv:
            findings.append(
                f'CTA "{cta}" on a cold Meta audience for high-ACV (£{avg_order_value:,.0f}) '
                "is the #1 mistake in Ivan's offer-strategy framework. Cold Meta = "
                "discovery mode, not buying mode. Demo asks burn budget on garbage "
                "leads. Move to a benchmark report / ROI calculator / assessment "
                "offer instead, retarget engagers with the demo."
            )
        else:
            findings.append(
                f'Demo-style CTA "{cta}" on a cold audience converts low. Even at '
                "SMB ACV, consider a lower-friction offer (interactive tour, free "
                "calculator) for the cold layer."
            )

    # Placement-specific aspect-ratio + creative type advice
    pl = _PLACEMENT_RULES.get(platform_id.lower())
    if pl:
        if "9:16" in pl["ratio"]:
            findings.append(
                f"{platform_id.replace('_', ' ')} runs in {pl['ratio']} — dedicated "
                f"9:16 creative is non-negotiable. {pl['notes']}"
            )

    # Length checks against Ivan's "first 2-3 lines before See More" rule
    body = (primary_text or "").strip()
    if body:
        first_chunk = body[:125]
        first_lines = first_chunk.count("\n") + 1
        if first_lines == 1 and len(body) > 300:
            findings.append(
                "Long primary text but no line breaks in the first 125 chars — "
                "most Meta users won't expand 'See More'. Front-load the offer "
                "+ pain in the first 2-3 lines."
            )

    # Missing CTA when objective is conversion
    if objective.lower() == "conversion" and not cta_l:
        findings.append(
            "No CTA set for a conversion-objective Meta ad. Conversion campaigns "
            "without a clear ask under-deliver — pick a specific verb-led CTA."
        )

    return findings


# ---------------------------------------------------------------------------
# Gemini prompt
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a senior B2B Meta-ads strategist (Facebook + Instagram), "
    "trained on Ivan Falco's ads-skills knowledge base. Your job: "
    "critique a paid Meta ad CREATIVE — not the campaign, not the "
    "targeting, not paid-CTR forecasting. You are scoring CRAFT QUALITY "
    "for paid Meta use.\n\n"
    "Use Ivan's specific frameworks:\n"
    "  - Creative IS targeting (mosquito-repellent principle)\n"
    "  - The 7-step ad copy formula (DIRECT OFFER → PAIN → SOLUTION → "
    "PAIN EXPLAINED → SOLUTION EXPLAINED → SOCIAL PROOF → CTA)\n"
    "  - 8 concept types (problem_solution, before_after, ugc_founder, "
    "meme_humor, data_statistics, testimonial, case_study, comparison)\n"
    "  - Offer-stage matching (cold ≠ demo for high-ACV)\n"
    "  - Predicted quality score (Urgency / Budget / Fit, each 0-3)\n\n"
    "Be ruthlessly specific. Cite the concrete line that earned each "
    "score. Don't pad. Most ads score 5-7 on each dimension; reserve "
    "9-10 for genuinely strong work.\n\n"
    "Respond ONLY with the requested JSON, no prose outside."
)


def _user_prompt(*, headline: str, primary_text: str, description: str,
                  cta: str, link: str, objective: str, platform_id: str,
                  audience_hint: str, industry: str, geo: str,
                  avg_order_value: float | None,
                  deterministic_findings: list[str],
                  has_image: bool, has_video: bool) -> str:
    stage, stage_label = OBJECTIVE_TO_META_STAGE.get(objective.lower(),
                                                       ("warm", "Remarketing"))
    pl = _PLACEMENT_RULES.get(platform_id.lower(), {})
    media_desc = ("video creative attached" if has_video
                  else "image creative attached" if has_image
                  else "no visual — text-only Meta ad")
    aov_desc = f"£{avg_order_value:,.0f}" if avg_order_value else "unknown"
    det_block = ""
    if deterministic_findings:
        det_block = "\n\nDETERMINISTIC FINDINGS (already detected):\n" + \
                    "\n".join(f"- {f}" for f in deterministic_findings)
    pl_block = ""
    if pl:
        pl_block = (f"\nPlacement-specific rules: {platform_id} runs at "
                    f"{pl['ratio']} ({pl['media']}). {pl['notes']}")
    return (
        f"Critique this Meta paid ad. Format: {media_desc}.\n\n"
        f"Headline: \"{headline.strip()}\"\n"
        f"Primary text: \"{primary_text.strip()}\"\n"
        f"Description: \"{description.strip()}\"\n"
        f"CTA: \"{cta.strip()}\"\n"
        f"Destination URL: \"{link.strip()}\"\n"
        f"Campaign objective: {objective} (Meta stage: {stage} / {stage_label})\n"
        f"Target audience: {audience_hint[:300]}\n"
        f"Industry context: {industry}, geo: {geo}, avg order value: {aov_desc}"
        f"{pl_block}{det_block}\n\n"
        "--- TASK ---\n\n"
        "Score 6 Meta-tuned dimensions (each 0-10), classify the creative's "
        "concept type from Ivan's 8, audit the offer against the no-brainer "
        "framework, check ad-copy-formula compliance, predict the quality "
        "score (Urgency/Budget/Fit), and propose 3 stronger hooks.\n\n"
        "Return EXACTLY this JSON (no extra keys):\n"
        "{\n"
        "  \"scores\": {\n"
        "    \"offer_strength\":        int 0-10,  // Strongest lever. Does it pass the no-brainer test? Value asymmetry, unavailable elsewhere, specific outcome.\n"
        "    \"message_market_fit\":    int 0-10,  // Does the copy match the awareness stage? Cold buyers need different message than warm.\n"
        "    \"creative_as_targeting\": int 0-10,  // Mosquito repellent. Would a non-ICP person immediately scroll past?\n"
        "    \"hook\":                  int 0-10,  // First 2-3 lines / first 3s — does it stop a scroller in their target role?\n"
        "    \"cta_alignment\":         int 0-10,  // Does the CTA match the funnel stage? Cold + 'Book demo' fails for high-ACV.\n"
        "    \"format_execution\":      int 0-10   // Placement-aware aspect ratio, copy density, See-More-aware structure.\n"
        "  },\n"
        "  \"explanations\": {\n"
        "    \"offer_strength\":        \"one short sentence — cite the offer or its absence\",\n"
        "    \"message_market_fit\":    \"...\", \"creative_as_targeting\": \"...\",\n"
        "    \"hook\":                  \"...\", \"cta_alignment\":         \"...\",\n"
        "    \"format_execution\":      \"...\"\n"
        "  },\n"
        "  \"detected_concept\": \"one of: problem_solution | before_after | ugc_founder | meme_humor | data_statistics | testimonial | case_study | comparison\",\n"
        "  \"recommended_concepts\": [\n"
        "    {\"concept\": \"<one of the 8>\", \"why\": \"why this concept would lift performance for the stage + audience\"},\n"
        "    {\"concept\": \"...\", \"why\": \"...\"}\n"
        "  ],\n"
        "  \"detected_funnel_stage\": \"cold | warm | hot\",\n"
        "  \"stage_mismatch_warning\": \"empty if detected matches intended; one sentence if not\",\n"
        "  \"offer_no_brainer_pass\": {\n"
        "    \"value_asymmetry\":      \"Pass | Fail\",\n"
        "    \"unavailable_elsewhere\":\"Pass | Fail\",\n"
        "    \"problem_solution_fit\": \"Pass | Fail\",\n"
        "    \"specificity\":          \"Pass | Fail\",\n"
        "    \"immediate_gratification\":\"Pass | Fail\",\n"
        "    \"low_friction\":         \"Pass | Fail\"\n"
        "  },\n"
        "  \"offer_issues\": [\"specific issues with the offer the ad is pushing\"],\n"
        "  \"copy_formula_gaps\": [\"which step of Ivan's 7-step formula is missing or weak — be specific (e.g. 'No PAIN EXPLAINED — jumps from offer to social proof')\"],\n"
        "  \"icp_specificity_score\": int 0-10,\n"
        "  \"icp_specificity_issues\": [\"specific evidence that a non-ICP person might engage instead of scrolling past\"],\n"
        "  \"placement_findings\": [\"placement-specific issues — wrong aspect ratio for the placement, density problems, etc.\"],\n"
        "  \"hook_score\": int 0-10,\n"
        "  \"hook_alternatives\": [\n"
        "    {\"hook\": \"new opening line, ≤120 chars\", \"reason\": \"why it lifts — cite the lever (specificity, urgency, role-callout, problem naming)\"},\n"
        "    {\"hook\": \"...\", \"reason\": \"...\"},\n"
        "    {\"hook\": \"...\", \"reason\": \"...\"}\n"
        "  ],\n"
        "  \"predicted_quality_score\": {\n"
        "    \"urgency\": int 0-3,    // Would this attract prospects with active urgency? 0 = passive browsing, 3 = burning problem\n"
        "    \"budget\":  int 0-3,    // Would this attract prospects with budget? 0 = no budget signal, 3 = ICP with clear budget\n"
        "    \"fit\":     int 0-3,    // Would the lead match ICP? 0 = repels ICP, 3 = perfect ICP magnet\n"
        "    \"total\":   int 0-9,    // sum of the above\n"
        "    \"rationale\": \"one line on why\"\n"
        "  },\n"
        "  \"biggest_strength\": \"single strongest thing\",\n"
        "  \"biggest_weakness\": \"single most limiting thing\",\n"
        "  \"one_specific_fix\": \"if the user does ONE thing tomorrow, what is it? Tactical.\"\n"
        "}"
    )


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    if not text:
        raise ValueError("Empty response.")
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError(f"No JSON object found: {text[:200]}")
    return json.loads(m.group(0))


def _clip_int(v, lo: int = 0, hi: int = 10) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return (lo + hi) // 2


def _composite_from_scores(scores: dict) -> float:
    total = sum(scores.get(k, 0) * META_DIMENSION_WEIGHTS[k]
                for k in META_DIMENSIONS)
    return round(total, 1)


def _grade_for(composite: float) -> str:
    if composite >= 9.0:
        return "A+"
    if composite >= 8.0:
        return "A"
    if composite >= 7.0:
        return "B"
    if composite >= 5.5:
        return "C"
    if composite >= 4.0:
        return "D"
    return "F"


def _skipped(reason: str) -> MetaCritique:
    return MetaCritique(
        scores={k: 0 for k in META_DIMENSIONS},
        composite=0.0, grade="—",
        explanations={k: "" for k in META_DIMENSIONS},
        is_skipped=True, skipped_reason=reason,
    )


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def critique_meta(*, headline: str = "",
                   primary_text: str = "",
                   description: str = "",
                   cta: str = "",
                   link: str = "",
                   objective: str = "consideration",
                   platform_id: str = "meta_facebook",
                   audience_hint: str = "",
                   industry: str = "",
                   geo: str = "UK",
                   avg_order_value: float | None = None,
                   image_path: str | None = None,
                   video_path: str | None = None) -> MetaCritique:
    """Critique a Meta paid ad on Ivan's framework.

    Skipped silently when:
      - platform_id is NOT a Meta placement
      - ADPROOF_META_CRITIC_ENABLED env flag is off
      - no Gemini key
      - all providers exhausted
    """
    if not is_meta_platform(platform_id):
        return _skipped(f"Platform {platform_id} is not Meta — critic skipped.")
    if os.environ.get("ADPROOF_META_CRITIC_ENABLED", "1").lower() in ("0", "false", "no"):
        return _skipped("Meta critic disabled via env flag.")
    if not (headline or primary_text or description):
        return _skipped("No copy provided — nothing to critique.")

    det = _deterministic_findings(
        headline=headline, primary_text=primary_text, cta=cta,
        platform_id=platform_id, objective=objective,
        avg_order_value=avg_order_value)

    user = _user_prompt(
        headline=headline, primary_text=primary_text, description=description,
        cta=cta, link=link, objective=objective, platform_id=platform_id,
        audience_hint=audience_hint, industry=industry, geo=geo,
        avg_order_value=avg_order_value,
        deterministic_findings=det,
        has_image=bool(image_path), has_video=bool(video_path),
    )

    raw: dict = {}
    used_model = ""
    last_exc: Exception | None = None

    if _get_key("GEMINI_API_KEY"):
        try:
            from google import genai
            from google.genai import types as gtypes
            client = genai.Client(api_key=_get_key("GEMINI_API_KEY"))
            for model_id in GEMINI_VISION_CHAIN:
                if ("gemini-meta-critic", model_id) in _VISION_EXHAUSTED:
                    continue
                try:
                    response = client.models.generate_content(
                        model=model_id,
                        contents=[user],
                        config=gtypes.GenerateContentConfig(
                            system_instruction=_SYSTEM,
                            response_mime_type="application/json",
                            max_output_tokens=4096,
                        ),
                    )
                except Exception as exc:                              # noqa: BLE001
                    last_exc = exc
                    if _is_quota_error(exc):
                        _VISION_EXHAUSTED.add(("gemini-meta-critic", model_id))
                        _ph_quota("gemini-meta-critic", model_id, str(exc))
                        continue
                    last_exc = exc
                    break
                text = getattr(response, "text", None)
                if not text:
                    continue
                try:
                    raw = _extract_json(text)
                    used_model = model_id
                    _ph_ok("gemini-meta-critic", model_id)
                    break
                except (ValueError, json.JSONDecodeError) as exc:
                    last_exc = exc
                    continue
        except ImportError:
            pass

    if not raw:
        return _skipped(
            f"Meta critic unavailable: {last_exc or 'no provider configured'}.")

    # ---- Normalise + clip ----
    scores_raw = raw.get("scores") or {}
    scores = {k: _clip_int(scores_raw.get(k)) for k in META_DIMENSIONS}
    explanations_raw = raw.get("explanations") or {}
    explanations = {k: str(explanations_raw.get(k, "")).strip()
                    for k in META_DIMENSIONS}

    detected_concept = str(raw.get("detected_concept", "")).strip().lower()
    if detected_concept not in CONCEPT_TYPES:
        detected_concept = ""

    recommended_concepts_raw = raw.get("recommended_concepts") or []
    recommended_concepts = []
    for r in recommended_concepts_raw[:5]:
        if isinstance(r, dict):
            c = str(r.get("concept", "")).strip().lower()
            why = str(r.get("why", "")).strip()
            if c in CONCEPT_TYPES:
                recommended_concepts.append({"concept": c, "why": why})

    intended_stage = OBJECTIVE_TO_META_STAGE.get(objective.lower(),
                                                   ("warm", "Remarketing"))[0]
    detected_stage = str(raw.get("detected_funnel_stage", "")).strip().lower()
    if detected_stage not in ("cold", "warm", "hot"):
        detected_stage = ""

    no_brainer_raw = raw.get("offer_no_brainer_pass") or {}
    no_brainer = {}
    for k in ("value_asymmetry", "unavailable_elsewhere", "problem_solution_fit",
              "specificity", "immediate_gratification", "low_friction"):
        v = str(no_brainer_raw.get(k, "")).strip().capitalize()
        if v in ("Pass", "Fail"):
            no_brainer[k] = v

    hook_alts_raw = raw.get("hook_alternatives") or []
    hook_alts = []
    for ha in hook_alts_raw[:5]:
        if isinstance(ha, dict):
            h = str(ha.get("hook", "")).strip()
            r_ = str(ha.get("reason", "")).strip()
            if h:
                hook_alts.append({"hook": h, "reason": r_})

    qs_raw = raw.get("predicted_quality_score") or {}
    qs = {
        "urgency":   _clip_int(qs_raw.get("urgency"), 0, 3),
        "budget":    _clip_int(qs_raw.get("budget"),  0, 3),
        "fit":       _clip_int(qs_raw.get("fit"),     0, 3),
        "rationale": str(qs_raw.get("rationale", "")).strip(),
    }
    qs["total"] = qs["urgency"] + qs["budget"] + qs["fit"]

    def _strlist(key: str, cap: int = 6) -> list:
        out = []
        for v in (raw.get(key) or [])[:cap]:
            s = str(v).strip()
            if s:
                out.append(s)
        return out

    composite = _composite_from_scores(scores)
    return MetaCritique(
        scores=scores,
        composite=composite,
        grade=_grade_for(composite),
        explanations=explanations,
        detected_concept=detected_concept,
        recommended_concepts=recommended_concepts,
        detected_funnel_stage=detected_stage,
        intended_funnel_stage=intended_stage,
        stage_mismatch_warning=str(raw.get("stage_mismatch_warning", "")).strip(),
        offer_no_brainer_pass=no_brainer,
        offer_issues=_strlist("offer_issues"),
        copy_formula_gaps=_strlist("copy_formula_gaps"),
        icp_specificity_score=_clip_int(raw.get("icp_specificity_score")),
        icp_specificity_issues=_strlist("icp_specificity_issues"),
        placement_findings=_strlist("placement_findings"),
        hook_score=_clip_int(raw.get("hook_score")),
        hook_alternatives=hook_alts,
        predicted_quality_score=qs,
        deterministic_findings=det,
        biggest_strength=str(raw.get("biggest_strength", "")).strip(),
        biggest_weakness=str(raw.get("biggest_weakness", "")).strip(),
        one_specific_fix=str(raw.get("one_specific_fix", "")).strip(),
        provider="gemini",
        model=used_model,
        raw=raw,
    )
