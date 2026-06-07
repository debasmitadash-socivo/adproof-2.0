"""Live ad-account connectors — pull a client's REAL ad performance into the
ad_outcomes shape AdProof calibrates from, so the credibility flywheel can run
on real data instead of CSV uploads.

Read-only by design: connectors only ever GET performance. No campaign writes
(AdProof is a scorer, not an ad manager).

Adapted, with permission, from Ivan Falco's `ads-skills` read scripts.
"""
from __future__ import annotations

SUPPORTED = ("meta",)               # linkedin/google: scaffolded, wired next


def pull_outcomes(provider: str, access_token: str, account_id: str,
                  since: str, until: str) -> list[dict]:
    """Return a list of normalized ad_outcomes dicts for [since, until].

    provider: 'meta' (others raise NotImplementedError for now).
    since/until: 'YYYY-MM-DD'.
    """
    p = (provider or "").lower()
    if p in ("meta", "facebook", "instagram", "meta_facebook", "meta_instagram"):
        from connectors.meta import pull
        return pull(access_token, account_id, since, until)
    if p in ("linkedin",):
        raise NotImplementedError(
            "LinkedIn connector is scaffolded but not wired yet — Meta first.")
    if p in ("google", "google_ads"):
        raise NotImplementedError(
            "Google Ads connector needs a developer token (slow approval) — later.")
    raise ValueError(f"Unknown ad provider '{provider}'.")
