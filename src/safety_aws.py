"""Opt-in second ban-screen for image creatives using AWS Rekognition.

Gemini already screens for ban-risk in the existing visual_analysis pipeline.
This module adds an *independent* second pair of eyes — AWS Rekognition's
specialised content-moderation model — so a creative has to clear BOTH to be
considered safe. If AWS isn't configured (no keys in env), this silently
skips; the run continues on Gemini's screen alone.

Why a second screener? Different models find different things. Rekognition
is purpose-built for moderation and stronger than a general LLM on edge cases
(suggestive content, weapons, drug paraphernalia). Belt + braces for a
product whose whole pitch is "will this get my account banned?"

Scope: IMAGES today (Rekognition Image is synchronous and dead simple).
Videos would need Rekognition Video (async, requires S3 staging) — a
sensible follow-up; deliberately not done here to keep the dependency
surface small.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

__all__ = ["aws_configured", "screen_image_aws"]


def aws_configured() -> bool:
    """True iff an AWS access key + secret are present in env."""
    return bool(os.environ.get("AWS_ACCESS_KEY_ID")
                and os.environ.get("AWS_SECRET_ACCESS_KEY"))


def _level_from_confidence(c: float) -> str:
    if c >= 90: return "high"
    if c >= 70: return "medium"
    if c >= 50: return "low"
    return "none"


def screen_image_aws(image_path: str | Path,
                     min_confidence: float = 50.0) -> dict[str, Any] | None:
    """Run Rekognition Image moderation. Returns the same ban_risk shape we
    use for Gemini ({level, flags, explanation}). Returns None when AWS isn't
    configured OR Rekognition couldn't be reached — the caller treats None as
    "no second opinion available" rather than as a clean pass.
    """
    if not aws_configured():
        return None
    try:
        import boto3                                                # type: ignore
    except ImportError:
        return None
    p = Path(image_path)
    if not p.exists() or p.stat().st_size == 0:
        return None
    region = os.environ.get("AWS_REGION", "us-east-1")
    try:
        client = boto3.client(
            "rekognition", region_name=region,
            aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        )
        resp = client.detect_moderation_labels(
            Image={"Bytes": p.read_bytes()},
            MinConfidence=float(min_confidence),
        )
    except Exception:  # noqa: BLE001 — never crash the run on AWS failure
        return None

    labels = resp.get("ModerationLabels", []) or []
    if not labels:
        return {"level": "none", "flags": [],
                "explanation": "AWS Rekognition: no policy-flagged content detected.",
                "provider": "aws_rekognition"}
    # Highest-confidence label drives the level.
    top = max(labels, key=lambda x: float(x.get("Confidence", 0.0)))
    level = _level_from_confidence(float(top.get("Confidence", 0.0)))
    flags = sorted({str(l.get("Name", "")) for l in labels if l.get("Name")})
    parents = sorted({str(l.get("ParentName", "")) for l in labels if l.get("ParentName")})
    detail = ", ".join(parents) if parents else ", ".join(flags)
    return {
        "level": level, "flags": flags,
        "explanation": (f"AWS Rekognition flagged: {detail} "
                        f"(top: {top.get('Name')} {top.get('Confidence'):.0f}%)."),
        "provider": "aws_rekognition",
    }


def merge_ban_risk(primary: dict[str, Any] | None,
                   secondary: dict[str, Any] | None) -> dict[str, Any]:
    """Combine two ban_risk reports into one — take the more severe level,
    union the flags, keep both explanations so the user can see why each
    raised concern."""
    if not primary and not secondary:
        return {"level": "unknown", "flags": [], "explanation": ""}
    if not secondary: return primary  # type: ignore[return-value]
    if not primary:   return secondary
    order = {"none": 0, "low": 1, "medium": 2, "high": 3, "unknown": -1}
    p_lvl, s_lvl = str(primary.get("level", "")), str(secondary.get("level", ""))
    worse = primary if order.get(p_lvl, -1) >= order.get(s_lvl, -1) else secondary
    flags = sorted(set(list(primary.get("flags", [])) + list(secondary.get("flags", []))))
    expl = " · ".join(x for x in (primary.get("explanation"), secondary.get("explanation")) if x)
    return {
        "level": worse.get("level", "unknown"),
        "flags": flags,
        "explanation": expl,
        "sources": [primary.get("provider", "gemini"), secondary.get("provider", "aws_rekognition")],
    }
