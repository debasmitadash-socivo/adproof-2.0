"""Meta Marketing API connector — read-only ad-performance pull.

Pulls AD-level daily insights and maps them into the ad_outcomes shape the
calibration/backtest/fatigue pipeline consumes. Adapted, with permission, from
Socivo's Meta read scripts (client.py + get_campaign_performance.py).

We only ever GET insights — never write campaigns.
"""
from __future__ import annotations

import requests

_API_VERSION = "v22.0"
_BASE = f"https://graph.facebook.com/{_API_VERSION}"

# Meta nests conversions inside an `actions` array keyed by action_type. These
# are the types we treat as a conversion/lead; revenue comes from action_values.
_CONVERSION_ACTIONS = {
    "lead", "offsite_conversion.fb_pixel_lead", "onsite_conversion.lead_grouped",
    "complete_registration", "offsite_conversion.fb_pixel_complete_registration",
    "offsite_conversion.fb_pixel_purchase", "purchase", "omni_purchase",
}
_REVENUE_ACTIONS = {
    "offsite_conversion.fb_pixel_purchase", "purchase", "omni_purchase",
    "omni_purchase.value",
}


def _sum_actions(actions, types) -> float:
    if not actions:
        return 0.0
    total = 0.0
    for a in actions:
        if a.get("action_type") in types:
            try:
                total += float(a.get("value", 0) or 0)
            except (TypeError, ValueError):
                pass
    return total


def _platform_for(insight: dict) -> str:
    pub = str(insight.get("publisher_platform") or "").lower()
    if pub == "instagram":
        return "meta_instagram"
    if pub == "facebook":
        return "meta_facebook"
    return "meta_facebook"            # default bucket when not broken out


def _int(v) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _float(v):
    try:
        f = float(v)
        return f if f else None
    except (TypeError, ValueError):
        return None


def map_insights(insights: list[dict]) -> list[dict]:
    """Map Meta ad-level insight rows -> ad_outcomes dicts. Pure + testable."""
    rows: list[dict] = []
    for ins in insights or []:
        actions = ins.get("actions") or []
        action_values = ins.get("action_values") or []
        conv = _sum_actions(actions, _CONVERSION_ACTIONS)
        rev = _sum_actions(action_values, _REVENUE_ACTIONS)
        rows.append({
            "ad_name": ins.get("ad_name") or ins.get("campaign_name") or "Meta ad",
            "campaign_name": ins.get("campaign_name") or None,
            "adset_name": ins.get("adset_name") or None,
            "platform": _platform_for(ins),
            "date_start": ins.get("date_start"),
            "date_end": ins.get("date_stop"),
            "impressions": _int(ins.get("impressions")),
            "reach": _int(ins.get("reach")),
            "frequency": _float(ins.get("frequency")),
            "clicks": _int(ins.get("clicks")),
            "spend": float(ins.get("spend", 0) or 0),
            "conversions": conv or None,
            "revenue": rev or None,
        })
    return rows


def test(credentials: dict) -> dict:
    """Verify the token can read the ad account. Read-only, one GET."""
    token = (credentials.get("access_token") or "").strip()
    account_id = (credentials.get("account_id") or "").strip()
    if not token or not account_id:
        raise ValueError("Missing Meta access token or ad account ID.")
    acct = account_id if account_id.startswith("act_") else f"act_{account_id}"
    resp = requests.get(
        f"{_BASE}/{acct}",
        params={"access_token": token, "fields": "name,currency,account_status"},
        timeout=30)
    data = resp.json()
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        raise RuntimeError(f"Meta API error: {err.get('message', err)}")
    return {"ok": True,
            "detail": f"Connected to “{data.get('name', acct)}” "
                      f"({data.get('currency', '?')}).",
            "account_name": data.get("name"), "currency": data.get("currency")}


