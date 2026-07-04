"""P3b — auction-layer parameters fitted from the account's OWN daily data.

Two market effects the flat CPM/fatigue constants ignore:

1. CPM seasonality — auction prices move with the calendar (Q4 e-commerce
   CPMs are famously higher). We fit per-month factors from the account's
   real spend/impressions history, shrunk toward 1.0 by sample size so one
   noisy month can't fabricate a trend.

2. Creative fatigue slope — how fast THIS account's CTR decays per extra
   exposure (frequency). Fitted as the cross-sectional slope of log-CTR vs
   frequency across ads. At paid-social CTRs (~1%), log ≈ logit, so the
   fitted slope maps directly onto the ABM's FATIGUE_PER_EXPOSURE logit
   constant (0.10 hand-written today).

Both are ESTIMATES with explicit usability gates — below the data floor we
return usable=False and the generic constants stay in charge. Pure pandas +
numpy; unit-tested in eval/ style via direct invocation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Shrinkage strength for monthly factors: a month with K_MONTH ads is
# trusted 50/50 against "no seasonal effect" (factor 1.0).
K_MONTH = 6

# Gates.
MIN_ADS_SEASONALITY = 12
MIN_MONTHS_SEASONALITY = 2
MIN_ADS_FATIGUE = 8

# Plausibility clamps.
FACTOR_LO, FACTOR_HI = 0.6, 1.8          # a month can't triple or crater CPM
LAMBDA_LO, LAMBDA_HI = 0.0, 0.35         # per-exposure logit decay bounds


def fit_cpm_seasonality(df: pd.DataFrame) -> dict:
    """Per-month CPM factors (month mean / overall mean), shrunk toward 1.

    Needs date_start + spend + impressions. factors[m] > 1 means that month
    is more expensive than the account's average.
    """
    out = {"usable": False, "factors": {}, "n_ads": 0, "months_covered": 0,
           "reason": None}
    if df is None or df.empty or not {"date_start", "spend", "impressions"} \
            .issubset(df.columns):
        out["reason"] = "Needs dated rows with spend + impressions."
        return out

    d = df.copy()
    d["spend"] = pd.to_numeric(d["spend"], errors="coerce")
    d["impressions"] = pd.to_numeric(d["impressions"], errors="coerce")
    d = d[(d["spend"] > 0) & (d["impressions"] > 0)]
    d["month"] = pd.to_datetime(d["date_start"], errors="coerce").dt.month
    d = d.dropna(subset=["month"])
    if len(d) < MIN_ADS_SEASONALITY:
        out["reason"] = (f"Needs ≥{MIN_ADS_SEASONALITY} dated ads with spend "
                         f"(have {len(d)}).")
        return out

    # Spend-weighted CPMs: overall + per month.
    overall_cpm = d["spend"].sum() / d["impressions"].sum() * 1000
    if not np.isfinite(overall_cpm) or overall_cpm <= 0:
        out["reason"] = "Couldn't compute a baseline CPM."
        return out

    months = 0
    for m, grp in d.groupby("month"):
        n = int(len(grp))
        month_cpm = grp["spend"].sum() / grp["impressions"].sum() * 1000
        raw = month_cpm / overall_cpm
        # Shrink toward 1.0 by sample size, then clamp to plausibility.
        shrunk = (n * raw + K_MONTH * 1.0) / (n + K_MONTH)
        out["factors"][int(m)] = float(np.clip(shrunk, FACTOR_LO, FACTOR_HI))
        months += 1

    out["n_ads"] = int(len(d))
    out["months_covered"] = months
    if months < MIN_MONTHS_SEASONALITY:
        out["reason"] = (f"Needs data across ≥{MIN_MONTHS_SEASONALITY} "
                         f"months (have {months}).")
        return out
    out["usable"] = True
    return out


def fit_fatigue_lambda(df: pd.DataFrame) -> dict:
    """Account-level fatigue slope: log-CTR decay per unit frequency.

    Cross-sectional least-squares over ads with frequency data: slope of
    ln(ctr) on frequency. Positive lambda = CTR decays with repeat exposure
    (the normal case). Clamped to [0, 0.35]; negative slopes (CTR *rising*
    with frequency — usually confounding) floor at 0 = "no measured fatigue".
    """
    out = {"usable": False, "lambda_per_exposure": None, "n_ads": 0,
           "reason": None}
    if df is None or df.empty:
        out["reason"] = "No rows."
        return out
    cols = set(df.columns)
    if "frequency" not in cols or not {"clicks", "impressions"}.issubset(cols):
        out["reason"] = "Needs frequency + clicks/impressions columns."
        return out

    d = df.copy()
    for c in ("frequency", "clicks", "impressions"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[(d["impressions"] > 0) & (d["clicks"] >= 0) & (d["frequency"] > 0)]
    d["ctr"] = d["clicks"] / d["impressions"]
    d = d[d["ctr"] > 0]
    # Fatigue is only identifiable with frequency VARIATION.
    if len(d) < MIN_ADS_FATIGUE or d["frequency"].nunique() < 3:
        out["reason"] = (f"Needs ≥{MIN_ADS_FATIGUE} ads with varied "
                         f"frequency (have {len(d)}).")
        return out

    x = d["frequency"].to_numpy(dtype=float)
    y = np.log(d["ctr"].to_numpy(dtype=float))
    # Least-squares slope; guard the degenerate zero-variance case.
    vx = float(np.var(x))
    if vx <= 1e-12:
        out["reason"] = "No frequency variation."
        return out
    slope = float(np.cov(x, y, bias=True)[0, 1] / vx)
    lam = float(np.clip(-slope, LAMBDA_LO, LAMBDA_HI))
    out["lambda_per_exposure"] = lam
    out["n_ads"] = int(len(d))
    out["usable"] = True
    return out


def auction_block(df: pd.DataFrame) -> dict:
    """The `auction` block attached to every calibration result."""
    return {
        "cpm_seasonality": fit_cpm_seasonality(df),
        "fatigue": fit_fatigue_lambda(df),
    }
