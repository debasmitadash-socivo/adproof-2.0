"""Cited industry conversion-rate priors — the honest fallback when a
workspace has no real conversion data yet.

The forecast's old behaviour was a silent 2.5% post-click CVR for every
business on earth. These ranges replace that false precision with an
explicit, cited scenario band: ROAS is presented as "X–Y× if your conversion
rate is in the typical range for your goal", until the account's own data
tightens it.

Ranges are deliberately WIDE — they're honesty bands, not predictions. Keyed
by the company's conversion goal first, business model second. Sources are
public benchmark publications; each range names the one it leans on so the
UI can show receipts.
"""
from __future__ import annotations

# (low, high) are post-click conversion-rate fractions.
_BY_GOAL: dict[str, dict] = {
    "purchase": {
        "low": 0.010, "high": 0.030,
        "source": "Shopify / Littledata e-commerce conversion benchmarks "
                  "(median store CVR ≈ 1.4%, top quartile ≈ 3%+)",
    },
    "lead": {
        "low": 0.030, "high": 0.090,
        "source": "WordStream / LocaliQ paid-social & search benchmarks "
                  "(lead-gen conversion typically 3–9% by industry)",
    },
    "demo": {
        "low": 0.010, "high": 0.040,
        "source": "B2B SaaS demo-request benchmarks (First Page Sage / "
                  "HubSpot; typically 1–4% of clicks book)",
    },
    "signup": {
        "low": 0.030, "high": 0.100,
        "source": "Free-trial / registration benchmarks (Unbounce / HubSpot "
                  "landing-page studies; typically 3–10%)",
    },
}

_BY_MODEL: dict[str, dict] = {
    "b2b": {
        "low": 0.015, "high": 0.050,
        "source": "B2B paid-media benchmarks (LocaliQ / First Page Sage)",
    },
    "saas": {
        "low": 0.015, "high": 0.050,
        "source": "SaaS paid-media benchmarks (First Page Sage)",
    },
    # b2c / dtc / marketplace all behave like transactional e-commerce.
    "default": {
        "low": 0.010, "high": 0.035,
        "source": "Cross-industry paid-social benchmarks (WordStream / "
                  "Littledata; most transactional accounts land 1–3.5%)",
    },
}


def cvr_prior(conversion_goal: str | None, business_model: str | None) -> dict:
    """Return {'low','high','source'} — the cited CVR range for this business.

    Goal is the stronger signal (a purchase and a newsletter signup convert
    at wildly different rates); business model is the fallback.
    """
    goal = (conversion_goal or "").strip().lower()
    if goal in _BY_GOAL:
        return dict(_BY_GOAL[goal])
    model = (business_model or "").strip().lower()
    for key in ("b2b", "saas"):
        if key in model:
            return dict(_BY_MODEL[key])
    return dict(_BY_MODEL["default"])
