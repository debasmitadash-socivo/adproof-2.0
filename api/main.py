"""FastAPI backend for AdProof.

Thin REST layer over the existing analytics engine in ../src/. Endpoints:

    POST /api/parse-company    -> CompanyProfile
    POST /api/match-audience   -> AudienceMatch
    GET  /api/platforms        -> platform / format catalogue
    POST /api/simulate         -> full forecast (charts as Plotly JSON)
    GET  /api/me               -> stub demo user
    GET  /api/healthz          -> health probe

Run with:
    cd api && uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Make the existing src/ package importable.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from audience_match import match_audience  # noqa: E402
from brief import CampaignBrief, CreativeAssets  # noqa: E402
from company_profile import parse_company  # noqa: E402
from copy_critique import critique_copy  # noqa: E402
from llm import have_any_key  # noqa: E402
from pipeline import run_wizard_simulation  # noqa: E402
from platforms import (  # noqa: E402
    BENCHMARK_AS_OF,
    FORMATS,
    PLATFORMS,
    get_format,
    platform_formats,
    platform_name,
)

# Resolve config defaults once at import time so endpoints don't depend on
# stale hard-coded strings.
sys.path.insert(0, str(_PROJECT_ROOT))
from config import GEMINI_GROUNDED_CHAIN, GEMINI_GROUNDED_MODEL  # noqa: E402


def _gemini_grounded_call(prompt: str, max_tokens: int, *, tools=None):
    """Call Gemini with google_search grounding, rotating through the
    grounded model chain so 429 on one model doesn't kill the request."""
    from google import genai
    from google.genai import types as gtypes
    import os as _os
    key = _os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    client = genai.Client(api_key=key)
    last_exc: Exception | None = None
    for model_id in GEMINI_GROUNDED_CHAIN:
        try:
            return client.models.generate_content(
                model=model_id,
                contents=prompt,
                config=gtypes.GenerateContentConfig(
                    tools=tools or [
                        gtypes.Tool(google_search=gtypes.GoogleSearch())],
                    max_output_tokens=max_tokens,
                ),
            ), model_id
        except Exception as exc:                       # noqa: BLE001
            last_exc = exc
            msg = str(exc).lower()
            if any(s in msg for s in ("429", "resource_exhausted",
                                       "quota", "503", "unavailable")):
                continue
            raise
    raise last_exc or RuntimeError("all grounded Gemini models failed")


app = FastAPI(title="AdProof API", version="0.1.0")

# CORS — allow local dev + production frontends. Extra origins can be added
# via the ALLOW_EXTRA_ORIGINS env var as a comma-separated list (e.g.
# "https://staging.adproof.com,https://my-pr-branch.vercel.app").
import os as _cors_os
_extra_origins = [
    o.strip() for o in
    (_cors_os.environ.get("ALLOW_EXTRA_ORIGINS") or "").split(",")
    if o.strip()
]
_default_origins = [
    # Local development
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    # Vercel — main production + every preview deploy (PR branches, etc.).
    # `allow_origin_regex` below handles the `*.vercel.app` wildcard.
    "https://adproof.vercel.app",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra_origins,
    # Matches every Vercel preview URL: adproof-git-feature.vercel.app,
    # adproof-pr-42.vercel.app, etc.
    allow_origin_regex=r"https://adproof-[a-z0-9-]+\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API key persistence (local dev only — auto-loads on every API restart)
# ---------------------------------------------------------------------------

_SECRETS_FILE = _PROJECT_ROOT / "data" / ".secrets.json"


_PERSISTED_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "OPENROUTER_API_KEY",
    "XAI_API_KEY",
    "TOGETHER_API_KEY",
)


def _load_persisted_keys() -> None:
    """Re-populate os.environ from the persisted secrets file on startup so
    keys survive `uvicorn` restarts. v2 will move to per-user encrypted
    storage with real auth."""
    import os as _os
    if not _SECRETS_FILE.exists():
        return
    try:
        data = json.loads(_SECRETS_FILE.read_text())
        for env_name in _PERSISTED_KEYS:
            val = data.get(env_name)
            if val and not _os.environ.get(env_name):
                _os.environ[env_name] = val
    except (json.JSONDecodeError, OSError):
        pass


def _save_persisted_keys() -> None:
    import os as _os
    try:
        _SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            k: _os.environ[k] for k in _PERSISTED_KEYS
            if _os.environ.get(k)
        }
        _SECRETS_FILE.write_text(json.dumps(snapshot, indent=2))
        try:
            _SECRETS_FILE.chmod(0o600)
        except OSError:
            pass
    except OSError:
        pass


_load_persisted_keys()


# ===========================================================================
# Schemas
# ===========================================================================

class ParseCompanyRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)


class MatchAudienceRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)


class SimulateRequest(BaseModel):
    # Company
    company_description: str = ""
    # Audience
    audience_description: str = ""
    audience_segment: Optional[str] = None   # if user picked a saved segment id
    # Brief
    objective: str = "consideration"
    platform_id: str
    format_id: str
    budget: float = 10_000.0
    days: int = 14
    daily_reach: float = 0.35
    n_runs: int = 20
    target_conversion_rate: float = 0.025
    # --- Real economics (the honest inputs that replace synthetic AOV) -----
    avg_order_value: Optional[float] = None   # customer value in `currency`
    product_price: Optional[float] = None
    currency: str = "GBP"                     # UK-based default
    geo: str = "UK"                           # target market for this campaign
    # Creative
    image_path: Optional[str] = None
    video_path: Optional[str] = None
    headline: str = ""
    primary_text: str = ""
    description: str = ""
    cta: str = ""
    link: str = ""
    visual_provider: str = "auto"


