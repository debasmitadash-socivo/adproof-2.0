"""LinkedIn Ads connector — read-only performance pull via the Marketing API
(adAnalytics). LinkedIn is the most gated of the majors: the Marketing API
requires partner-program approval before tokens get the r_ads_reporting scope.
Once approved, the credential pattern is the familiar token + account ID.

We only ever GET analytics — never write campaigns.
"""
from __future__ import annotations

import requests

_BASE = "https://api.linkedin.com/rest"
_VERSION = "202409"          # LinkedIn-Version header (YYYYMM)


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": _VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _creds(credentials: dict) -> tuple[str, str]:
    token = (credentials.get("access_token") or "").strip()
    account_id = (credentials.get("account_id") or "").strip()
    # Accept a raw URN or plain digits.
    account_id = account_id.replace("urn:li:sponsoredAccount:", "")
    if not token or not account_id:
        raise ValueError("Missing LinkedIn access token or ad account ID.")
    return token, account_id


def _raise_api_error(resp: requests.Response, what: str) -> None:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    detail = body.get("message") or resp.text[:300]
    if resp.status_code in (401, 403):
        detail += (" — LinkedIn's Marketing API needs partner-program approval; "
                   "if you haven't been approved yet this is the expected failure.")
    raise RuntimeError(f"LinkedIn API error ({what}): {detail}")


def test(credentials: dict) -> dict:
    token, account_id = _creds(credentials)
    resp = requests.get(f"{_BASE}/adAccounts/{account_id}",
                        headers=_headers(token), timeout=30)
    if resp.status_code != 200:
        _raise_api_error(resp, "adAccounts")
    data = resp.json()
    name = data.get("name") or account_id
    cur = data.get("currency")
    return {"ok": True,
            "detail": f"Connected to “{name}”{f' ({cur})' if cur else ''}.",
            "account_name": name, "currency": cur}


def _date_param(ymd: str, key: str) -> str:
    y, m, d = ymd.split("-")
    return f"{key}:(year:{int(y)},month:{int(m)},day:{int(d)})"


def pull(credentials: dict, since: str, until: str, *, timeout: int = 60) -> list[dict]:
    """Pull creative-level daily analytics for [since, until] -> ad_outcomes rows."""
    token, account_id = _creds(credentials)
    # Rest.li 2.0 URL syntax — parens/colons must go through unencoded.
    url = (
        f"{_BASE}/adAnalytics?q=analytics&pivot=CREATIVE&timeGranularity=DAILY"
        f"&dateRange=({_date_param(since, 'start')},{_date_param(until, 'end')})"
        f"&accounts=List(urn%3Ali%3AsponsoredAccount%3A{account_id})"
        "&fields=impressions,clicks,costInLocalCurrency,externalWebsiteConversions,"
        "dateRange,pivotValues"
    )
    resp = requests.get(url, headers=_headers(token), timeout=timeout)
    if resp.status_code != 200:
        _raise_api_error(resp, "adAnalytics")
    rows: list[dict] = []
    for el in resp.json().get("elements") or []:
        dr = (el.get("dateRange") or {}).get("start") or {}
        day = (f"{dr.get('year'):04d}-{dr.get('month'):02d}-{dr.get('day'):02d}"
               if dr.get("year") else None)
        pivots = el.get("pivotValues") or []
        name = str(pivots[0]).replace("urn:li:sponsoredCreative:", "Creative ") \
            if pivots else "LinkedIn ad"
        conv = float(el.get("externalWebsiteConversions", 0) or 0)
        rows.append({
            "ad_name": name,
            "platform": "linkedin",
            "date_start": day,
            "date_end": day,
            "impressions": int(el.get("impressions", 0) or 0),
            "clicks": int(el.get("clicks", 0) or 0),
            "spend": float(el.get("costInLocalCurrency", 0) or 0),
            "conversions": conv or None,
            "revenue": None,     # LinkedIn doesn't return revenue here
        })
    return rows
