"""Live ad-account connectors — pull a client's REAL ad performance into the
ad_outcomes shape AdProof calibrates from, so the credibility flywheel can run
on real data instead of CSV uploads.

Read-only by design: connectors only ever GET performance. No campaign writes
(AdProof is a scorer, not an ad manager).

Architecture: one module per provider, each exposing
    pull(credentials: dict, since: str, until: str) -> list[dict]   # ad_outcomes rows
    test(credentials: dict) -> dict                                 # {ok, detail}
plus a PROVIDERS registry describing what credentials each platform needs and
how gated its API access is — the UI renders connect cards straight from this,
so adding a platform is: write the module, add a registry entry, done.

Socivo's read connectors.
"""
from __future__ import annotations

# Every provider follows the same pattern Meta set: an auth credential (token /
# key set) + an account identifier. `fields` drives the connect form in the UI.
# `access` is honest about each platform's gate:
#   ready  — works today with credentials any account admin can self-serve
#   gated  — platform requires an application/approval before the API answers
PROVIDERS: dict[str, dict] = {
    "meta": {
        "label": "Meta (Facebook + Instagram)",
        "platforms": ["meta_facebook", "meta_instagram"],
        "access": "ready",
        "access_note": "Works now with a Graph API Explorer or System User token — your own ad account needs no App Review.",
        "sync": True,
        "fields": [
            {"key": "access_token", "label": "Access token", "secret": True,
             "placeholder": "EAAG…",
             "help_url": "https://developers.facebook.com/tools/explorer/"},
            {"key": "account_id", "label": "Ad account ID", "secret": False,
             "placeholder": "act_1234567890 (or just the digits)",
             "help_url": "https://adsmanager.facebook.com/"},
        ],
        "how_to": [
            "Open Graph API Explorer (developers.facebook.com/tools/explorer) and pick/create an app.",
            "Generate an access token with the ads_read and read_insights permissions.",
            "For an ongoing connection, mint a System User token in Business Settings instead (doesn't expire hourly).",
            "Ad account ID: Ads Manager → account dropdown top-left → the act_… number.",
        ],
    },
    "tiktok": {
        "label": "TikTok Ads",
        "platforms": ["tiktok"],
        "access": "ready",
        "access_note": "Register a developer app at business-api.tiktok.com (quick), authorize your advertiser account, paste the long-term access token.",
        "sync": True,
        "fields": [
            {"key": "access_token", "label": "Access token", "secret": True,
             "placeholder": "act.…",
             "help_url": "https://business-api.tiktok.com/portal"},
            {"key": "advertiser_id", "label": "Advertiser ID", "secret": False,
             "placeholder": "7012345678901234567",
             "help_url": "https://ads.tiktok.com/"},
        ],
        "how_to": [
            "Go to business-api.tiktok.com/portal → create a developer app (choose Ads Management, read scope).",
            "Authorize it against your TikTok Ads account — you'll get a long-term access token.",
            "Advertiser ID: TikTok Ads Manager → top-right account menu, the long number under the account name.",
        ],
    },
    "google": {
        "label": "Google Ads",
        "platforms": ["google_search"],
        "access": "gated",
        "access_note": "Needs a Google Ads developer token (apply from a manager/MCC account — days to weeks). Once you have it, this connector works.",
        "sync": True,
        "fields": [
            {"key": "developer_token", "label": "Developer token", "secret": True,
             "placeholder": "ABcdeFGh1jK…",
             "help_url": "https://developers.google.com/google-ads/api/docs/get-started/dev-token"},
            {"key": "access_token", "label": "OAuth access token", "secret": True,
             "placeholder": "ya29.…",
             "help_url": "https://developers.google.com/oauthplayground/"},
            {"key": "customer_id", "label": "Customer ID (10 digits)", "secret": False,
             "placeholder": "1234567890 (no dashes)",
             "help_url": "https://ads.google.com/"},
            {"key": "login_customer_id", "label": "Manager (MCC) ID — optional", "secret": False,
             "placeholder": "Only if the account sits under a manager account", "optional": True},
        ],
        "how_to": [
            "Create a free manager (MCC) account and link your ad account under it.",
            "In the MCC: Tools → API Center → apply for a developer token (Basic access).",
            "Get an OAuth access token with the https://www.googleapis.com/auth/adwords scope (OAuth Playground works for testing).",
            "Customer ID is the 10-digit number top-right in Google Ads — enter it without dashes.",
        ],
    },
    "linkedin": {
        "label": "LinkedIn Ads",
        "platforms": ["linkedin"],
        "access": "gated",
        "access_note": "LinkedIn's Marketing API needs partner-program approval (can take weeks–months). Apply early; use CSV export meanwhile.",
        "sync": True,
        "fields": [
            {"key": "access_token", "label": "Access token", "secret": True,
             "placeholder": "AQV…",
             "help_url": "https://learn.microsoft.com/linkedin/marketing/"},
            {"key": "account_id", "label": "Ad account ID (digits)", "secret": False,
             "placeholder": "512345678",
             "help_url": "https://www.linkedin.com/campaignmanager/"},
        ],
        "how_to": [
            "Apply for the LinkedIn Marketing API partner program (developer.linkedin.com) — this is the slow gate.",
            "Once approved, create an app, request the r_ads and r_ads_reporting scopes, and OAuth to get a token.",
            "Ad account ID: Campaign Manager URL contains it, or Account Settings → the numeric ID.",
        ],
    },
    "reddit": {
        "label": "Reddit Ads",
        "platforms": ["reddit"],
        "access": "ready",
        "access_note": "Reddit's Ads API is self-serve: create an app at ads.reddit.com developer settings, OAuth for a token. Similar effort to TikTok.",
        "sync": True,
        "fields": [
            {"key": "access_token", "label": "OAuth access token", "secret": True,
             "placeholder": "eyJhb…",
             "help_url": "https://ads-api.reddit.com/docs/"},
            {"key": "account_id", "label": "Ad account ID", "secret": False,
             "placeholder": "t2_… or a2_…",
             "help_url": "https://ads.reddit.com/"},
        ],
        "how_to": [
            "In Reddit Ads (ads.reddit.com): Settings → API access → create an app to get client credentials.",
            "OAuth with the adsread scope to get an access token.",
            "Ad account ID: shown in Reddit Ads account settings (starts a2_… on newer accounts).",
        ],
    },
    "x": {
        "label": "X (Twitter) Ads",
        "platforms": ["x_twitter"],
        "access": "gated",
        "access_note": "The most restrictive: needs an approved X developer account PLUS a separate Ads API access grant. We verify your credentials now; stats sync unlocks once X grants Ads API access.",
        "sync": False,   # connection verify only, until Ads API analytics wiring
        "fields": [
            {"key": "consumer_key", "label": "API key (consumer key)", "secret": True,
             "placeholder": "From your X developer app",
             "help_url": "https://developer.x.com/"},
            {"key": "consumer_secret", "label": "API key secret", "secret": True,
             "placeholder": "…"},
            {"key": "access_token", "label": "Access token", "secret": True,
             "placeholder": "…-…"},
            {"key": "access_token_secret", "label": "Access token secret", "secret": True,
             "placeholder": "…"},
            {"key": "account_id", "label": "Ads account ID", "secret": False,
             "placeholder": "18ce54… (from ads.x.com URL)",
             "help_url": "https://ads.x.com/"},
        ],
        "how_to": [
            "Get an X developer account (developer.x.com) and create an app — that yields the API key/secret + access token/secret.",
            "Separately apply for Ads API access for that app (X reviews this; it's tied to your ads account).",
            "Ads account ID: the hex-ish ID in the ads.x.com URL after /accounts/.",
        ],
    },
}

