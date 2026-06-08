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
import os
import shutil
import sys
import threading
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
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
from llm import have_any_key, text_complete, extract_json  # noqa: E402
from outcomes import calibrate_rows, ingest_and_calibrate  # noqa: E402
from pipeline import VisionUnavailableError, run_wizard_simulation  # noqa: E402
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
    # --- Per-account calibration (Path B): the advertiser's REAL CTR / CPM
    # from their ad history, override the generic format benchmarks. ---------
    target_ctr: Optional[float] = None
    cpm_override: Optional[float] = None
    # Pillar B: provenance for the anchor — which calibration layer the
    # frontend picked + how many ads it was built from. Surfaced in the
    # result page's data-provenance row so users can see whether the
    # forecast leaned on their AUDIENCE segment, the platform average, or
    # the overall account.
    # Pillar B+ widens 'segment:<seg>' to 'segment:<seg>:interest:<int>'
    # when a (segment × interest) cell was matched. The label parser in
    # _calibration_provenance_value handles both shapes.
    calibration_source: Optional[str] = None  # 'segment:<seg>[:interest:<int>]' | 'interest:<int>' | 'platform:<plat>' | 'overall' | None
    calibration_n_ads: Optional[int] = None
    # Pillar B+: the user-chosen interests (after wizard mapping to the
    # canonical taxonomy). Stored on creative_scores and surfaced in the
    # report's provenance row. Empty list = no interest signal.
    interests: List[str] = []
    reachable_audience: Optional[int] = None   # opt-in budget saturation
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


# ---------------------------------------------------------------------------
# Provider health — live "is each LLM working / has any quota run out" view.
# Powers the diagnostics page so the owner sees the MOMENT a provider's quota
# runs out instead of only noticing heuristic fallbacks after the fact.
# ---------------------------------------------------------------------------

# Canonical provider names (matching the event names recorded by llm.py /
# visual_analysis.py) mapped to their env var.
_PROVIDER_ENV = {
    "claude":     "ANTHROPIC_API_KEY",
    "openai":     "OPENAI_API_KEY",
    "gemini":     "GEMINI_API_KEY",
    "groq":       "GROQ_API_KEY",
    "mistral":    "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "xai":        "XAI_API_KEY",
    "together":   "TOGETHER_API_KEY",
}


@app.get("/api/admin/provider-health")
def provider_health_snapshot() -> dict:
    """Snapshot of provider liveness: which keys are present, the last ok/error
    per provider, currently-exhausted models, and recent quota/error events."""
    import os as _os
    import provider_health as _ph
    keys = {p: bool(_os.environ.get(env)) for p, env in _PROVIDER_ENV.items()}
    return {"keys": keys, **_ph.snapshot()}


@app.post("/api/admin/ping-providers")
def ping_providers() -> dict:
    """Actively test each provider that has a key, in ISOLATION (no fallback),
    recording each outcome so the health snapshot reflects live state. Lets the
    owner click one button and see exactly which providers answer right now."""
    import os as _os
    from llm import _try_provider, _is_quota_error  # noqa: E402
    import provider_health as _ph
    results = []
    for prov, env in _PROVIDER_ENV.items():
        if not _os.environ.get(env):
            results.append({"provider": prov, "status": "no_key"})
            continue
        try:
            out = _try_provider(
                prov, "Reply with the single word: ok",
                "You are a connectivity test. Reply with exactly: ok", 8, False)
            if out and "ok" in out.lower():
                _ph.record_ok(prov)
                results.append({"provider": prov, "status": "ok"})
            else:
                _ph.record_error(prov, "", "empty/None response")
                results.append({"provider": prov, "status": "error",
                                "reason": "empty response"})
        except Exception as exc:                       # noqa: BLE001
            reason = str(exc)[:200]
            if _is_quota_error(exc):
                _ph.record_quota(prov, "", reason)
                results.append({"provider": prov, "status": "quota", "reason": reason})
            else:
                _ph.record_error(prov, "", reason)
                results.append({"provider": prov, "status": "error", "reason": reason})
    return {"results": results, **_ph.snapshot()}


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