# ===========================================================================
# Health + identity
# ===========================================================================

@app.get("/api/healthz")
def healthz() -> dict:
    import os as _os
    return {
        "ok": True,
        "llm": have_any_key(),
        "anthropic":  bool(_os.environ.get("ANTHROPIC_API_KEY")),
        "openai":     bool(_os.environ.get("OPENAI_API_KEY")),
        "gemini":     bool(_os.environ.get("GEMINI_API_KEY")),
        "groq":       bool(_os.environ.get("GROQ_API_KEY")),
        "mistral":    bool(_os.environ.get("MISTRAL_API_KEY")),
        "openrouter": bool(_os.environ.get("OPENROUTER_API_KEY")),
        "xai":        bool(_os.environ.get("XAI_API_KEY")),
        "together":   bool(_os.environ.get("TOGETHER_API_KEY")),
        "version": app.version,
    }


# ---------------------------------------------------------------------------
# API key management (local-dev v1 — stored in process env, cleared on restart)
# ---------------------------------------------------------------------------

class ApiKeysRequest(BaseModel):
    anthropic_key:  Optional[str] = None
    openai_key:     Optional[str] = None
    gemini_key:     Optional[str] = None
    groq_key:       Optional[str] = None
    mistral_key:    Optional[str] = None
    openrouter_key: Optional[str] = None
    xai_key:        Optional[str] = None
    together_key:   Optional[str] = None


@app.post("/api/settings/api-keys")
def set_api_keys(req: ApiKeysRequest) -> dict:
    """Set LLM API keys at runtime, persist to data/.secrets.json so they
    survive uvicorn restarts. v2 will move to per-user encrypted DB storage.
    """
    import os as _os
    updated = []
    for field, env_name, label in (
        (req.anthropic_key,  "ANTHROPIC_API_KEY",  "anthropic"),
        (req.openai_key,     "OPENAI_API_KEY",     "openai"),
        (req.gemini_key,     "GEMINI_API_KEY",     "gemini"),
        (req.groq_key,       "GROQ_API_KEY",       "groq"),
        (req.mistral_key,    "MISTRAL_API_KEY",    "mistral"),
        (req.openrouter_key, "OPENROUTER_API_KEY", "openrouter"),
        (req.xai_key,        "XAI_API_KEY",        "xai"),
        (req.together_key,   "TOGETHER_API_KEY",   "together"),
    ):
        if field is None:
            continue
        if field.strip():
            _os.environ[env_name] = field.strip()
            updated.append(label)
        else:
            _os.environ.pop(env_name, None)
            updated.append(f"{label}_cleared")
    _save_persisted_keys()
    return {
        "updated": updated,
        "llm": have_any_key(),
        "anthropic":  bool(_os.environ.get("ANTHROPIC_API_KEY")),
        "openai":     bool(_os.environ.get("OPENAI_API_KEY")),
        "gemini":     bool(_os.environ.get("GEMINI_API_KEY")),
        "groq":       bool(_os.environ.get("GROQ_API_KEY")),
        "mistral":    bool(_os.environ.get("MISTRAL_API_KEY")),
        "openrouter": bool(_os.environ.get("OPENROUTER_API_KEY")),
        "xai":        bool(_os.environ.get("XAI_API_KEY")),
        "together":   bool(_os.environ.get("TOGETHER_API_KEY")),
    }


@app.post("/api/settings/test-llm")
def test_llm() -> dict:
    """Quick connection test against the chosen provider.

    Returns the active provider, the model the request hit, and the actual
    error reason if it failed (quota, bad key, network) so the user can
    diagnose instead of seeing a generic "no LLM responded".
    """
    import os as _os
    from llm import LAST_ERROR, _select_provider, text_complete  # noqa: E402
    from config import (CLAUDE_MODEL, GEMINI_MODEL,  # noqa: E402
                         GROQ_TEXT_MODEL, OPENAI_MODEL)

    provider = _select_provider("auto")
    model = {"claude": CLAUDE_MODEL, "openai": OPENAI_MODEL,
             "gemini": GEMINI_MODEL, "groq": GROQ_TEXT_MODEL}.get(provider)

    if provider == "none":
        return {
            "ok": False,
            "provider": "none",
            "model": None,
            "reason": ("No API key configured. Add an Anthropic / OpenAI / "
                       "Gemini / Groq key above to enable smart parsing + "
                       "visual analysis."),
        }

    # text_complete walks the full fallback chain so even if the primary
    # provider is rate-limited this will succeed via Groq or whichever else
    # has a key. Bypass the cache so we always make a fresh call here.
    out = text_complete(
        "Respond with the single word: ok",
        system="You are a connectivity test. Reply with exactly: ok",
        max_tokens=8,
        use_cache=False,
    )
    if out and "ok" in out.lower():
        return {
            "ok": True,
            "provider": provider,
            "model": model,
            "echo": out.strip(),
        }
    # Pull the underlying failure reason that llm.text_complete captured.
    reason = (LAST_ERROR or {}).get(
        "reason",
        "Provider call returned empty/None — likely a quota or model issue.",
    )
    return {
        "ok": False,
        "provider": provider,
        "model": model,
        "reason": reason,
        "anthropic_key_set": bool(_os.environ.get("ANTHROPIC_API_KEY")),
        "openai_key_set": bool(_os.environ.get("OPENAI_API_KEY")),
        "gemini_key_set": bool(_os.environ.get("GEMINI_API_KEY")),
        "groq_key_set": bool(_os.environ.get("GROQ_API_KEY")),
    }