SUPPORTED = tuple(PROVIDERS.keys())

# Aliases so older callers ('facebook', 'google_ads', 'twitter'…) keep working.
_ALIASES = {
    "facebook": "meta", "instagram": "meta", "meta_facebook": "meta",
    "meta_instagram": "meta", "google_ads": "google", "google_search": "google",
    "twitter": "x", "x_twitter": "x",
}


def _canonical(provider: str) -> str:
    p = (provider or "").lower().strip()
    p = _ALIASES.get(p, p)
    if p not in PROVIDERS:
        raise ValueError(f"Unknown ad provider '{provider}'.")
    return p


def _module(provider: str):
    p = _canonical(provider)
    try:
        import importlib
        return importlib.import_module(f"connectors.{p}")
    except ImportError:
        import importlib
        return importlib.import_module(f"src.connectors.{p}")


def provider_meta() -> list[dict]:
    """Registry for the UI — everything except nothing secret lives here."""
    return [{"id": pid, **meta} for pid, meta in PROVIDERS.items()]


def pull_outcomes(provider: str, credentials: dict, since: str, until: str) -> list[dict]:
    """Return normalized ad_outcomes dicts for [since, until] ('YYYY-MM-DD')."""
    p = _canonical(provider)
    if not PROVIDERS[p]["sync"]:
        raise NotImplementedError(
            f"{PROVIDERS[p]['label']}: performance sync isn't unlocked yet "
            f"({PROVIDERS[p]['access_note']}) Connection testing works; use a "
            "CSV export for data meanwhile.")
    return _module(p).pull(credentials, since, until)


def test_connection(provider: str, credentials: dict) -> dict:
    """Verify credentials read-only. Returns {ok: bool, detail: str, ...}."""
    p = _canonical(provider)
    return _module(p).test(credentials)


def pull_breakdowns(provider: str, credentials: dict,
                    since: str, until: str) -> list[dict]:
    """Audience breakdown rows (age × gender per ad) for providers that
    support it. Returns [] rather than raising when a provider doesn't —
    breakdowns are an enrichment, never a reason to fail a sync."""
    p = _canonical(provider)
    mod = _module(p)
    fn = getattr(mod, "pull_breakdowns", None)
    if fn is None:
        return []
    return fn(credentials, since, until)