# Uploads default to the repo's data dir (fine for local dev), but on a host
# with an EPHEMERAL filesystem (e.g. Railway) that folder is wiped on every
# restart/redeploy — so a creative uploaded one moment can be gone the next,
# breaking analysis. Point ADPROOF_UPLOAD_DIR at a mounted persistent volume in
# production so uploads survive deploys.
UPLOAD_DIR = Path(os.environ.get("ADPROOF_UPLOAD_DIR")
                  or (_PROJECT_ROOT / "data" / "raw" / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_ALLOWED_MIME = {
    "image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif",
    "video/mp4", "video/quicktime", "video/webm", "video/x-matroska",
    "video/3gpp", "video/x-msvideo", "video/mpeg",
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


@app.post("/api/ingest-outcomes")
async def ingest_outcomes(file: UploadFile = File(...),
                          segment: str = Form("general")) -> dict:
    """Parse a real ad-performance export (Meta/Google/our template) and
    compute per-account real benchmarks — CTR/CPM/CPC, plus conversion-rate
    and ROAS where the file actually contains that data.

    Stateless: the cleaned rows + calibration are returned for the frontend to
    persist under the logged-in user (RLS), so one account's data never becomes
    a shared prior. This is Path B, part 1.
    """
    name = (file.filename or "").lower()
    if not name.endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(status_code=400,
                            detail="Please upload a .csv or .xlsx export.")
    try:
        data = await file.read()
    finally:
        await file.close()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 25 MB).")
    seg = segment if segment in ("general", "b2b_saas") else "general"
    try:
        return ingest_and_calibrate(data, file.filename or "upload", segment=seg)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422,
                            detail=f"Could not parse this export: {str(e)[:300]}")


# ===========================================================================
# Live ad-account connection (Phase 3) — pull REAL performance read-only
# ===========================================================================

class ConnectionSyncRequest(BaseModel):
    provider: str = "meta"
    access_token: str
    account_id: str
    since: str                       # YYYY-MM-DD
    until: str                       # YYYY-MM-DD
    segment: str = "general"
    currency: str = "GBP"


@app.post("/api/connections/sync")
def connections_sync(req: ConnectionSyncRequest) -> dict:
    """Pull REAL ad performance from a connected account (read-only) and return
    an ingest-shaped payload (calibration + backtest + fatigue + rows) for the
    frontend to render and persist under the logged-in user (RLS).

    The token is used for THIS request only and is not stored here — persistent,
    encrypted connections land in the next slice (the ad_connections table).
    Works today with a Meta access token (e.g. from Graph API Explorer / a
    System User token) — no registered OAuth app required to try it.
    """
    from connectors import pull_outcomes
    seg = req.segment if req.segment in ("general", "b2b_saas") else "general"
    try:
        rows = pull_outcomes(req.provider, req.access_token, req.account_id,
                             req.since, req.until)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:                            # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Pull failed: {str(e)[:300]}")
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No ads returned for that account / date range.")
    return calibrate_rows(rows, currency=req.currency, segment=seg,
                          source=req.provider)


# Serve uploaded files back so the wizard can preview them.
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


# ===========================================================================
# Pillars E + F: Blotato MCP integrations
# ===========================================================================
# Live MCP tools list (verified) is publishing/scheduling/asset-generation
# only — no scoring. So these endpoints use create_visual (for variant
# generation, Pillar E) and create_source (for competitor / landing-page
# extraction, Pillar F). All gated on BLOTATO_API_KEY: when unset, every
# call returns 503 with a friendly "feature disabled" body so the UI can
# hide the surface entirely.


class BlotatoVariantsRequest(BaseModel):
    template_id: Optional[str] = None     # explicit template; else pick the first
    variables: dict = {}                  # template-specific variables
    count: int = 3                        # how many variants to generate
    wait: bool = True                     # poll until done (synchronous)


@app.get("/api/blotato/status")
def blotato_status() -> dict:
    """Cheap feature-availability probe for the UI to hide / show panels."""
    from blotato_client import is_enabled
    return {"enabled": is_enabled()}


@app.get("/api/blotato/templates")
def blotato_templates() -> dict:
    """List the visual templates Blotato exposes for this account."""
    try:
        from blotato_client import BlotatoClient
        client = BlotatoClient()
        return {"templates": client.list_visual_templates()}
    except Exception as exc:                              # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/blotato/generate-variants")
def blotato_generate_variants(req: BlotatoVariantsRequest) -> dict:
    """Pillar E: generate N visual variants via Blotato MCP create_visual.

    Stateless from AdProof's side: returns the generated visual descriptors
    (URLs + status). Re-scoring each variant happens through the normal
    /api/simulate flow once the user wires it back in as an upload.

    Cost gate: count is capped at 3 to keep Blotato credit burn predictable
    (the owner's primary concern when picking this pillar).
    """
    try:
        from blotato_client import BlotatoClient
        client = BlotatoClient()
    except Exception as exc:                              # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc))

    # Pick a template — explicit one wins, else first available.
    template_id = req.template_id
    if not template_id:
        templates = client.list_visual_templates()
        if not templates:
            raise HTTPException(status_code=502,
                                detail="No Blotato visual templates available.")
        template_id = (templates[0].get("id")
                       or templates[0].get("templateId")
                       or "")

    n = max(1, min(int(req.count or 3), 3))               # cap at 3
    out: list = []
    for _ in range(n):
        try:
            job = client.create_visual(template_id, req.variables)
        except Exception as exc:                          # noqa: BLE001
            out.append({"status": "error", "error": str(exc)})
            continue
        visual_id = (job.get("visualId") or job.get("id")
                     if isinstance(job, dict) else None)
        if req.wait and visual_id:
            try:
                final = client.wait_for_visual(visual_id)
                out.append({"status": (final.get("status") or "").lower(),
                            "visual_id": visual_id, "result": final})
            except Exception as exc:                      # noqa: BLE001
                out.append({"status": "error", "visual_id": visual_id,
                            "error": str(exc)})
        else:
            out.append({"status": "queued", "visual_id": visual_id,
                        "job": job})
    return {"template_id": template_id, "variants": out}


class BlotatoExtractRequest(BaseModel):
    url: Optional[str] = None
    text: Optional[str] = None
    wait: bool = True


@app.post("/api/blotato/extract-source")
def blotato_extract_source(req: BlotatoExtractRequest) -> dict:
    """Pillar F: extract a competitor ad / landing page via Blotato create_source.

    Returns the extracted media URLs + text so the frontend can pass them
    straight into the normal AdProof flow (re-upload as an image / video
    and analyse). No scoring happens here — extraction only.
    """
    if not (req.url or req.text):
        raise HTTPException(status_code=400,
                            detail="Provide either url or text.")
    try:
        from blotato_client import BlotatoClient
        client = BlotatoClient()
    except Exception as exc:                              # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc))
    try:
        job = client.create_source(url=req.url, text=req.text)
    except Exception as exc:                              # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))
    source_id = (job.get("sourceId") or job.get("id")
                 if isinstance(job, dict) else None)
    if req.wait and source_id:
        try:
            final = client.wait_for_source(source_id)
            return {"status": (final.get("status") or "").lower(),
                    "source_id": source_id, "result": final}
        except Exception as exc:                          # noqa: BLE001
            return {"status": "error", "source_id": source_id,
                    "error": str(exc)}
    return {"status": "queued", "source_id": source_id, "job": job}


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
    geo: str = "UK"                # advertiser's market → which regulator applies


_PLATFORM_POLICY_HINT = {
    "meta_facebook": "Meta Advertising Standards (transparency.meta.com/policies/ad-standards)",
    "meta_instagram": "Meta Advertising Standards (transparency.meta.com/policies/ad-standards)",
    "google_search": "Google Ads Policies (support.google.com/adspolicy)",
    "google_display": "Google Ads Policies (support.google.com/adspolicy)",
    "youtube": "Google Ads + YouTube ad policies",
    "linkedin": "LinkedIn Advertising Policies (linkedin.com/legal/ads-policy)",
    "tiktok": "TikTok For Business Advertising Policies (ads.tiktok.com/help/article/advertising-policies)",
}

# Map the advertiser's market to its advertising regulator(s) so the check
# covers the LAW, not just the platform's house rules. AdProof is UK-based,
# so UK is the most fleshed-out.
_JURISDICTION_REGULATORS = {
    "UK": "the UK ASA / CAP Code (asa.org.uk) — and the FCA for financial "
          "promotions, MHRA for health claims, Gambling Commission for betting",
    "US": "the US FTC Act / FTC endorsement & 'Made in USA' guides (ftc.gov), "
          "plus FDA for health claims and state-level rules",
    "EU": "EU consumer-protection + national advertising codes (e.g. UCPD), "
          "EASA self-regulatory standards",
    "Canada": "Ad Standards Canada (adstandards.ca) + the Competition Bureau",
    "Australia": "Ad Standards Australia (adstandards.com.au) + ACCC",
    "Global": "the platform's own global ad policies (no single regulator)",
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
    geo = (req.geo or "UK").strip()
    regulator = _JURISDICTION_REGULATORS.get(geo, _JURISDICTION_REGULATORS["Global"])

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
PLATFORM POLICY SOURCE: {policy_source}
ADVERTISER MARKET: {geo}
APPLICABLE REGULATOR(S): {regulator}
{industry_hint}

TASK
1. Use Google Search to read BOTH (a) the CURRENT ({BENCHMARK_AS_OF}) platform
   advertising policy AND (b) the {geo} legal/regulator rules above. Many ads
   pass platform rules but breach the law of the advertiser's country
   (e.g. UK ASA substantiation + FCA financial-promotion rules differ from US
   FTC). Check BOTH layers.
2. Evaluate this ad copy against both the platform policy and {geo} regulation:

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
        "jurisdiction": geo,
        "regulator": regulator,
        "summary": parsed.get("summary", ""),
        "overall_risk": parsed.get("overall_risk", "unknown"),
        "policy_source_url": parsed.get("policy_source_url", ""),
        "policies_consulted_year": parsed.get("policies_consulted_year", BENCHMARK_AS_OF),
        "issues": parsed.get("issues", []),
        "grounding_sources": grounding_urls[:5],
    }


# ---------------------------------------------------------------------------
# Market & cultural context (Gemini grounded) — the differentiator.
# Culture + seasonality + recent events for {geo} × {industry} × {month}.
# Cached by (geo, industry, year-month) so the 4 variants of one campaign —
# and repeat campaigns the same month — reuse a single grounded call.
# ---------------------------------------------------------------------------

_MARKET_CONTEXT_CACHE: dict = {}
_MARKET_CACHE_MAX = 128


class MarketContextRequest(BaseModel):
    geo: str = "UK"
    industry: str = ""
    product: str = ""              # what they sell, one line
    company_description: str = ""


@app.post("/api/market-context")
def market_context(req: MarketContextRequest) -> dict:
    """Web-grounded cultural / seasonal / recent-events read for the target
    market. This is what makes the tool feel locally-aware instead of a
    generic synthetic model: it flags tone norms for the geo, whether the ad
    is timed for a real sales window, and any current events the copy could
    leverage (or must avoid)."""
    import os as _os
    from datetime import datetime, timezone
    key = _os.environ.get("GEMINI_API_KEY")
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Connect a Gemini key in /settings for market & cultural context.",
        )

    geo = (req.geo or "UK").strip()
    industry = (req.industry or "general consumer").strip()
    now = datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")
    cache_key = f"{geo.lower()}|{industry.lower()}|{month_key}"
    if cache_key in _MARKET_CONTEXT_CACHE:
        cached = dict(_MARKET_CONTEXT_CACHE[cache_key])
        cached["cached"] = True
        return cached

    month_name = now.strftime("%B %Y")
    prompt = f"""You are a {geo} advertising strategist. It is {month_name}.
A business in "{industry}" ({req.product or req.company_description or 'see industry'})
is about to run a paid ad to a {geo} audience.

Use web search for anything current. Return ONLY this JSON (no prose):
{{
  "geo": "{geo}",
  "as_of": "{month_name}",
  "cultural_notes": ["<short, {geo}-specific tone/idiom/spelling norms to respect — e.g. avoid US-style hype, use 'colour' not 'color'>", "..."],
  "seasonality": {{
    "current_window": "<the relevant sales/seasonal window happening now or imminent in {geo}, or 'none notable'>",
    "advice": "<one line: how to play it, or what to wait for>"
  }},
  "recent_events": [
    {{"event": "<a current {geo} event/trend/news this category could intersect>", "use_as": "<leverage | landmine>", "note": "<one line why>"}}
  ],
  "overall": "<2-sentence verdict on whether the timing + cultural fit favour this ad right now in {geo}>"
}}
RULES: max 3 items per array. Keep EACH string under 18 words — terse phrases,
not paragraphs (long output gets truncated). Be specific to {geo} and {month_name}."""

    try:
        # Bigger budget — grounded search consumes tokens, and a truncated
        # reply means the JSON never closes and fails to parse.
        response, model_used = _gemini_grounded_call(prompt, max_tokens=4096)
    except Exception as exc:                          # noqa: BLE001
        msg = str(exc)
        status = 503 if "429" in msg or "RESOURCE_EXHAUSTED" in msg else 502
        raise HTTPException(
            status_code=status,
            detail=f"Market-context check failed: {msg[:200]}.",
        )

    raw_text = response.text or ""
    import re as _re
    cleaned = _re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
    cleaned = _re.sub(r"\s*```$", "", cleaned)
    s, e = cleaned.find("{"), cleaned.rfind("}")
    parsed: dict = {}
    if s != -1 and e != -1 and e > s:
        try:
            parsed = json.loads(cleaned[s:e + 1])
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

    out = {
        "geo": geo,
        "industry": industry,
        "as_of": month_name,
        "context": parsed,
        "sources": grounding_urls[:5],
        "model": model_used,
        "cached": False,
    }
    # Store (trim cache if needed).
    if len(_MARKET_CONTEXT_CACHE) >= _MARKET_CACHE_MAX:
        _MARKET_CONTEXT_CACHE.pop(next(iter(_MARKET_CONTEXT_CACHE)), None)
    _MARKET_CONTEXT_CACHE[cache_key] = out
    return out


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
# Smart audience suggestion — read the company profile and pick the TIGHT,
# relevant targeting from the platform catalogue (instead of dumping every
# generic interest on the user). The frontend sends its own chip catalogue so
# the model can only return ids the UI knows how to toggle.
# ---------------------------------------------------------------------------