@app.get("/api/me")
def me() -> dict:
    """Returns a marker the frontend uses to know auth is stubbed.

    No fake identity is invented -- the real user/workspace info lives in the
    browser's local storage and is set during onboarding. We surface auth
    being stubbed honestly so the UI can show the right onboarding prompt.
    """
    return {"auth_kind": "stub-v1", "needs_local_profile": True}


# ===========================================================================
# Creative upload
# ===========================================================================

UPLOAD_DIR = _PROJECT_ROOT / "data" / "raw" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_ALLOWED_MIME = {
    "image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif",
    "video/mp4", "video/quicktime",
}


@app.post("/api/upload")
async def upload_creative(file: UploadFile = File(...)) -> dict:
    """Save an uploaded creative under data/raw/uploads/ and return its path.

    The path is what the simulation pipeline reads for visual analysis;
    ``url`` is served back so the wizard can render a preview thumbnail.
    """
    if file.content_type and file.content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}",
        )
    suffix = Path(file.filename or "upload.bin").suffix.lower() or ".bin"
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    try:
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
    finally:
        file.file.close()
    kind = "video" if (file.content_type or "").startswith("video/") else "image"
    return {
        "path": str(dest),
        "url": f"/uploads/{dest.name}",
        "filename": file.filename,
        "size": dest.stat().st_size,
        "content_type": file.content_type,
        "kind": kind,
    }


# Serve uploaded files back so the wizard can preview them.
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


# ===========================================================================
# Platform / format catalogue
# ===========================================================================

@app.get("/api/platforms")
def list_platform_catalogue() -> dict:
    """Full platform x format catalogue with benchmarks."""
    platforms_out = []
    for pid, meta in PLATFORMS.items():
        formats_out = []
        for f in platform_formats(pid):
            formats_out.append({
                "id": f.id,
                "name": f.name,
                "media_type": f.media_type,
                "asset_types": list(f.asset_types),
                "benchmarks": f.benchmarks,
                "copy_limits": f.copy_limits,
                "aspect_ratios": list(f.aspect_ratios),
                "best_for": f.best_for,
                "tone": f.tone,
                "primary_objectives": list(f.primary_objectives),
            })
        platforms_out.append({
            "id": pid,
            "name": meta["name"],
            "audience_default": meta["audience_default"],
            "strength": meta["strength"],
            "formats": formats_out,
        })
    return {"platforms": platforms_out, "benchmarks_as_of": BENCHMARK_AS_OF}


# ---------------------------------------------------------------------------
# Live benchmark refresh -- Gemini web grounding
# ---------------------------------------------------------------------------

class BenchmarkRefreshRequest(BaseModel):
    format_id: str
    industry: Optional[str] = None      # nudge the grounded query toward a
                                         # vertical (DTC beauty, B2B SaaS…)
    geo: Optional[str] = None            # ISO country or "US" / "UK" / "global"


