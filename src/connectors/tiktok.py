"""TikTok Ads connector — read-only ad-performance pull via the TikTok
Business API (business-api.tiktok.com). Credential model mirrors Meta's:
a long-term access token + the advertiser (account) ID.

We only ever GET reports — never write campaigns.
"""
from __future__ import annotations

import json

import requests

_BASE = "https://business-api.tiktok.com/open_api/v1.3"


def _headers(token: str) -> dict:
    return {"Access-Token": token, "Content-Type": "application/json"}


def _check(data: dict, what: str) -> dict:
    # TikTok wraps every response as {code, message, data}; code 0 = OK.
    if not isinstance(data, dict):
        raise RuntimeError(f"TikTok API returned an unexpected {what} response.")
    if data.get("code") not in (0, "0", None):
        raise RuntimeError(f"TikTok API error: {data.get('message', data.get('code'))}")
    return data.get("data") or {}


def test(credentials: dict) -> dict:
    token = (credentials.get("access_token") or "").strip()
    adv = (credentials.get("advertiser_id") or "").strip()
    if not token or not adv:
        raise ValueError("Missing TikTok access token or advertiser ID.")
    resp = requests.get(
        f"{_BASE}/advertiser/info/",
        params={"advertiser_ids": json.dumps([adv])},
        headers=_headers(token), timeout=30)
    data = _check(resp.json(), "advertiser info")
    infos = data.get("list") or []
    name = (infos[0].get("name") if infos else None) or adv
    cur = infos[0].get("currency") if infos else None
    return {"ok": True,
            "detail": f"Connected to “{name}”{f' ({cur})' if cur else ''}.",
            "account_name": name, "currency": cur}


def _int(v) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def pull(credentials: dict, since: str, until: str, *, timeout: int = 60) -> list[dict]:
    """Pull AD-level daily metrics for [since, until] -> ad_outcomes rows."""
    token = (credentials.get("access_token") or "").strip()
    adv = (credentials.get("advertiser_id") or "").strip()
    if not token or not adv:
        raise ValueError("Missing TikTok access token or advertiser ID.")

    rows: list[dict] = []
    page = 1
    while True:
        params = {
            "advertiser_id": adv,
            "report_type": "BASIC",
            "data_level": "AUCTION_AD",
            "dimensions": json.dumps(["ad_id", "stat_time_day"]),
            "metrics": json.dumps([
                "ad_name", "campaign_name", "spend", "impressions",
                "clicks", "conversion", "total_purchase_value",
            ]),
            "start_date": since,
            "end_date": until,
            "page": page,
            "page_size": 1000,
        }
        resp = requests.get(f"{_BASE}/report/integrated/get/",
                            params=params, headers=_headers(token), timeout=timeout)
        data = _check(resp.json(), "report")
        for item in data.get("list") or []:
            m = item.get("metrics") or {}
            d = item.get("dimensions") or {}
            day = str(d.get("stat_time_day") or "")[:10] or None
            rev = m.get("total_purchase_value")
            try:
                rev = float(rev) if rev not in (None, "", "-") else None
            except (TypeError, ValueError):
                rev = None
            rows.append({
                "ad_name": m.get("ad_name") or m.get("campaign_name") or "TikTok ad",
                "platform": "tiktok",
                "date_start": day,
                "date_end": day,
                "impressions": _int(m.get("impressions")),
                "clicks": _int(m.get("clicks")),
                "spend": float(m.get("spend", 0) or 0),
                "conversions": float(m.get("conversion", 0) or 0) or None,
                "revenue": rev or None,
            })
        page_info = data.get("page_info") or {}
        if page >= int(page_info.get("total_page", 1) or 1):
            break
        page += 1
    return rows