class AudienceChip(BaseModel):
    id: str
    label: str
    group: str = ""


class SuggestAudienceRequest(BaseModel):
    company_description: str = ""
    industry: str = ""
    product_category: str = ""
    business_model: str = ""
    value_proposition: str = ""
    conversion_goal: Optional[str] = None
    platform_id: str = "meta_instagram"
    available_chips: list[AudienceChip] = []


@app.post("/api/suggest-audience")
def suggest_audience(req: SuggestAudienceRequest) -> dict:
    valid_ids = {c.id for c in req.available_chips}
    # Compact, grouped catalogue for the prompt.
    by_group: dict = {}
    for c in req.available_chips:
        by_group.setdefault(c.group or "Other", []).append(f"{c.id} = {c.label}")
    catalogue = "\n".join(
        f"[{g}]\n  " + "\n  ".join(items) for g, items in by_group.items())

    system = ("You are a senior paid-social strategist. You choose the TIGHTEST, "
              "most relevant audience targeting for ONE specific company. Be "
              "ruthless — only include targeting that genuinely fits this "
              "business; never pad with generic interests (e.g. do NOT pick "
              "'Skincare' or 'Parent of newborn' for a B2B SaaS). Reply with "
              "strict JSON only.")
    prompt = (
        f"COMPANY\n"
        f"- Industry: {req.industry or 'n/a'}\n"
        f"- Sells: {req.value_proposition or req.product_category or 'n/a'}\n"
        f"- Model: {req.business_model or 'n/a'}\n"
        f"- Goal: {req.conversion_goal or 'conversions'}\n"
        f"- Notes: {req.company_description[:600]}\n\n"
        f"PLATFORM: {req.platform_id}\n\n"
        f"AVAILABLE TARGETING (id = label):\n{catalogue}\n\n"
        f"Pick ONLY ids that genuinely fit this company. Also suggest up to 4 "
        f"EXTRA interests not in the list. Recommend a gender. Reply JSON:\n"
        f'{{"selected_chip_ids": ["..."], "custom_interests": ["..."], '
        f'"gender": "all|women|men", "rationale": "one sentence why", '
        f'"audience_name": "short name"}}')

    raw = text_complete(prompt, system=system, max_tokens=700, json_mode=True) \
        if have_any_key() else None
    data = extract_json(raw) or {}
    selected = [i for i in (data.get("selected_chip_ids") or []) if i in valid_ids]
    gender = data.get("gender")
    return {
        "selected_chip_ids": selected,
        "custom_interests": [str(x)[:40] for x in (data.get("custom_interests") or [])][:4],
        "gender": gender if gender in ("all", "women", "men") else "all",
        "rationale": str(data.get("rationale", ""))[:220],
        "audience_name": str(data.get("audience_name", ""))[:60],
        "source": "llm" if (raw and selected) else "unavailable",
    }


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