@app.post("/api/benchmarks/refresh")
def refresh_benchmarks(req: BenchmarkRefreshRequest) -> dict:
    """Pull the current published industry-average CTR/CPM for one format
    by grounding Gemini against live Google Search results.

    Requires a Gemini API key. Returns the fetched numbers, the source URLs
    Gemini cited, and a delta vs the stored 2026 baseline so the user can
    decide whether to apply the override.
    """
    import os as _os
    key = _os.environ.get("GEMINI_API_KEY")
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Connect a Gemini API key in /settings to fetch live benchmarks.",
        )
    try:
        fmt = get_format(req.format_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="google-genai not installed -- run `pip install google-genai`.",
        )

    industry_hint = (f" in the {req.industry} industry"
                     if req.industry else "")
    geo_hint = f" (geo: {req.geo})" if req.geo else ""
    prompt = (
        f"What is the current industry-average click-through rate (CTR) and "
        f"CPM for {fmt.platform_name} {fmt.name} advertising in 2026"
        f"{industry_hint}{geo_hint}? "
        "Cite the source (e.g. WordStream 2026 benchmarks, Meta business "
        "blog, LinkedIn marketing solutions report, TikTok For Business, "
        "Statista, AdRoll, etc.). "
        "Respond in this exact JSON shape (no prose around it):\n"
        '{\n'
        '  "ctr": <decimal e.g. 0.0085 means 0.85%>,\n'
        '  "cpm": <USD>,\n'
        '  "cpc": <USD or null>,\n'
        '  "ctr_range_low": <decimal>,\n'
        '  "ctr_range_high": <decimal>,\n'
        '  "source": "<source name>",\n'
        '  "source_url": "<URL>",\n'
        '  "year": "<YYYY or YYYY-Qn>",\n'
        '  "notes": "<one short sentence on confidence / caveats>"\n'
        '}\n'
        "If you cannot find current data, set fields to null and explain in notes."
    )

    try:
        response, _model_used = _gemini_grounded_call(prompt, max_tokens=2048)
    except Exception as exc:                          # noqa: BLE001
        # Common cases: 429 quota exhausted across all chain models, 400 bad
        # key, network error. Surface the actual reason rather than a 500.
        msg = str(exc)
        status = 503 if "429" in msg or "RESOURCE_EXHAUSTED" in msg else 502
        raise HTTPException(
            status_code=status,
            detail=(f"Gemini live-benchmark refresh failed: {msg[:280]}. "
                    "All grounded model fallbacks were attempted. "
                    "Try again later or add a Groq key in /settings."),
        )

    raw_text = response.text or ""
    # Extract JSON robustly -- Gemini sometimes wraps in ```json```.
    import re as _re
    cleaned = _re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
    cleaned = _re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    parsed: dict = {}
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            parsed = {}

    # Source attributions (Gemini grounding metadata).
    grounding_urls: list = []
    try:
        gm = response.candidates[0].grounding_metadata
        if gm and gm.grounding_chunks:
            for ch in gm.grounding_chunks:
                if ch.web:
                    grounding_urls.append({
                        "title": ch.web.title or "",
                        "uri": ch.web.uri or "",
                    })
    except Exception:
        pass

    stored = fmt.benchmarks
    fetched_ctr = parsed.get("ctr")
    fetched_cpm = parsed.get("cpm")
    return {
        "format_id": fmt.id,
        "platform": fmt.platform_name,
        "format_name": fmt.name,
        "stored_benchmarks": {
            "ctr": stored.get("ctr"),
            "cpm": stored.get("cpm"),
            "cpc": stored.get("cpc"),
            "as_of": stored.get("as_of", BENCHMARK_AS_OF),
        },
        "fetched": parsed,
        "delta_pct": {
            "ctr": (round((fetched_ctr - stored["ctr"]) / stored["ctr"] * 100, 1)
                    if isinstance(fetched_ctr, (int, float)) and stored.get("ctr") else None),
            "cpm": (round((fetched_cpm - stored["cpm"]) / max(stored["cpm"], 1e-9) * 100, 1)
                    if isinstance(fetched_cpm, (int, float)) and stored.get("cpm") else None),
        },
        "grounding_sources": grounding_urls[:5],
        "raw_text": raw_text[:600],   # first 600 chars for debugging
    }


# ---------------------------------------------------------------------------
# Live policy / regulation compliance check (Gemini web grounding)
# ---------------------------------------------------------------------------

class PolicyCheckRequest(BaseModel):
    platform_id: str
    format_id: str
    headline: str = ""
    primary_text: str = ""
    description: str = ""
    cta: str = ""
    link: str = ""
    industry: Optional[str] = None


_PLATFORM_POLICY_HINT = {
    "meta_facebook": "Meta Advertising Standards (transparency.meta.com/policies/ad-standards)",
    "meta_instagram": "Meta Advertising Standards (transparency.meta.com/policies/ad-standards)",
    "google_search": "Google Ads Policies (support.google.com/adspolicy)",
    "google_display": "Google Ads Policies (support.google.com/adspolicy)",
    "youtube": "Google Ads + YouTube ad policies",
    "linkedin": "LinkedIn Advertising Policies (linkedin.com/legal/ads-policy)",
    "tiktok": "TikTok For Business Advertising Policies (ads.tiktok.com/help/article/advertising-policies)",
}