def search_interests(credentials: dict, query: str, limit: int = 25) -> list[dict]:
    """Live interest targeting search — the SAME options Meta's Ads Manager
    shows, straight from the Graph API (type=adinterest), with audience
    sizes. Powers AdProof's audience builder for Meta campaigns."""
    token = (credentials.get("access_token") or "").strip()
    if not token:
        raise ValueError("Missing Meta access token.")
    q = (query or "").strip()
    if len(q) < 2:
        return []
    resp = requests.get(
        f"{_BASE}/search",
        params={"type": "adinterest", "q": q, "limit": min(limit, 50),
                "access_token": token},
        timeout=30)
    data = resp.json()
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        raise RuntimeError(f"Meta API error: {err.get('message', err)}")
    out = []
    for it in data.get("data", []):
        out.append({
            "id": str(it.get("id", "")),
            "name": it.get("name", ""),
            "audience_size_lower": it.get("audience_size_lower_bound"),
            "audience_size_upper": it.get("audience_size_upper_bound"),
            "path": " › ".join(it.get("path") or []),
            "topic": it.get("topic") or None,
        })
    return out


def pull_breakdowns(credentials: dict, since: str, until: str,
                    *, timeout: int = 90) -> list[dict]:
    """WHO responded: ad-level insights broken down by age × gender,
    aggregated over the whole [since, until] window (no day grain — the
    audience read doesn't need it and the row count stays sane).

    Meta only allows certain breakdown combos in one call; age,gender is a
    valid pair. Placement (publisher_platform) can't join them, so platform
    here is the ad's default bucket, not a per-row split.
    """
    access_token = (credentials.get("access_token") or "").strip()
    account_id = (credentials.get("account_id") or "").strip()
    if not access_token:
        raise ValueError("Missing Meta access token.")
    acct = account_id if str(account_id).startswith("act_") else f"act_{account_id}"
    params: dict = {
        "access_token": access_token,
        "level": "ad",
        "fields": ("ad_id,ad_name,adset_name,campaign_name,impressions,"
                   "clicks,spend,actions,action_values"),
        "breakdowns": "age,gender",
        "time_range": f'{{"since":"{since}","until":"{until}"}}',
        "limit": 500,
    }
    url = f"{_BASE}/{acct}/insights"
    rows: list[dict] = []
    while url:
        resp = requests.get(url, params=params, timeout=timeout)
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            raise RuntimeError(f"Meta API error: {err.get('message', err)}")
        for ins in data.get("data", []):
            conv = _sum_actions(ins.get("actions") or [], _CONVERSION_ACTIONS)
            rev = _sum_actions(ins.get("action_values") or [], _REVENUE_ACTIONS)
            rows.append({
                "ad_name": ins.get("ad_name") or ins.get("campaign_name") or "Meta ad",
                "campaign_name": ins.get("campaign_name") or None,
                "adset_name": ins.get("adset_name") or None,
                "platform": _platform_for(ins),
                "age": str(ins.get("age") or "unknown"),
                "gender": str(ins.get("gender") or "unknown"),
                "impressions": _int(ins.get("impressions")),
                "clicks": _int(ins.get("clicks")),
                "spend": float(ins.get("spend", 0) or 0),
                "conversions": conv or None,
                "revenue": rev or None,
                "window_start": since,
                "window_end": until,
            })
        url = (data.get("paging") or {}).get("next")
        params = {}
    return rows


def pull(credentials: dict, since: str, until: str,
         *, breakdown_platform: bool = True, timeout: int = 60) -> list[dict]:
    """Pull AD-level daily insights for [since, until] (YYYY-MM-DD) and return
    ad_outcomes rows. ``account_id`` may be given with or without the act_ prefix.
    """
    access_token = (credentials.get("access_token") or "").strip()
    account_id = (credentials.get("account_id") or "").strip()
    if not access_token:
        raise ValueError("Missing Meta access token.")
    acct = account_id if str(account_id).startswith("act_") else f"act_{account_id}"
    fields = ("ad_id,ad_name,adset_name,campaign_name,impressions,reach,"
              "frequency,clicks,ctr,spend,cpm,cpc,actions,action_values,"
              "date_start,date_stop")
    params: dict = {
        "access_token": access_token,
        "level": "ad",
        "fields": fields,
        "time_increment": 1,
        "time_range": f'{{"since":"{since}","until":"{until}"}}',
        "limit": 500,
    }
    if breakdown_platform:
        params["breakdowns"] = "publisher_platform"

    url = f"{_BASE}/{acct}/insights"
    raw: list[dict] = []
    # Follow pagination; the `next` URL already carries the params.
    while url:
        resp = requests.get(url, params=params, timeout=timeout)
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            raise RuntimeError(f"Meta API error: {err.get('message', err)}")
        raw.extend(data.get("data", []))
        url = (data.get("paging") or {}).get("next")
        params = {}
    return map_insights(raw)