# Concurrency gate for the heavy forecast path. The wizard fires variants /
# placements in PARALLEL, so without this several 20-run Monte Carlos + video
# analyses pile up at once and OOM-kill the whole worker on a small instance —
# which takes the entire app down (every request 502s) until it restarts, not
# just the heavy one. Serialise the heavy work (default 1 at a time) so a burst
# queues instead of crashing. Bump ADPROOF_SIMULATE_CONCURRENCY if the host has
# memory headroom.
_SIMULATE_GATE = threading.Semaphore(
    max(1, int(os.environ.get("ADPROOF_SIMULATE_CONCURRENCY", "1") or "1")))


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

    # Daily reach is no longer a user input — default it. Fatigue-sensitive
    # categories (apparel/fashion/beauty) get a lower daily reach so the same
    # person isn't shown the ad as often (frequency builds more slowly).
    _cat = (profile.product_category or "").lower()
    _daily_reach = 0.25 if any(k in _cat for k in
                               ("apparel", "fashion", "beauty", "cosmetic")) else 0.35

    brief = CampaignBrief(
        objective=req.objective,
        platform_id=req.platform_id,
        format_id=req.format_id,
        budget=req.budget, days=req.days,
        daily_reach=_daily_reach, n_runs=req.n_runs,
        target_conversion_rate=req.target_conversion_rate,
        target_ctr_override=req.target_ctr,
        cpm_override=req.cpm_override,
        reachable_audience=req.reachable_audience,
        avg_order_value=req.avg_order_value,
        product_price=req.product_price,
        currency=req.currency,
        geo=req.geo,
        interests=list(req.interests or []),
    )
    assets = CreativeAssets(
        image_path=req.image_path, video_path=req.video_path,
        headline=req.headline, primary_text=req.primary_text,
        description=req.description, cta=req.cta, link=req.link,
    )

    try:
        # Serialise the memory-heavy section so parallel variant runs queue
        # instead of stacking memory and OOM-killing the worker.
        with _SIMULATE_GATE:
            result = run_wizard_simulation(
                profile=profile, match=match, brief=brief, assets=assets,
                visual_provider=req.visual_provider,
            )
    except VisionUnavailableError as exc:
        # The image couldn't be inspected by a real vision model, so the run
        # is refused (no forecast). 422 = the request was valid but we can't
        # responsibly produce a result for it right now.
        detail = str(exc)
        if exc.provider_error:
            detail += f" (technical detail: {exc.provider_error})"
        raise HTTPException(status_code=422, detail=detail)
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

    # Break-even probability — the share of Monte Carlo runs that at least return
    # the budget. Computed ONCE here and reused as the single source of truth for
    # the break-even messaging, so the headline's risk wording can never
    # contradict the "X% chance of breaking even" number on the card (the old bug
    # showed "risky" next to "100% chance").
    _be_imps = ((mc_dict.get("saturation") or {}).get("effective_impressions")
                or mc_dict.get("total_impressions", 0))
    _conv_per_click = (mc_dict.get("predicted_conversions", {}).get("p50", 0)
                       / max(mc_dict.get("predicted_clicks", {}).get("p50", 1), 1))
    _aov_be = mc_dict.get("mean_aov", 0)
    _budget_be = mc_dict.get("budget", 1)
    _ctrs = mc_dict.get("sample_ctrs") or []
    break_even_probability = round(
        sum(1 for r in _ctrs
            if r * _be_imps * _conv_per_click * _aov_be >= _budget_be)
        / max(len(_ctrs), 1) * 100, 0)

    # Objective-aware verdict. Each campaign objective is graded on the
    # metric that actually matters to it — an awareness campaign judged on
    # ROAS would be marked "underperforming" even when it's doing its job.
    #   awareness    -> CPM / reach (ROAS is irrelevant; nobody's buying yet)
    #   consideration -> CTR / CPC (engagement is the unit of success)
    #   conversion   -> ROAS (existing logic, the only objective with revenue)
    objective = (brief.objective or "conversion").lower()
    _mean_aov = mc_dict.get("mean_aov", 0) or 0
    _conv = (brief.target_conversion_rate or 0.025)
    _cur = brief.currency or "GBP"

    # CPM in real money: budget per thousand impressions. The format benchmark
    # CPM is used as the comparison anchor for the awareness verdict.
    _bench_cpm = brief.format.benchmarks.get("cpm", 8.0) or 8.0
    _raw_imps_for_cpm = max(mc_dict.get("total_impressions", 0), 1)
    _cpm_value = (brief.budget / _raw_imps_for_cpm) * 1000

    if objective == "awareness":
        if _cpm_value <= _bench_cpm * 0.75:
            verdict_word = "wide_reach"
            plain = (f"Wide reach — {_cur} {_cpm_value:.2f} CPM beats the "
                     f"{_cur} {_bench_cpm:.2f} format benchmark by "
                     f"{(1 - _cpm_value/_bench_cpm)*100:.0f}%. Strong "
                     f"awareness-campaign economics.")
        elif _cpm_value <= _bench_cpm * 1.10:
            verdict_word = "moderate_reach"
            plain = (f"Reach is in line with benchmark — {_cur} {_cpm_value:.2f} "
                     f"CPM vs the {_cur} {_bench_cpm:.2f} format average. The "
                     f"creative is doing its job for an awareness brief.")
        else:
            verdict_word = "narrow_reach"
            plain = (f"Reach is expensive — {_cur} {_cpm_value:.2f} CPM is "
                     f"{(_cpm_value/_bench_cpm - 1)*100:.0f}% above the "
                     f"{_cur} {_bench_cpm:.2f} format benchmark. Strengthen the "
                     f"hook / attention before scaling spend.")
    elif objective == "consideration":
        if sample_ctr >= fmt_bench_ctr * 1.25:
            verdict_word = "strong_engagement"
            plain = (f"Strong engagement — {sample_ctr*100:.2f}% CTR is "
                     f"{(sample_ctr/fmt_bench_ctr - 1)*100:.0f}% above the "
                     f"{fmt_bench_ctr*100:.2f}% format benchmark. The creative "
                     f"earns the click.")
        elif sample_ctr >= fmt_bench_ctr * 0.90:
            verdict_word = "fair_engagement"
            plain = (f"Engagement in line with benchmark — {sample_ctr*100:.2f}% "
                     f"CTR vs the {fmt_bench_ctr*100:.2f}% format average. Fine "
                     f"for a consideration brief; not a runaway winner.")
        else:
            verdict_word = "weak_engagement"
            plain = (f"Engagement below benchmark — {sample_ctr*100:.2f}% CTR "
                     f"vs {fmt_bench_ctr*100:.2f}% format average "
                     f"({(1 - sample_ctr/fmt_bench_ctr)*100:.0f}% short). The "
                     f"ad isn't earning the click — improve the hook or "
                     f"relevance.")
    else:                                            # "conversion" (or unknown)
        # Verdict CLASS is about magnitude of return (ROAS p50); the risk
        # wording is about the ODDS (break_even_probability) — kept separate
        # so they agree.
        if roas >= 4.0:
            plain = "Likely to be a strong winner."
            verdict_word = "strong"
        elif roas >= 2.0:
            plain = "Likely profitable — should pay back well."
            verdict_word = "positive"
        elif roas >= 1.0:
            plain = "Around break-even on the median forecast."
            verdict_word = "break_even"
        else:
            plain = "Likely to lose money — don't ship as is."
            verdict_word = "underperforming"

        # Risk clause derived from the SAME probability shown on the card.
        if verdict_word != "underperforming":
            if break_even_probability >= 85:
                plain += f" Very likely to at least break even ({break_even_probability:.0f}% of simulations did)."
            elif break_even_probability >= 50:
                plain += f" Not a sure thing — only {break_even_probability:.0f}% of simulations cleared break-even."
            else:
                plain += f" Risky — just {break_even_probability:.0f}% of simulations cleared break-even."

        # ---- Believability guardrails (conversion objective only — the
        # ROAS guardrails don't apply to awareness/consideration) ----
        if roas > 12.0:
            # An implausibly high ROAS is almost always an overstated input,
            # not a real forecast. Refuse to celebrate it; point at the
            # likely culprits.
            verdict_word = "underperforming" if verdict_word == "underperforming" else "break_even"
            plain = (f"A {roas:.0f}× ROAS is implausibly high — real campaigns are "
                     f"usually 1–8×. This almost always means an input is overstated: "
                     f"check your conversion rate ({_conv*100:.1f}%) and order value "
                     f"({_cur} {_mean_aov:,.0f}). Treat the number as a red flag, not "
                     f"a result.")
        elif sample_ctr < fmt_bench_ctr * 0.90 and verdict_word in ("strong", "positive"):
            # A below-benchmark click-through is not a strong creative — any
            # decent return is coming from economics, not the ad itself.
            verdict_word = "break_even"
            plain = ("The ad's click-through is below the format benchmark, so this "
                     "isn't a strong creative — any decent return is coming from your "
                     "economics, not the ad. Strengthen the creative before scaling.")

    # ----------------------------------------------------------------------
    # VIABILITY GATE — the forecast assumes the ad actually RUNS. If the
    # creative will be rejected (nudity/prohibited content) or is
    # fundamentally broken (image has zero connection to the copy/brand), the
    # ROAS is meaningless and MUST NOT be shown as a green "Grade A" result.
    # This gate overrides the verdict so a nude image with B2B copy can never
    # read as "6.25x — strong". A banned ad's real ROAS is £0.
    # ----------------------------------------------------------------------
    _v = result.get("visual")
    _is_heur = bool(getattr(_v, "is_heuristic", True)) if _v else True
    _ban = (getattr(_v, "ban_risk", None) or {}) if _v else {}
    _ban_level = str(_ban.get("level", "unknown")).lower()
    _coh = getattr(_v, "image_copy_coherence", None) if _v else None
    _brand = getattr(_v, "brand_relevance", None) if _v else None

    blockers: list = []
    # FATAL — the ad will be rejected at upload / suspended. Only trust this
    # when a real vision model (not the heuristic) made the call.
    if not _is_heur and _ban_level == "high":
        blockers.append({
            "severity": "fatal", "kind": "policy",
            "label": "Will be rejected — policy violation",
            "detail": _ban.get("explanation")
                      or "The image breaches platform advertising policy "
                         "(e.g. nudity / prohibited content) and will be "
                         "rejected or get the account suspended.",
            "flags": _ban.get("flags", []),
        })
    # SEVERE — the creative is fundamentally mismatched; any forecast built on
    # a benchmark CTR is fiction because nobody engages with an incoherent ad.
    if not _is_heur and _coh is not None and _coh < 0.20:
        blockers.append({
            "severity": "severe", "kind": "coherence",
            "label": "Image and copy don't match",
            "detail": f"Image-copy coherence is {round(_coh*100)}%. The picture "
                      "has effectively no relationship to what the copy says, "
                      "so a benchmark-based CTR forecast doesn't apply.",
            "flags": [],
        })
    if not _is_heur and _brand is not None and _brand < 0.20:
        blockers.append({
            "severity": "severe", "kind": "brand",
            "label": "Image doesn't fit the brand",
            "detail": f"Brand fit is {round(_brand*100)}%. The creative would "
                      "damage brand credibility with this audience.",
            "flags": [],
        })

    has_fatal = any(b["severity"] == "fatal" for b in blockers)
    has_severe = any(b["severity"] == "severe" for b in blockers)
    runnable = not has_fatal

    if has_fatal:
        # Void the forecast entirely.
        verdict_word = "wont_run"
        plain = ("This ad won't run — it breaches advertising policy. "
                 "Fix the flagged issue before any forecast is meaningful.")
    elif has_severe:
        verdict_word = "broken_creative"
        plain = ("Forecast void — the creative is fundamentally broken "
                 "(image doesn't match the copy/brand). The ROAS below "
                 "assumes a coherent ad and does NOT apply here.")

    viability = {
        "runnable": runnable,
        "forecast_valid": not (has_fatal or has_severe),
        "blockers": blockers,
        "headline": plain,
        "verdict_class": verdict_word,
    }

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
    # Use EFFECTIVE (post-saturation) impressions so the break-even maths isn't
    # rosy when budget saturation is on (raw impressions overstate reach).
    imps = max((mc_dict.get("saturation") or {}).get("effective_impressions")
               or mc_dict.get("total_impressions", 0), 1)
    conv_rate = max(float(req.target_conversion_rate or 0.0), 1e-9)
    aov_used = float(mc_dict.get("mean_aov", 0.0) or 0.0)
    aov_is_real = brief.avg_order_value is not None and brief.avg_order_value > 0
    # CTR needed so revenue (= imps × CTR × conv × AOV) exactly equals budget.
    denom = imps * conv_rate * aov_used
    break_even_ctr = (brief.budget / denom) if denom > 0 else None
    headroom = ((sample_ctr / break_even_ctr)
                if break_even_ctr and break_even_ctr > 0 else None)
    # Plain "% vs break-even": negative = short of break-even, positive = above.
    # Replaces the unreadable "0.65× headroom" framing.
    pct_vs_breakeven = (round((sample_ctr - break_even_ctr) / break_even_ctr * 100, 0)
                        if break_even_ctr and break_even_ctr > 0 else None)
    economics = {
        "currency": req.currency,
        "geo": req.geo,
        "avg_order_value": round(aov_used, 2),
        "avg_order_value_source": "your figure" if aov_is_real else "estimated (no figure supplied)",
        # Honesty: when we had no real order value we GUESSED one — flag it and
        # give a soft range instead of a fake-precise number the UI can lean on.
        "aov_is_estimate": not aov_is_real,
        "aov_low": (round(aov_used * 0.85, 0) if (not aov_is_real and aov_used) else None),
        "aov_high": (round(aov_used * 1.15, 0) if (not aov_is_real and aov_used) else None),
        "product_price": req.product_price,
        "conversion_rate": conv_rate,
        "budget": brief.budget,
        "impressions": imps,
        "modelled_ctr": sample_ctr,
        "benchmark_ctr": fmt_bench_ctr,
        "break_even_ctr": break_even_ctr,
        "clears_break_even": (sample_ctr >= break_even_ctr) if break_even_ctr else None,
        "pct_vs_breakeven": pct_vs_breakeven,
        "headroom_x": round(headroom, 2) if headroom else None,
        # Honest verdict on the ECONOMICS (not a revenue promise):
        "verdict": (
            "comfortable" if headroom and headroom >= 1.5
            else "marginal" if headroom and headroom >= 1.0
            else "shortfall" if headroom else "unknown"
        ),
    }

    # ----------------------------------------------------------------------
    # KPI scoreboard — the plain numbers a marketer expects, derived from the
    # Monte Carlo bands (clicks/conversions/revenue/roas/roi already carry
    # p10/p50/p90). Cost metrics invert the band (more clicks => lower CPC).
    # ----------------------------------------------------------------------
    _clk = mc_dict.get("predicted_clicks", {})
    _cnv = mc_dict.get("predicted_conversions", {})
    _rev = mc_dict.get("predicted_revenue", {})
    _roas_b = mc_dict.get("predicted_roas", {})
    _roi_b = mc_dict.get("predicted_roi", {})
    _raw_imps = max(mc_dict.get("total_impressions", 0), 1)
    _bud = brief.budget or 0.0
    # Frequency (avg times each real person sees the ad) is ONLY meaningful when
    # the user set a reachable audience — otherwise it's impressions ÷ the
    # synthetic 1,000-persona panel, which is nonsense. Omit it otherwise.
    _sat_freq = (mc_dict.get("saturation") or {}).get("est_frequency")

    def _div(n, d):
        return (n / d) if d else 0.0

    # CPM and Reach — needed for the awareness hero card. Reach is unique
    # people; with frequency it's impressions/frequency, else impressions
    # (which is already a unique-person cap once saturation kicks in).
    _cpm_kpi = round((_bud / _raw_imps) * 1000, 2) if _raw_imps else 0
    _reach_kpi = round(_raw_imps / _sat_freq) if _sat_freq else _raw_imps

    # The hero metric for the result page — different per objective so an
    # awareness campaign isn't graded on ROAS.
    _lead = {
        "awareness": "cpm",
        "consideration": "ctr",
        "conversion": "roas",
    }.get(objective, "roas")

    kpis = {
        "currency": req.currency,
        "objective": objective,
        "lead": _lead,
        "impressions": {"value": _raw_imps},
        "reach": {"value": _reach_kpi},
        "cpm": {"value": _cpm_kpi, "benchmark": round(_bench_cpm, 2)},
        "frequency": ({"value": round(_sat_freq, 1)} if _sat_freq else None),
        "link_clicks": {"p10": round(_clk.get("p10", 0)), "p50": round(_clk.get("p50", 0)),
                        "p90": round(_clk.get("p90", 0))},
        "ctr": {"p50": round(sample_ctr, 5), "benchmark": round(fmt_bench_ctr, 5)},
        "conversions": {"p10": round(_cnv.get("p10", 0), 1), "p50": round(_cnv.get("p50", 0), 1),
                        "p90": round(_cnv.get("p90", 0), 1)},
        "conversion_rate": {"p50": round(_div(_cnv.get("p50", 0), _clk.get("p50", 0)), 5)},
        "cpc": {  # cost per click — band inverts: cheaper when clicks land high
            "p10": round(_div(_bud, _clk.get("p90", 0)), 2),
            "p50": round(_div(_bud, _clk.get("p50", 0)), 2),
            "p90": round(_div(_bud, _clk.get("p10", 0)), 2)},
        "cost_per_result": {"p50": round(_div(_bud, _cnv.get("p50", 0)), 2)},
        "revenue": {"p10": round(_rev.get("p10", 0)), "p50": round(_rev.get("p50", 0)),
                    "p90": round(_rev.get("p90", 0))},
        "roas": {"p10": round(_roas_b.get("p10", 0), 2), "p50": round(_roas_b.get("p50", 0), 2),
                 "p90": round(_roas_b.get("p90", 0), 2)},
        "roi_pct": {"p50": round(_roi_b.get("p50", 0) * 100, 0)},
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
        # Pillar B: when the frontend picked a calibration layer, that layer
        # — segment / platform / overall — replaces the generic "synthetic"
        # row so the user can see exactly what anchored their forecast.
        ({"label": "Calibration",
          "value": _calibration_provenance_value(
              req.calibration_source, req.calibration_n_ads, req.currency),
          "note": _calibration_provenance_note(
              req.calibration_source, req.calibration_n_ads, req.target_ctr,
              req.cpm_override, req.currency)}
         if req.calibration_source else
         {"label": "Calibration",
          "value": "synthetic CTR dataset (replaceable)",
          "note": "Psychology-rule weights fitted on a generated dataset, not your past performance. Upload your Meta/Google/LinkedIn CSV exports on the Data page to recalibrate against YOUR campaigns."}),
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
        "reel_quality": (result["reel_quality"].to_dict()
                         if result.get("reel_quality") is not None else None),
        "figures": figures,
        "validation": result["validation"],
        "headline_md": result["headline_md"],
        "visual_md": result["visual_md"],
        "narrative_md": result["narrative_md"],
        # New plain-English fields:
        "plain_verdict": {
            "headline": plain,
            "class": verdict_word,
            # Objective drives which hero card the report renders — the same
            # campaign read on different objectives now shows the right metric.
            "objective": objective,
            "lead": _lead,
            "roas_p50": round(roas, 2),
            "roi_p50_pct": round(mc_dict["predicted_roi"]["p50"] * 100, 0),
            "ctr_p50": round(sample_ctr, 5),
            "ctr_vs_bench_pct": round((sample_ctr - fmt_bench_ctr) / max(fmt_bench_ctr, 1e-6) * 100, 0),
            "cpm_p50": _cpm_kpi,
            "cpm_vs_bench_pct": round((_cpm_value - _bench_cpm) / max(_bench_cpm, 1e-6) * 100, 0),
            "reach_value": _reach_kpi,
            # Single source of truth — same value the headline's risk wording uses.
            "break_even_chance_pct": break_even_probability,
        },
        "factor_plain": factor_plain,
        "data_sources": data_sources,
        "economics": economics,
        "kpis": kpis,
        "viability": viability,
        "confidence": {
            "level": confidence,
            "blurb": confidence_blurb,
            "heuristic_count": heuristic_count,
        },
    }


