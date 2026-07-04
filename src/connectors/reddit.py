"""Reddit Ads connector — read-only performance pull via the Reddit Ads API
(ads-api.reddit.com, v3). Self-serve access: create an app in Reddit Ads
developer settings, OAuth with the adsread scope. Credential pattern matches
Meta's: bearer token + ad account ID.

Money note: Reddit reports spend in MICRO-currency (millionths) — we divide.
We only ever read reports — never write campaigns.
"""
from __future__ import annotations

import requests

_BASE = "https://ads-api.reddit.com/api/v3"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _creds(credentials: dict) -> tuple[str, str]:
    token = (credentials.get("access_token") or "").strip()
    account_id = (credentials.get("account_id") or "").strip()
    if not token or not account_id:
        raise ValueError("Missing Reddit access token or ad account ID.")
    return token, account_id


def _raise_api_error(resp: requests.Response, what: str) -> None:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    detail = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) \
        else body.get("message") or resp.text[:300]
    raise RuntimeError(f"Reddit Ads API error ({what}): {detail}")


def test(credentials: dict) -> dict:
    token, account_id = _creds(credentials)
    resp = requests.get(f"{_BASE}/ad_accounts/{account_id}",
                        headers=_headers(token), timeout=30)
    if resp.status_code != 200:
        _raise_api_error(resp, "ad_accounts")
    data = (resp.json() or {}).get("data") or {}
    name = data.get("name") or account_id
    cur = data.get("currency")
    return {"ok": True,
            "detail": f"Connected to “{name}”{f' ({cur})' if cur else ''}.",
            "account_name": name, "currency": cur}


def pull(credentials: dict, since: str, until: str, *, timeout: int = 60) -> list[dict]:
    """Pull ad-level daily metrics for [since, until] -> ad_outcomes rows."""
    token, account_id = _creds(credentials)
    body = {
        "data": {
            "breakdowns": ["AD_ID", "DATE"],
            "fields": ["SPEND", "IMPRESSIONS", "CLICKS"],
            "starts_at": f"{since}T00:00:00Z",
            "ends_at": f"{until}T23:59:59Z",
            "time_zone_id": "GMT",
        }
    }
    resp = requests.post(f"{_BASE}/ad_accounts/{account_id}/reports",
                         headers=_headers(token), json=body, timeout=timeout)
    if resp.status_code not in (200, 201):
        _raise_api_error(resp, "reports")
    payload = (resp.json() or {}).get("data") or {}
    metrics = payload.get("metrics") or payload.get("rows") or []
    rows: list[dict] = []
    for m in metrics:
        day = str(m.get("date") or m.get("DATE") or "")[:10] or None
        spend_micro = float(m.get("spend", m.get("SPEND", 0)) or 0)
        rows.append({
            "ad_name": str(m.get("ad_id") or m.get("AD_ID") or "Reddit ad"),
            "platform": "reddit",
            "date_start": day,
            "date_end": day,
            "impressions": int(m.get("impressions", m.get("IMPRESSIONS", 0)) or 0),
            "clicks": int(m.get("clicks", m.get("CLICKS", 0)) or 0),
            "spend": spend_micro / 1e6,     # micro-currency -> currency
            "conversions": None,
            "revenue": None,
        })
    return rows
