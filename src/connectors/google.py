"""Google Ads connector — read-only performance pull via the Google Ads REST
API (searchStream + GAQL). Google's twist on the credential pattern is a THIRD
credential nobody expects: a developer token (applied for from a manager/MCC
account) on top of OAuth. Once the user has one, this works over plain REST —
no client library needed.

We only ever SELECT metrics — never mutate campaigns.
"""
from __future__ import annotations

import requests

_VERSION = "v18"
_BASE = f"https://googleads.googleapis.com/{_VERSION}"


def _headers(credentials: dict) -> dict:
    h = {
        "Authorization": f"Bearer {(credentials.get('access_token') or '').strip()}",
        "developer-token": (credentials.get("developer_token") or "").strip(),
        "Content-Type": "application/json",
    }
    login = (credentials.get("login_customer_id") or "").replace("-", "").strip()
    if login:
        h["login-customer-id"] = login
    return h


def _customer_id(credentials: dict) -> str:
    cid = (credentials.get("customer_id") or "").replace("-", "").strip()
    if not cid:
        raise ValueError("Missing Google Ads customer ID.")
    return cid


def _raise_api_error(resp: requests.Response, what: str) -> None:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    # searchStream errors arrive as a list; single calls as a dict.
    err = (body[0] if isinstance(body, list) and body else body) or {}
    detail = (err.get("error") or {}).get("message") or resp.text[:300]
    raise RuntimeError(f"Google Ads API error ({what}): {detail}")


def _search(credentials: dict, query: str, timeout: int = 60) -> list[dict]:
    cid = _customer_id(credentials)
    resp = requests.post(
        f"{_BASE}/customers/{cid}/googleAds:searchStream",
        headers=_headers(credentials), json={"query": query}, timeout=timeout)
    if resp.status_code != 200:
        _raise_api_error(resp, "searchStream")
    chunks = resp.json()
    results: list[dict] = []
    for chunk in chunks if isinstance(chunks, list) else [chunks]:
        results.extend(chunk.get("results") or [])
    return results


def test(credentials: dict) -> dict:
    if not (credentials.get("access_token") or "").strip():
        raise ValueError("Missing Google OAuth access token.")
    if not (credentials.get("developer_token") or "").strip():
        raise ValueError("Missing Google Ads developer token.")
    rows = _search(credentials,
                   "SELECT customer.descriptive_name, customer.currency_code "
                   "FROM customer LIMIT 1", timeout=30)
    cust = (rows[0].get("customer") if rows else {}) or {}
    name = cust.get("descriptiveName") or _customer_id(credentials)
    cur = cust.get("currencyCode")
    return {"ok": True,
            "detail": f"Connected to “{name}”{f' ({cur})' if cur else ''}.",
            "account_name": name, "currency": cur}


def pull(credentials: dict, since: str, until: str, *, timeout: int = 90) -> list[dict]:
    """Pull ad-level daily metrics for [since, until] -> ad_outcomes rows."""
    query = (
        "SELECT ad_group_ad.ad.id, ad_group_ad.ad.name, campaign.name, "
        "metrics.impressions, metrics.clicks, metrics.cost_micros, "
        "metrics.conversions, metrics.conversions_value, segments.date "
        "FROM ad_group_ad "
        f"WHERE segments.date BETWEEN '{since}' AND '{until}'"
    )
    rows: list[dict] = []
    for r in _search(credentials, query, timeout=timeout):
        m = r.get("metrics") or {}
        ad = (r.get("adGroupAd") or {}).get("ad") or {}
        seg = r.get("segments") or {}
        day = seg.get("date")
        conv = float(m.get("conversions", 0) or 0)
        rev = float(m.get("conversionsValue", 0) or 0)
        rows.append({
            "ad_name": ad.get("name") or (r.get("campaign") or {}).get("name") or "Google ad",
            "platform": "google_search",
            "date_start": day,
            "date_end": day,
            "impressions": int(m.get("impressions", 0) or 0),
            "clicks": int(m.get("clicks", 0) or 0),
            "spend": float(m.get("costMicros", 0) or 0) / 1e6,
            "conversions": conv or None,
            "revenue": rev or None,
        })
    return rows