# --------------------------------------------------------------------------
# Pillar B: calibration-provenance helpers (used by the data_sources block)
# --------------------------------------------------------------------------

_SEGMENT_LABEL = {
    "all":                 "all audiences",
    "gen_z":               "Gen Z",
    "millennials":         "Millennials",
    "gen_x":               "Gen X",
    "boomers":             "Boomers",
    "high_income":         "high-income",
    "budget_conscious":    "budget-conscious",
    "early_adopters":      "early adopters",
    "socially_influenced": "socially-influenced",
}

_PLATFORM_LABEL = {
    "meta_facebook":  "Meta / Facebook",
    "meta_instagram": "Meta / Instagram",
    "linkedin":       "LinkedIn",
    "tiktok":         "TikTok",
    "youtube":        "YouTube",
    "google_search":  "Google Search",
}

# Pillar B+: pretty labels for the interest taxonomy (mirrors the slugs in
# outcomes.INTEREST_BUCKETS so they stay in sync).
_INTEREST_LABEL = {
    "fitness": "fitness", "fashion": "fashion", "beauty": "beauty",
    "tech": "tech", "travel": "travel", "food": "food / drink",
    "home": "home / DIY", "finance": "finance", "automotive": "automotive",
    "entertainment": "entertainment", "business": "business / B2B",
    "wellness": "wellness",
}


