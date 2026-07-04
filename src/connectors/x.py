"""X (Twitter) Ads connector — connection verification via the X Ads API.

X is the most gated platform: it requires an approved developer account AND a
separate Ads API access grant for the app. Its auth is also the odd one out —
OAuth 1.0a request signing (four credentials), not a simple bearer token. We
implement the signing with the stdlib so verifying a connection works the
moment X grants access; performance sync is wired after that grant exists to
test against (the registry marks sync=False so the UI is honest about it).

We only ever GET — never write campaigns.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import urllib.parse

import requests

_BASE = "https://ads-api.x.com/12"


def _pct(s: str) -> str:
    return urllib.parse.quote(str(s), safe="~")


def _oauth1_header(method: str, url: str, credentials: dict,
                   query: dict | None = None) -> str:
    """Minimal OAuth 1.0a HMAC-SHA1 signature (stdlib only)."""
    oauth = {
        "oauth_consumer_key": (credentials.get("consumer_key") or "").strip(),
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": (credentials.get("access_token") or "").strip(),
        "oauth_version": "1.0",
    }
    all_params = {**(query or {}), **oauth}
    param_str = "&".join(
        f"{_pct(k)}={_pct(v)}" for k, v in sorted(all_params.items()))
    base = "&".join([method.upper(), _pct(url), _pct(param_str)])
    signing_key = (
        _pct((credentials.get("consumer_secret") or "").strip()) + "&" +
        _pct((credentials.get("access_token_secret") or "").strip()))
    sig = base64.b64encode(
        hmac.new(signing_key.encode(), base.encode(), hashlib.sha1).digest()
    ).decode()
    oauth["oauth_signature"] = sig
    return "OAuth " + ", ".join(
        f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth.items()))


def test(credentials: dict) -> dict:
    for k in ("consumer_key", "consumer_secret", "access_token",
              "access_token_secret", "account_id"):
        if not (credentials.get(k) or "").strip():
            raise ValueError(f"Missing X credential: {k.replace('_', ' ')}.")
    account_id = credentials["account_id"].strip()
    url = f"{_BASE}/accounts/{account_id}"
    resp = requests.get(
        url, headers={"Authorization": _oauth1_header("GET", url, credentials)},
        timeout=30)
    body = {}
    try:
        body = resp.json()
    except ValueError:
        pass
    if resp.status_code != 200:
        errs = body.get("errors") or []
        detail = (errs[0].get("message") if errs else None) or resp.text[:300]
        if resp.status_code in (401, 403):
            detail += (" — X requires a developer account plus a separate Ads "
                       "API access grant; until X approves that, this is the "
                       "expected failure.")
        raise RuntimeError(f"X Ads API error: {detail}")
    data = body.get("data") or {}
    name = data.get("name") or account_id
    return {"ok": True, "detail": f"Connected to “{name}”.",
            "account_name": name, "currency": None}


def pull(credentials: dict, since: str, until: str) -> list[dict]:
    raise NotImplementedError(
        "X Ads performance sync unlocks once X grants your app Ads API "
        "analytics access — connection verification works now; export a CSV "
        "from ads.x.com for data meanwhile.")
