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


def pull(access_token: str, account_id: str, since: str, until: str,
         *, breakdown_platform: bool = True, timeout: int = 60) -> list[dict]:
    """Pull AD-level daily insights for [since, until] (YYYY-MM-DD) and return
    ad_outcomes rows. ``account_id`` may be given with or without the act_ prefix.
    """
    if not access_token:
        raise ValueError("Missing Meta access token.")
    acct = account_id if str(account_id).startswith("act_") else f"act_{account_id}"
    fields = ("ad_id,ad_name,campaign_name,impressions,reach,frequency,clicks,"
              "ctr,spend,cpm,cpc,actions,action_values,date_start,date_stop")
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