def _parse_calibration_source(source: str | None) -> dict:
    """Split a calibration_source string into structured parts.

    Recognises:
      'segment:gen_z:interest:fitness' -> {kind:'segment_interest', seg, interest}
      'segment:gen_z'                  -> {kind:'segment', seg}
      'interest:fitness'               -> {kind:'interest', interest}
      'platform:meta_facebook'         -> {kind:'platform', plat}
      'overall'                        -> {kind:'overall'}
      ''/None                          -> {kind:'none'}
    """
    if not source:
        return {"kind": "none"}
    if source == "overall":
        return {"kind": "overall"}
    if source.startswith("segment:"):
        rest = source[len("segment:"):]
        if ":interest:" in rest:
            seg, interest = rest.split(":interest:", 1)
            return {"kind": "segment_interest", "seg": seg, "interest": interest}
        return {"kind": "segment", "seg": rest}
    if source.startswith("interest:"):
        return {"kind": "interest", "interest": source[len("interest:"):]}
    if source.startswith("platform:"):
        return {"kind": "platform", "plat": source[len("platform:"):]}
    return {"kind": "raw", "raw": source}


def _calibration_provenance_value(source: str | None,
                                  n_ads: int | None,
                                  currency: str) -> str:
    """Headline label for the calibration row.

    Examples: 'your Gen Z · fitness audience · 12 ads' / 'your Gen Z audience
    · 23 ads' / 'Meta/Facebook average · 41 ads' / 'your account average ·
    64 ads'. Purely descriptive of what the frontend selected.
    """
    parts = _parse_calibration_source(source)
    if parts["kind"] == "none":
        return "synthetic CTR dataset (replaceable)"
    n_str = f" · {n_ads} ads" if n_ads else ""
    if parts["kind"] == "segment_interest":
        seg = _SEGMENT_LABEL.get(parts["seg"], parts["seg"])
        interest = _INTEREST_LABEL.get(parts["interest"], parts["interest"])
        return f"your {seg} · {interest} audience{n_str}"
    if parts["kind"] == "segment":
        return f"your {_SEGMENT_LABEL.get(parts['seg'], parts['seg'])} audience{n_str}"
    if parts["kind"] == "interest":
        return f"your {_INTEREST_LABEL.get(parts['interest'], parts['interest'])} ads{n_str}"
    if parts["kind"] == "platform":
        return f"{_PLATFORM_LABEL.get(parts['plat'], parts['plat'])} average{n_str}"
    if parts["kind"] == "overall":
        return f"your account average{n_str}"
    return source or ""