@app.post("/api/policy-check")
def policy_check(req: PolicyCheckRequest) -> dict:
    """Use Gemini + Google Search grounding to fetch the current advertising
    policy for the chosen platform/format, then evaluate the user's copy
    against those rules. Returns specific rule violations with the source URL
    so the user can verify.

    Catches things copy_critique cannot:
    * Restricted content (health claims, financial promises, alcohol)
    * Required disclaimers (gambling, crypto, supplements)
    * Targeting restrictions (housing, employment, credit — HEC)
    * Trademark / IP issues
    """
    import os as _os
    key = _os.environ.get("GEMINI_API_KEY")
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Connect a Gemini API key in /settings to run policy compliance checks.",
        )
    try:
        fmt = get_format(req.format_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="google-genai not installed -- run `pip install google-genai`.",
        )

    policy_source = _PLATFORM_POLICY_HINT.get(req.platform_id, "")
    industry_hint = f" The advertiser is in: {req.industry}." if req.industry else ""

    creative_text = "\n".join(
        f"- {label}: {value}" for label, value in [
            ("Headline", req.headline),
            ("Primary text / caption", req.primary_text),
            ("Description", req.description),
            ("CTA", req.cta),
            ("Destination URL", req.link),
        ] if value
    ) or "(no copy provided)"

    prompt = f"""You are a paid-media compliance reviewer.

PLATFORM: {fmt.platform_name} / {fmt.name}
POLICY SOURCE: {policy_source}
{industry_hint}

TASK
1. Use Google Search to read the CURRENT ({BENCHMARK_AS_OF}) advertising policy
   documentation for this platform. Be specific to *this* year's rules --
   policies were updated in 2025-2026 for AI-generated content, health
   claims, financial services, and political content.
2. Evaluate this ad copy against those rules:

{creative_text}

3. Return ONLY a JSON object (no prose) with this shape:
{{
  "summary": "<one-sentence overall verdict>",
  "overall_risk": "<low | medium | high>",
  "policy_source_url": "<the canonical URL you used>",
  "policies_consulted_year": "<YYYY or YYYY-MM>",
  "issues": [
    {{
      "severity": "<error | warning | info>",
      "rule": "<short policy rule name>",
      "rule_url": "<deep URL to the specific rule>",
      "violating_text": "<the exact words from the copy that trigger this>",
      "explanation": "<1-2 sentences why it violates>",
      "fix": "<concrete rewrite suggestion>"
    }}
  ]
}}

Be strict but fair. If the copy is clean, return issues: []."""

    try:
        response, _model_used = _gemini_grounded_call(prompt, max_tokens=3072)
    except Exception as exc:                          # noqa: BLE001
        msg = str(exc)
        status = 503 if "429" in msg or "RESOURCE_EXHAUSTED" in msg else 502
        raise HTTPException(
            status_code=status,
            detail=(f"Gemini policy-check failed: {msg[:280]}. "
                    "All grounded model fallbacks were attempted. "
                    "Try again later or add a Groq key in /settings."),
        )

    raw_text = response.text or ""
    import re as _re
    cleaned = _re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
    cleaned = _re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    parsed: dict = {}
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            parsed = {}

    grounding_urls: list = []
    try:
        gm = response.candidates[0].grounding_metadata
        if gm and gm.grounding_chunks:
            for ch in gm.grounding_chunks:
                if ch.web:
                    grounding_urls.append({
                        "title": ch.web.title or "",
                        "uri": ch.web.uri or "",
                    })
    except Exception:
        pass

    return {
        "platform": fmt.platform_name,
        "format": fmt.name,
        "summary": parsed.get("summary", ""),
        "overall_risk": parsed.get("overall_risk", "unknown"),
        "policy_source_url": parsed.get("policy_source_url", ""),
        "policies_consulted_year": parsed.get("policies_consulted_year", BENCHMARK_AS_OF),
        "issues": parsed.get("issues", []),
        "grounding_sources": grounding_urls[:5],
    }


# ===========================================================================
# Company parsing + audience matching
# ===========================================================================

@app.post("/api/parse-company")
def parse_company_endpoint(req: ParseCompanyRequest) -> dict:
    profile = parse_company(req.description, prefer_llm=have_any_key())
    return profile.to_dict()


@app.post("/api/match-audience")
def match_audience_endpoint(req: MatchAudienceRequest) -> dict:
    match = match_audience(req.description, prefer_llm=have_any_key())
    return match.to_dict()


# ---------------------------------------------------------------------------
# Website research → proposed economics (Gemini grounded). The AI's estimate
# is a PREFILL the user confirms/corrects — never treated as truth.
# ---------------------------------------------------------------------------

class ResearchCompanyRequest(BaseModel):
    url: Optional[str] = None
    description: str = ""
    geo: str = "UK"


def _is_safe_public_url(raw: str) -> tuple[bool, str]:
    """SSRF guard. Only allow http(s) URLs pointing at public hosts. Blocks
    localhost, private ranges, and the cloud metadata endpoint so a malicious
    user can't make our server fetch internal services."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    try:
        u = urlparse(raw if "://" in raw else f"https://{raw}")
    except Exception:
        return False, "Could not parse URL."
    if u.scheme not in ("http", "https"):
        return False, "Only http/https URLs are allowed."
    host = u.hostname or ""
    if not host:
        return False, "URL has no host."
    if host.lower() in ("localhost", "metadata.google.internal"):
        return False, "Refusing to fetch internal host."
    # Resolve and reject private / loopback / link-local / reserved IPs.
    try:
        for fam, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast
                    or ip.is_unspecified):
                return False, "URL resolves to a non-public address."
    except Exception:
        # DNS failure — let it through to the grounded call, which will just
        # find nothing rather than hitting an internal service.
        pass
    return True, ""


@app.post("/api/research-company")
def research_company(req: ResearchCompanyRequest) -> dict:
    """Use Gemini + web grounding to research a business from its URL and/or
    description, and PROPOSE economics (industry, price point, likely average
    order value, location). Everything returned is an *estimate for the user
    to confirm* — the UI must let them edit it. We never feed these numbers
    into a forecast without the user accepting them first.
    """
    import os as _os
    key = _os.environ.get("GEMINI_API_KEY")
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Connect a Gemini key in /settings to auto-research a business.",
        )

    url = (req.url or "").strip()
    if url:
        ok, why = _is_safe_public_url(url)
        if not ok:
            raise HTTPException(status_code=400, detail=f"Unsafe URL: {why}")

    site_hint = f"Their website: {url}\n" if url else ""
    desc_hint = f"They describe themselves as: \"{req.description.strip()}\"\n" if req.description.strip() else ""
    if not site_hint and not desc_hint:
        raise HTTPException(
            status_code=400,
            detail="Provide a website URL or a description to research.",
        )

    prompt = f"""You are a marketing analyst. Estimate the economics of this
