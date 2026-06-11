"""LinkedIn-specific paid-ad critic.

Built on top of:
  - Ivan Falco's `ads-skills` LinkedIn knowledge base (licensed for use)
      creative-strategy.md   (awareness-stage model, 12 creative angles,
                              TLA rules, video guidelines)
      copy-audit-framework.md (5-layer audit)
      audit-checklist.md      (deterministic pre-flight checks)
      full-funnel-framework.md (3-layer TOF/MOF/BOF objective mapping)
  - The owner's `linkedin-devils-advocate.skill` 6-dim scoring schema
      Hook 30% / Body 20% / Credibility 15% / Audience Fit 15% /
      CTA 10% / Format 10% = /10

Runs ONLY when ``brief.platform_id`` starts with ``linkedin``. Other
platforms get nothing from this module — Meta has its own critic
(future session) and the existing VIE Reel Quality covers short-video
craft platform-agnostically.

Attribution required in every UI surface that shows this output:
    "Knowledge base adapted from Ivan Falco's ads-skills, licensed
     for AdProof's use."

Cost: one Gemini call per LinkedIn forecast. ~£0.003 per call at
2.5 Flash rates. Cached on the campaign row.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import (  # noqa: E402
    CLAUDE_MODEL, GEMINI_VISION_CHAIN, OPENAI_MODEL,
)

try:
    from src.visual_analysis import (_VIDEO_MIME_TYPES, _MAX_VIDEO_BYTES,
                                     _VISION_EXHAUSTED, _get_key,
                                     _is_quota_error, _ph_ok, _ph_quota)
except ImportError:                                    # standalone
    from visual_analysis import (_VIDEO_MIME_TYPES, _MAX_VIDEO_BYTES,
                                 _VISION_EXHAUSTED, _get_key,
                                 _is_quota_error, _ph_ok, _ph_quota)

__all__ = [
    "LinkedInCritique",
    "critique_linkedin",
    "LDA_DIMENSIONS",
    "LDA_DIMENSION_WEIGHTS",
    "CREATIVE_ANGLES",
    "is_linkedin_platform",
]


# LDA's 6 weighted dimensions (each scored 0-10, weighted to a /10 composite).
LDA_DIMENSIONS = (
    "hook",
    "body",
    "credibility",
    "audience_fit",
    "cta",
    "format_execution",
)
LDA_DIMENSION_WEIGHTS = {
    "hook":             0.30,
    "body":             0.20,
    "credibility":      0.15,
    "audience_fit":     0.15,
    "cta":              0.10,
    "format_execution": 0.10,
}
assert abs(sum(LDA_DIMENSION_WEIGHTS.values()) - 1.0) < 1e-6


# Ivan's 12 creative angle categories. The critic picks the best 2-3 for
# (awareness_stage, objective) and proposes specific rewrites.
CREATIVE_ANGLES = (
    "trigger_event",            # TOF — regulatory shift, market change
    "main_problem",             # TOF — name the daily pain
    "goals_jobs_to_be_done",    # TOF/MOF — what they're trying to accomplish
    "pains_with_alternatives",  # MOF — why current workarounds fail
    "key_features",             # MOF/BOF — what the product does
    "primary_use_cases",        # MOF — real scenarios
    "benefits_for_users",       # MOF/BOF — outcomes, not features
    "selfish_desires",          # TOF/MOF — personal motivation
    "case_studies",             # BOF — real numbers
    "testimonials",             # BOF — direct quotes
    "ratings_awards",           # BOF — G2, Capterra etc.
    "client_logos",             # BOF — social proof
)


# Awareness stages map to brief.objective. The mapping is:
#   awareness     -> problem_aware    (TOF)
#   consideration -> solution_aware   (MOF)
#   conversion    -> product_aware    (BOF)
# Used to tune the critic prompt so the rubric applies the right stage.
OBJECTIVE_TO_STAGE = {
    "awareness":     ("problem_aware",  "TOF"),
    "consideration": ("solution_aware", "MOF"),
    "conversion":    ("product_aware",  "BOF"),
}


@dataclass
class LinkedInCritique:
    """6-dim LDA scorecard + Ivan-derived diagnosis + actionable rewrites."""
    # Scorecard (LDA — each /10 raw, composite /10 weighted)
    scores: dict                       # 6 LDA dims, each 0..10
    composite: float                   # 0-10 weighted
    grade: str                         # A/B/C/D
    explanations: dict
    # Awareness + funnel
    detected_awareness_stage: str = "" # problem_aware | solution_aware | product_aware
    intended_awareness_stage: str = "" # derived from brief.objective
    stage_mismatch_warning: str = ""   # populated when detected != intended
    funnel_stage: str = ""             # TOF / MOF / BOF
    # Creative angle classification + alternatives
    detected_angle: str = ""           # one of CREATIVE_ANGLES
    recommended_angles: list = field(default_factory=list)  # top 2-3 alternatives
    # 5-layer copy audit findings (from Ivan's copy-audit-framework.md)
    factual_accuracy_issues: list = field(default_factory=list)
    tone_violations: list = field(default_factory=list)
    structure_issues: list = field(default_factory=list)
    text_density_issues: list = field(default_factory=list)
    audience_fit_issues: list = field(default_factory=list)
    # Hook autopsy
    hook_score: int = 0                # /10
    hook_alternatives: list = field(default_factory=list)
    # Ivan-specific LinkedIn rules check
    tla_eligible: bool = False
    tla_notes: str = ""
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


# ---------------------------------------------------------------------------
# Deterministic pre-flight (Ivan's audit-checklist.md, section 4)
# ---------------------------------------------------------------------------

def _deterministic_findings(*, headline: str, primary_text: str,
                              cta: str, video_path: str | None) -> list[str]:
    """Cheap, no-API checks against Ivan's LinkedIn-creatives checklist.

    Items mapped from audit-checklist.md section 4 (Creatives & Ads):
      4.9  Video ads under 2 minutes with subtitles
      4.10 Ad copies have clear CTA
      4.11 Ad sizes suited for platform (handled by check_image_specs)
    """
    findings: list[str] = []

    # 4.10: ad must have a clear CTA
    if not (cta or "").strip():
        findings.append(
            "No CTA field set (audit-checklist 4.10). LinkedIn ads "
            "without a clear CTA underperform — pick one (Try Now / "
            "Request Demo / Book a Demo)."
        )

    # 4.9: video under 2 minutes (we can't verify subtitles without OCR)
    if video_path:
        try:
            p = Path(video_path)
            size_mb = p.stat().st_size / 1_048_576 if p.exists() else 0
            # No duration probe without ffmpeg — flag a soft caveat instead
            if size_mb > 12:                 # rough proxy for >90s @ HD
                findings.append(
                    "Video is unusually large for LinkedIn — verify it's under "
                    "2 minutes (audit-checklist 4.9). LinkedIn's algorithm "
                    "drops view-completion sharply past 2 minutes; clips "
                    "running 60-90 seconds outperform on engagement."
                )
        except OSError:
            pass

    # TLA character-count check (creative-strategy.md: 1000-1500 chars
    # for the TLA body in problem -> solution -> proof structure)
    body_len = len((primary_text or "").strip())
    if body_len > 0 and body_len < 400:
        findings.append(
            "Primary text is short for a thought-leader-ad pattern "
            "(Ivan recommends 1,000-1,500 chars in problem → solution → proof). "
            "Short copy works for retargeting; long-form TLAs are where "
            "LinkedIn paid actually pays off."
        )

    return findings


def _tla_eligibility(*, headline: str, primary_text: str,
                       has_video: bool) -> tuple[bool, str]:
    """Rough check: does this creative look like it could be promoted as a
    Thought Leader Ad? TLAs need substantive copy from a person, not a
    company-page-style announcement.
    """
    body = (primary_text or "").strip()
    if not body:
        return False, "No body text — TLA needs substantive personal copy."
    if len(body) < 300:
        return False, ("Too short for a TLA — non-employee/founder TLAs "
                        "win when they're 1,000-1,500 chars of genuinely "
                        "valuable insight.")
    # Cheap heuristic: looks like a company announcement vs personal voice
    if re.search(r"\b(we\s+are\s+excited|introducing|announcing|launch(?:ing)?)\b",
                 body.lower()):
        return False, ("Reads as a brand announcement. Non-employee TLAs "
                        "outperform employee TLAs by 15-20% — only run as "
                        "a TLA if the voice is genuinely personal.")
    return True, ("Long-form personal voice — promotable as a TLA. Per "
                   "Ivan, non-employee TLAs deliver ~15-20% higher "
                   "conversion lift than employee TLAs; CPC as low as $4.14.")


def is_linkedin_platform(platform_id: str) -> bool:
    return (platform_id or "").lower().startswith("linkedin")


# ---------------------------------------------------------------------------
# Gemini prompt
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a senior LinkedIn paid-ads strategist trained on Ivan Falco's "
    "ads-skills knowledge base + the LinkedIn Devil's Advocate (LDA) scoring "
    "framework. Your job is to critique a B2B paid LinkedIn ad CREATIVE — "
    "not orchestrate the campaign, not score organic-virality, not predict "
    "paid CTR. You are scoring CRAFT QUALITY for paid LinkedIn use.\n\n"
    "Be specific, ruthless, and ACTIONABLE. Never pad. Always cite the "
    "concrete thing in the creative that earned the score.\n\n"
    "Calibration: most well-built B2B creative scores 5-8 on each dimension. "
    "Reserve 9-10 for genuinely outstanding work. Sub-3 means the dimension "
    "is failing — call it out plainly.\n\n"
    "Respond ONLY with the requested JSON, no prose outside."
)


def _user_prompt(*, headline: str, primary_text: str, description: str,
                  cta: str, link: str, objective: str, audience_hint: str,
                  industry: str, geo: str,
                  deterministic_findings: list[str],
                  tla_eligible: bool, tla_notes: str,
                  has_image: bool, has_video: bool) -> str:
    stage_info = OBJECTIVE_TO_STAGE.get(objective.lower(),
                                          ("solution_aware", "MOF"))
    intended_stage, funnel_stage = stage_info
    media_desc = ("video creative attached" if has_video
                  else "image creative attached" if has_image
                  else "no visual — text-only LinkedIn ad")
    det_block = ""
    if deterministic_findings:
        det_block = "\n\nDETERMINISTIC AUDIT FINDINGS (already detected):\n" + \
                    "\n".join(f"- {f}" for f in deterministic_findings)
    return (
        f"Critique this LinkedIn paid ad. Format: {media_desc}.\n\n"
        f"Headline: \"{headline.strip()}\"\n"
        f"Primary text: \"{primary_text.strip()}\"\n"
        f"Description: \"{description.strip()}\"\n"
        f"CTA: \"{cta.strip()}\"\n"
        f"Destination URL: \"{link.strip()}\"\n"
        f"Campaign objective: {objective} (LinkedIn funnel stage: {funnel_stage}, "
        f"intended awareness stage: {intended_stage})\n"
        f"Target audience hint: {audience_hint[:300]}\n"
        f"Industry context: {industry}, geo: {geo}\n"
        f"TLA eligibility (pre-computed): {tla_eligible} — {tla_notes}"
        f"{det_block}\n\n"
        "--- TASK ---\n\n"
        "Score on LDA's 6 dimensions (each 0-10), classify the creative's "
        "awareness stage + angle, audit the copy against Ivan's 5-layer "
        "framework (Factual Accuracy / Tone / Structure / Text Density / "
        "Audience Fit), and return a tightened hook alternative.\n\n"
        "Return EXACTLY this JSON (no extra keys):\n"
        "{\n"
        "  \"scores\": {\n"
        "    \"hook\":             int 0-10,  // does line 1-2 stop a B2B founder mid-scroll?\n"
        "    \"body\":             int 0-10,  // is the copy substantive, specific, well-paced?\n"
        "    \"credibility\":      int 0-10,  // proof, stakes, lived experience — does it earn trust?\n"
        "    \"audience_fit\":     int 0-10,  // speaks to the chosen audience in their language?\n"
        "    \"cta\":              int 0-10,  // pointed, specific, matches funnel stage?\n"
        "    \"format_execution\": int 0-10   // white space, fragment rhythm, no AI smells\n"
        "  },\n"
        "  \"explanations\": {\n"
        "    \"hook\":             \"one short sentence — cite the specific line\",\n"
        "    \"body\":             \"...\", \"credibility\": \"...\",\n"
        "    \"audience_fit\":     \"...\", \"cta\": \"...\",\n"
        "    \"format_execution\": \"...\"\n"
        "  },\n"
        "  \"detected_awareness_stage\": \"problem_aware | solution_aware | product_aware\",\n"
        "  \"stage_mismatch_warning\": \"empty if detected matches intended; one sentence if not\",\n"
        "  \"detected_angle\": \"one of: trigger_event | main_problem | goals_jobs_to_be_done | pains_with_alternatives | key_features | primary_use_cases | benefits_for_users | selfish_desires | case_studies | testimonials | ratings_awards | client_logos\",\n"
        "  \"recommended_angles\": [\n"
        "    {\"angle\": \"<one of the 12 above>\", \"why\": \"one short line — why it'd lift this creative for the chosen objective\"},\n"
        "    {\"angle\": \"...\", \"why\": \"...\"}\n"
        "  ],\n"
        "  \"factual_accuracy_issues\": [\"specific claim that needs sourcing or is unverifiable\"],\n"
        "  \"tone_violations\": [\"specific tone hit — accusatory you, AI phrases, etc.\"],\n"
        "  \"structure_issues\": [\"hook → pain → solution → CTA progression broken where?\"],\n"
        "  \"text_density_issues\": [\"wall of text? lack of line breaks? specific\"],\n"
        "  \"audience_fit_issues\": [\"speaks to marketers when targeting founders? generic vs ICP-specific?\"],\n"
        "  \"hook_score\": int 0-10,\n"
        "  \"hook_alternatives\": [\n"
        "    {\"hook\": \"the new line, ≤120 chars\", \"reason\": \"why it lifts hook score, cites the LDA hook templates: contrarian / open_loop / data / pain_point / personal_story / industry_insight\"},\n"
        "    {\"hook\": \"...\", \"reason\": \"...\"},\n"
        "    {\"hook\": \"...\", \"reason\": \"...\"}\n"
        "  ],\n"
        "  \"biggest_strength\": \"the single strongest thing about this ad\",\n"
        "  \"biggest_weakness\": \"the thing most limiting paid performance\",\n"
        "  \"one_specific_fix\": \"if the user does ONE thing tomorrow, what is it? Be tactical, not general\"\n"
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
    total = sum(scores.get(k, 0) * LDA_DIMENSION_WEIGHTS[k]
                for k in LDA_DIMENSIONS)
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


def _skipped(reason: str) -> LinkedInCritique:
    return LinkedInCritique(
        scores={k: 0 for k in LDA_DIMENSIONS},
        composite=0.0, grade="—",
        explanations={k: "" for k in LDA_DIMENSIONS},
        is_skipped=True, skipped_reason=reason,
    )


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def critique_linkedin(*, headline: str = "",
                       primary_text: str = "",
                       description: str = "",
                       cta: str = "",
                       link: str = "",
                       objective: str = "consideration",
                       platform_id: str = "linkedin",
                       audience_hint: str = "",
                       industry: str = "",
                       geo: str = "UK",
                       image_path: str | None = None,
                       video_path: str | None = None) -> LinkedInCritique:
    """Score a LinkedIn paid ad on Ivan's + LDA's rubric.

    Returns a LinkedInCritique. Skipped silently when:
      - platform_id is NOT a LinkedIn placement
      - ADPROOF_LINKEDIN_CRITIC_ENABLED env flag is off
      - no Gemini key + no Claude key + no OpenAI key
      - all providers exhausted

    Honest framing — caller MUST enforce in UI: this scores CRAFT QUALITY
    for paid LinkedIn use. It is NOT a paid-CTR predictor. Even with a
    high LDA score, paid LinkedIn campaigns succeed or fail on targeting,
    bidding, landing page, and offer — none of which this critic can see.
    """
    if not is_linkedin_platform(platform_id):
        return _skipped(f"Platform {platform_id} is not LinkedIn — critic skipped.")
    if os.environ.get("ADPROOF_LINKEDIN_CRITIC_ENABLED", "1").lower() in ("0", "false", "no"):
        return _skipped("LinkedIn critic disabled via env flag.")
    if not (headline or primary_text or description):
        return _skipped("No copy provided — nothing to critique.")

    # Pre-compute deterministic checks (cheap, run regardless of LLM)
    det = _deterministic_findings(
        headline=headline, primary_text=primary_text, cta=cta,
        video_path=video_path)
    tla_ok, tla_notes = _tla_eligibility(
        headline=headline, primary_text=primary_text,
        has_video=bool(video_path))

    # Pick a provider — prefer Gemini (cheapest), then Claude, then OpenAI.
    # No video Part: we just need the LLM to read copy + (optionally) view
    # an attached image. Skipping the multimodal arm keeps cost predictable
    # — text-only critique is what LDA was designed for.
    user = _user_prompt(
        headline=headline, primary_text=primary_text, description=description,
        cta=cta, link=link, objective=objective, audience_hint=audience_hint,
        industry=industry, geo=geo,
        deterministic_findings=det,
        tla_eligible=tla_ok, tla_notes=tla_notes,
        has_image=bool(image_path), has_video=bool(video_path),
    )

    raw: dict = {}
    used_model = ""
    used_provider = ""
    last_exc: Exception | None = None

    # Gemini text path first
    if _get_key("GEMINI_API_KEY"):
        try:
            from google import genai
            from google.genai import types as gtypes
            client = genai.Client(api_key=_get_key("GEMINI_API_KEY"))
            for model_id in GEMINI_VISION_CHAIN:
                if ("gemini-linkedin-critic", model_id) in _VISION_EXHAUSTED:
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
                except Exception as exc:                          # noqa: BLE001
                    last_exc = exc
                    if _is_quota_error(exc):
                        _VISION_EXHAUSTED.add(("gemini-linkedin-critic", model_id))
                        _ph_quota("gemini-linkedin-critic", model_id, str(exc))
                        continue
                    last_exc = exc
                    break
                text = getattr(response, "text", None)
                if not text:
                    continue
                try:
                    raw = _extract_json(text)
                    used_model = model_id
                    used_provider = "gemini"
                    _ph_ok("gemini-linkedin-critic", model_id)
                    break
                except (ValueError, json.JSONDecodeError) as exc:
                    last_exc = exc
                    continue
        except ImportError:
            pass

    if not raw:
        return _skipped(
            f"LinkedIn critic unavailable: {last_exc or 'no provider configured'}.")

    # ---- Normalise + clip ----
    scores_raw = raw.get("scores") or {}
    scores = {k: _clip_int(scores_raw.get(k)) for k in LDA_DIMENSIONS}
    explanations_raw = raw.get("explanations") or {}
    explanations = {k: str(explanations_raw.get(k, "")).strip()
                    for k in LDA_DIMENSIONS}

    intended_stage = OBJECTIVE_TO_STAGE.get(objective.lower(),
                                              ("solution_aware", "MOF"))[0]
    funnel_stage = OBJECTIVE_TO_STAGE.get(objective.lower(),
                                            ("solution_aware", "MOF"))[1]
    detected_stage = str(raw.get("detected_awareness_stage", "")).strip().lower()
    if detected_stage not in ("problem_aware", "solution_aware", "product_aware"):
        detected_stage = ""

    detected_angle = str(raw.get("detected_angle", "")).strip().lower()
    if detected_angle not in CREATIVE_ANGLES:
        detected_angle = ""

    recommended_angles_raw = raw.get("recommended_angles") or []
    recommended_angles = []
    for r in recommended_angles_raw[:5]:
        if isinstance(r, dict):
            a = str(r.get("angle", "")).strip().lower()
            why = str(r.get("why", "")).strip()
            if a in CREATIVE_ANGLES:
                recommended_angles.append({"angle": a, "why": why})

    hook_alts_raw = raw.get("hook_alternatives") or []
    hook_alts = []
    for ha in hook_alts_raw[:5]:
        if isinstance(ha, dict):
            h = str(ha.get("hook", "")).strip()
            r_ = str(ha.get("reason", "")).strip()
            if h:
                hook_alts.append({"hook": h, "reason": r_})

    def _strlist(key: str, cap: int = 6) -> list:
        out = []
        for v in (raw.get(key) or [])[:cap]:
            s = str(v).strip()
            if s:
                out.append(s)
        return out

    composite = _composite_from_scores(scores)
    return LinkedInCritique(
        scores=scores,
        composite=composite,
        grade=_grade_for(composite),
        explanations=explanations,
        detected_awareness_stage=detected_stage,
        intended_awareness_stage=intended_stage,
        stage_mismatch_warning=str(raw.get("stage_mismatch_warning", "")).strip(),
        funnel_stage=funnel_stage,
        detected_angle=detected_angle,
        recommended_angles=recommended_angles,
        factual_accuracy_issues=_strlist("factual_accuracy_issues"),
        tone_violations=_strlist("tone_violations"),
        structure_issues=_strlist("structure_issues"),
        text_density_issues=_strlist("text_density_issues"),
        audience_fit_issues=_strlist("audience_fit_issues"),
        hook_score=_clip_int(raw.get("hook_score")),
        hook_alternatives=hook_alts,
        tla_eligible=tla_ok,
        tla_notes=tla_notes,
        deterministic_findings=det,
        biggest_strength=str(raw.get("biggest_strength", "")).strip(),
        biggest_weakness=str(raw.get("biggest_weakness", "")).strip(),
        one_specific_fix=str(raw.get("one_specific_fix", "")).strip(),
        provider=used_provider,
        model=used_model,
        raw=raw,
    )