def _calibration_provenance_note(source: str | None,
                                 n_ads: int | None,
                                 target_ctr: float | None,
                                 cpm_override: float | None,
                                 currency: str) -> str:
    """Plain-English explanation of which layer anchored the forecast."""
    parts = _parse_calibration_source(source)
    ctr_part = f"CTR anchor {target_ctr*100:.2f}%" if target_ctr else "CTR anchor unset"
    cpm_part = f"CPM anchor {currency} {cpm_override:.2f}" if cpm_override else "CPM anchor unset"
    nums = f" · {ctr_part}, {cpm_part}"
    if parts["kind"] == "none":
        return "No real-data calibration applied."
    if parts["kind"] == "segment_interest":
        seg = _SEGMENT_LABEL.get(parts["seg"], parts["seg"])
        interest = _INTEREST_LABEL.get(parts["interest"], parts["interest"])
        return (f"Tightest match — your uploaded ads for the '{seg}' audience "
                f"AND '{interest}' interest combined anchored the forecast.{nums}")
    if parts["kind"] == "segment":
        seg = _SEGMENT_LABEL.get(parts["seg"], parts["seg"])
        return (f"Your uploaded data didn't have enough rows for the chosen "
                f"audience + interest combination, so the forecast fell back "
                f"to your '{seg}' audience average across all interests.{nums}")
    if parts["kind"] == "interest":
        interest = _INTEREST_LABEL.get(parts["interest"], parts["interest"])
        return (f"Your uploaded data didn't tag audiences, but it did carry "
                f"interest hints, so the forecast was anchored to your "
                f"'{interest}' ads.{nums}")
    if parts["kind"] == "platform":
        plat = _PLATFORM_LABEL.get(parts["plat"], parts["plat"])
        return (f"Your uploaded data didn't have enough rows for this "
                f"audience or interest, so the forecast fell back to your "
                f"{plat} platform average.{nums}")
    if parts["kind"] == "overall":
        return (f"Your uploaded data didn't have enough rows for this "
                f"audience / interest / platform, so the forecast fell back "
                f"to your overall account average.{nums}")
    return f"Calibration source: {source}{nums}"


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