business so we can pre-fill a form. The user will confirm/correct your numbers.

{site_hint}{desc_hint}Primary market: {req.geo}

Use web search to look up the specific business if a URL/name is given. If you
can't find the exact business, STILL estimate based on the business TYPE and
the {req.geo} market — do not return nulls just because you can't find the
exact company. Always give your best category-level estimate.

Return ONLY this JSON, nothing else. Keep "reasoning" to ONE short sentence so
the JSON stays small:
{{
  "company_name": "<name or empty string>",
  "industry": "<concise industry>",
  "business_model": "<b2c | b2b | dtc | saas | marketplace | services>",
  "what_they_sell": "<one short line>",
  "price_point": "<low | mid | premium | luxury>",
  "estimated_avg_order_value": <number in local currency>,
  "currency": "<GBP | USD | EUR | ...>",
  "location": "<primary market>",
  "confidence": "<low | medium | high>",
  "reasoning": "<ONE short sentence on how you estimated the order value>"
}}"""

    try:
        response, model_used = _gemini_grounded_call(prompt, max_tokens=1600)
    except Exception as exc:                          # noqa: BLE001
        msg = str(exc)
        status = 503 if "429" in msg or "RESOURCE_EXHAUSTED" in msg else 502
        raise HTTPException(
            status_code=status,
            detail=(f"Research failed: {msg[:240]}. The user can still enter "
                    "their economics manually."),
        )

    raw_text = response.text or ""
    import re as _re
    cleaned = _re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
    cleaned = _re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    parsed: dict = {}
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            parsed = {}

    grounding_urls: list = []
    try:
        gm = response.candidates[0].grounding_metadata
        if gm and gm.grounding_chunks:
            for ch in gm.grounding_chunks:
                if ch.web:
                    grounding_urls.append({"title": ch.web.title or "",
                                            "uri": ch.web.uri or ""})
    except Exception:
        pass

    return {
        "proposed": parsed,                # ESTIMATE — UI must let user edit
        "model": model_used,
        "sources": grounding_urls[:5],
        "disclaimer": "These are AI estimates from public web data. Confirm or "
                      "correct them — your real numbers drive the forecast, not ours.",
    }


# ===========================================================================
# Main simulation
# ===========================================================================

def _strip_unserialisable(obj: Any) -> Any:
    """Drop heavy / non-JSON fields so the response stays light."""
    if isinstance(obj, dict):
        return {k: _strip_unserialisable(v) for k, v in obj.items()
                if k not in ("daily_records_per_run",)}
    if isinstance(obj, list):
        return [_strip_unserialisable(x) for x in obj]
    return obj


@app.post("/api/simulate")
def simulate(req: SimulateRequest) -> dict:
    if req.format_id not in FORMATS:
        raise HTTPException(status_code=400,
                            detail=f"Unknown format_id '{req.format_id}'.")

    # Build profile + match (LLM when key present, heuristic otherwise).
    profile = parse_company(req.company_description or
                             "(no company description provided)",
                             prefer_llm=have_any_key())
    match = match_audience(req.audience_description or
                            "general audience",
                            prefer_llm=have_any_key())
    if req.audience_segment:
        # User picked an explicit saved segment — override the matcher.
        match.segment = req.audience_segment
        match.rationale = (f"User selected the '{req.audience_segment}' "
                           f"segment explicitly.")
        match.confidence = 1.0

    brief = CampaignBrief(
        objective=req.objective,
        platform_id=req.platform_id,
        format_id=req.format_id,
        budget=req.budget, days=req.days,
        daily_reach=req.daily_reach, n_runs=req.n_runs,
        target_conversion_rate=req.target_conversion_rate,
        avg_order_value=req.avg_order_value,
        product_price=req.product_price,
        currency=req.currency,
        geo=req.geo,
    )
    assets = CreativeAssets(
        image_path=req.image_path, video_path=req.video_path,
        headline=req.headline, primary_text=req.primary_text,
        description=req.description, cta=req.cta, link=req.link,
    )

    try:
        result = run_wizard_simulation(
            profile=profile, match=match, brief=brief, assets=assets,
            visual_provider=req.visual_provider,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Convert plotly figures to JSON-serialisable dicts (Plotly.react in the
    # frontend can render these directly).
    figures = {k: json.loads(fig.to_json())
               for k, fig in result["figures"].items()}

    # Marketer-friendly verdict: translates the logit-scale internals into
    # plain English + percentages + clear data-provenance breakdown.
    mc_dict = result["mc"].to_dict()
    fmt_bench_ctr = brief.format.benchmarks.get("ctr", 0.012)
    sample_ctr = (sum(mc_dict["sample_ctrs"]) /
                  max(len(mc_dict["sample_ctrs"]), 1))
    roas = mc_dict["predicted_roas"]["p50"]

    if roas >= 4.0:
        plain = "Likely to be a strong winner."
        verdict_word = "strong"
    elif roas >= 2.0:
        plain = "Likely profitable — should pay back well."
        verdict_word = "positive"
    elif roas >= 1.0:
        plain = "Likely to barely break even — risky."
        verdict_word = "break_even"
    else:
        plain = "Likely to lose money — don't ship as is."
        verdict_word = "underperforming"

    # Translate aggregate click factors (logit) to relative-contribution
    # percentages so the UI can show 'this drove +30% of clicks'.
    factors = mc_dict.get("aggregate_click_factors", {})
    factor_items = [(k, float(v)) for k, v in factors.items() if k != "base"]
    total_abs = sum(abs(v) for _, v in factor_items) or 1.0
    factor_plain = sorted(
        [{"name": k, "share": round(abs(v) / total_abs, 3),
          "direction": "+" if v >= 0 else "-",
          "label": _pretty_factor_label(k, v)}
         for k, v in factor_items],
        key=lambda x: -x["share"],
    )

    # ----------------------------------------------------------------------
    # HONEST CHANNEL ECONOMICS — the reframe.
    # Instead of presenting a synthetic "predicted ROAS" as fact, we show the
    # marketer the actual break-even math against THEIR economics:
    #   "At your £X order value and Y% conversion, you need a Z% CTR to break
    #    even. The benchmark is B%, we model your creative at M%."
    # Every number here is either the advertiser's own input, a grounded
    # benchmark, or the modelled CTR — no invented revenue.
    # ----------------------------------------------------------------------
    imps = max(mc_dict.get("total_impressions", 0), 1)
    conv_rate = max(float(req.target_conversion_rate or 0.0), 1e-9)
    aov_used = float(mc_dict.get("mean_aov", 0.0) or 0.0)
    aov_is_real = brief.avg_order_value is not None and brief.avg_order_value > 0
    # CTR needed so revenue (= imps × CTR × conv × AOV) exactly equals budget.
    denom = imps * conv_rate * aov_used
    break_even_ctr = (brief.budget / denom) if denom > 0 else None
    headroom = ((sample_ctr / break_even_ctr)
                if break_even_ctr and break_even_ctr > 0 else None)
    economics = {
        "currency": req.currency,
        "geo": req.geo,
        "avg_order_value": round(aov_used, 2),
        "avg_order_value_source": "your figure" if aov_is_real else "estimated (no figure supplied)",
        "product_price": req.product_price,
        "conversion_rate": conv_rate,
        "budget": brief.budget,
        "impressions": imps,
        "modelled_ctr": sample_ctr,
        "benchmark_ctr": fmt_bench_ctr,
        "break_even_ctr": break_even_ctr,
        "clears_break_even": (sample_ctr >= break_even_ctr) if break_even_ctr else None,
        "headroom_x": round(headroom, 2) if headroom else None,
        # Honest verdict on the ECONOMICS (not a revenue promise):
        "verdict": (
            "comfortable" if headroom and headroom >= 1.5
            else "marginal" if headroom and headroom >= 1.0
            else "shortfall" if headroom else "unknown"
        ),
    }

    # Plain-English data provenance / confidence breakdown.
    visual_obj = result["visual"]
    visual_source = (visual_obj.provider
                     if visual_obj is not None else "none")

    # Which LLM is the active provider right now? Order matches _select_provider
    # in llm.py (Claude > OpenAI > Gemini).
    import os as _os
    if _os.environ.get("ANTHROPIC_API_KEY"):
        active_llm = "Claude"
    elif _os.environ.get("OPENAI_API_KEY"):
        active_llm = "GPT-4o"
    elif _os.environ.get("GEMINI_API_KEY"):
        active_llm = "Gemini"
    else:
        active_llm = None

    # Visual provider human label.
    visual_label = {
        "claude": "Claude (multimodal)",
        "openai": "GPT-4o (multimodal)",
        "gemini": "Gemini 2.5 Flash (multimodal)",
        "heuristic": "heuristic — image not inspected",
        "none": "no image uploaded",
    }.get(visual_source, visual_source)

    bench_year = brief.format.benchmarks.get("as_of", BENCHMARK_AS_OF)
    data_sources = [
        {"label": "Personas",
         "value": f"{mc_dict['audience_size']} synthetic personas (2026 consumption patterns)",
         "note": "Sampled with 2026 platform-share + media-time distributions. NOT your real customers — see 'Upload past performance' (v1.1) to recalibrate against your own data."},
        {"label": "CTR benchmark",
         "value": f"{fmt_bench_ctr*100:.2f}% ({bench_year} industry avg)",
         "note": (f"Industry mid-range for {brief.format.name}. Real campaigns vary 2–5×. "
                  + ("Use the 🔎 Refresh from web button on Step 2 of the wizard for live published numbers."
                     if active_llm == "Gemini" else "Connect a Gemini key for the 🔎 live-refresh feature."))},
        {"label": "Company parsing",
         "value": (f"✨ {active_llm}" if profile.source == "llm" and active_llm
                   else "keyword heuristic"),
         "note": (f"Free-text → structured profile via {active_llm}."
                  if profile.source == "llm" and active_llm
                  else "Keyword heuristic — may misclassify niche businesses. Connect a Gemini key (free at aistudio.google.com/apikey) for full semantic parsing.")},
        {"label": "Audience match",
         "value": (f"✨ {active_llm} → '{match.segment}'"
                   if match.source == "llm" and active_llm
                   else f"keyword heuristic → '{match.segment}'"),
         "note": (f"Confidence {match.confidence:.0%} — {active_llm} mapped your description onto the persona segment."
                  if match.source == "llm" and active_llm
                  else "Keyword match. Niche audiences fall back to 'all'. Connect a Gemini key for semantic mapping.")},
        {"label": "Visual analysis",
         "value": visual_label + (" ✨" if visual_source not in ("heuristic", "none") else ""),
         "note": ((f"{active_llm or 'Multimodal LLM'} examined your image and scored it against the rubric. "
                   + (f"It described what it saw as: \"{visual_obj.image_description[:160]}…\"" if visual_obj and visual_obj.image_description else ""))
                  if visual_source not in ("heuristic", "none")
                  else "Heuristic: image colour + contrast statistics + copy keywords. Does NOT 'understand' what's in the picture. Connect a Gemini key for true multimodal scoring.")},
        {"label": "Order value (AOV)",
         "value": (f"{req.currency} {aov_used:,.0f} — your figure" if aov_is_real
                   else f"{req.currency} {aov_used:,.0f} — estimated"),
         "note": ("Revenue = conversions × this value. Because you supplied your real order value, the break-even math below is grounded in YOUR economics, not a synthetic guess."
                  if aov_is_real
                  else "No order value supplied — we estimated from your category, which is a weak guess. Enter your real average order value for accurate break-even math.")},
        {"label": "Calibration",
         "value": "synthetic CTR dataset (replaceable)",
         "note": "Psychology-rule weights fitted on a generated dataset, not your past performance. Upload your Meta/Google/LinkedIn CSV exports (coming) to recalibrate against YOUR campaigns."},
    ]

    # Confidence rating: stricter when key inputs are heuristic.
    heuristic_count = sum(1 for s in (profile.source, match.source, visual_source)
                          if s in ("heuristic", "none"))
    if heuristic_count == 0:
        confidence = "medium"
        confidence_blurb = (f"All three smart-inputs ran on {active_llm} (company parse, audience match, image analysis). "
                            "Treat as a directional second opinion — accuracy lifts further when you upload your past performance.")
    elif heuristic_count <= 1:
        confidence = "low_medium"
        confidence_blurb = (f"{active_llm} is partially active. Useful for comparison, not for absolute revenue forecasting."
                            if active_llm else "Some inputs use heuristics. Useful for comparison only.")
    else:
        confidence = "low"
        confidence_blurb = ("Most inputs use keyword heuristics — no LLM connected. "
                            "Numbers are illustrative. Connect a Gemini key (free, no credit card) at aistudio.google.com/apikey to lift confidence.")

    # Run the copy critique against the brief's chosen format.
    copy_issues = [i.to_dict() for i in critique_copy(
        headline=req.headline, primary_text=req.primary_text,
        description=req.description, cta=req.cta, link=req.link,
        fmt=brief.format, profile=profile,
    )]

    return {
        "company": profile.to_dict(),
        "match": match.to_dict(),
        "brief": brief.to_dict(),
        "format": {
            "id": brief.format.id,
            "name": brief.format.name,
            "platform": brief.format.platform_name,
            "benchmarks": brief.format.benchmarks,
        },
        "copy_critique": copy_issues,
        "mc": _strip_unserialisable(mc_dict),
        "insights": result["insights"],
        "visual": (result["visual"].to_dict()
                   if result["visual"] is not None else None),
        "figures": figures,
        "validation": result["validation"],
        "headline_md": result["headline_md"],
        "visual_md": result["visual_md"],
        "narrative_md": result["narrative_md"],
        # New plain-English fields:
        "plain_verdict": {
            "headline": plain,
            "class": verdict_word,
            "roas_p50": round(roas, 2),
            "roi_p50_pct": round(mc_dict["predicted_roi"]["p50"] * 100, 0),
            "ctr_vs_bench_pct": round((sample_ctr - fmt_bench_ctr) / max(fmt_bench_ctr, 1e-6) * 100, 0),
            "break_even_chance_pct": round(
                sum(1 for r in mc_dict["sample_ctrs"]
                    if (r * mc_dict["total_impressions"] *
                        mc_dict["predicted_conversions"]["p50"] /
                        max(mc_dict["predicted_clicks"]["p50"], 1)) *
                       mc_dict["mean_aov"] >= mc_dict["budget"])
                / max(len(mc_dict["sample_ctrs"]), 1) * 100, 0),
        },
        "factor_plain": factor_plain,
        "data_sources": data_sources,
        "economics": economics,
        "confidence": {
            "level": confidence,
            "blurb": confidence_blurb,
            "heuristic_count": heuristic_count,
        },
    }


def _pretty_factor_label(key: str, value: float) -> str:
    """Marketer-friendly labels for the logit-decomposition factor names."""
    direction = "boosts" if value >= 0 else "drags"
    mapping = {
        "visual": "Visual quality of the creative",
        "psychology": "Persuasion cues in the copy",
        "persona_match": "Audience / channel / category fit",
        "word_of_mouth": "Word-of-mouth on the social graph",
        "fatigue": "Repeat-exposure fatigue",
    }
    return f"{mapping.get(key, key.replace('_', ' ').title())} {direction} performance"
