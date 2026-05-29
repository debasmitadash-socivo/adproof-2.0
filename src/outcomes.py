"""Ingest real ad-performance exports and calibrate per-account benchmarks.

This is Path B, part 1. A client's past ad results (Meta / Google / our
template) are the ground truth that turns the forecast from a generic guess
into something tuned to THEIR account — and, later, something we can backtest.

Real exports are messy: title rows above the header, currency baked into a
column name ("Amount spent (CAD)"), "Link clicks" vs "Clicks (all)", a
"Result type" text column with no result COUNT, often no revenue column at
all. This module is deliberately defensive: it finds the header row, maps
columns by synonym, coerces numerics, derives what it can, and is honest
about what's missing.

Output is intentionally split:
  * normalize_export()  -> clean rows in our schema + a mapping/▲warnings report
  * calibrate()         -> per-platform real CTR / CPM / CPC (+ CVR/ROAS where
                           the data exists), weighted by impressions, with a
                           confidence read.

Nothing here touches the database — the API layer persists the result against
the logged-in user (RLS), so per-account data never leaks into a global prior.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

__all__ = ["normalize_export", "calibrate", "ingest_and_calibrate", "CANONICAL_FIELDS"]

# Canonical schema -> list of source-column synonyms (matched case-insensitively
# as a normalised substring, longest/most-specific first).
CANONICAL_FIELDS: dict[str, list[str]] = {
    "ad_name":       ["ad name", "ad", "creative name"],
    "campaign":      ["campaign name", "campaign"],
    "platform":      ["platform", "publisher platform"],
    "placement":     ["placement", "position"],
    "spend":         ["amount spent", "spend", "cost", "total spent"],
    "impressions":   ["impressions", "impr."],
    "reach":         ["reach"],
    "clicks":        ["link clicks", "clicks (all)", "clicks", "link click"],
    "ctr_reported":  ["ctr (all)", "ctr (link click-through rate)", "ctr (link)", "ctr"],
    "cpc_reported":  ["cpc (cost per link click)", "cpc (all)", "cpc", "cost per click"],
    # NB: bare "result" is intentionally excluded — it would wrongly grab the
    # text "Result type" column. "Cost per result" is mapped separately below.
    "conversions":   ["results", "purchases", "conversions", "website purchases",
                      "leads"],
    "result_type":   ["result type", "result indicator"],
    "cost_per_result": ["cost per result", "cost per result type"],
    "revenue":       ["purchase conversion value", "conversion value",
                      "purchases conversion value", "revenue", "total conversion value"],
    "currency":      ["currency"],
    "date_start":    ["reporting starts", "day", "date start", "starts", "week"],
    "date_end":      ["reporting ends", "date end", "ends"],
    "objective":     ["objective"],
    "ad_copy":       ["body", "primary text", "ad copy", "title", "headline"],
    "test_group":    ["test group", "test_group", "experiment"],
}

# Header synonyms we scan for when locating the header row under title rows.
_HEADER_HINTS = {"ad name", "campaign name", "impressions", "amount spent",
                 "link clicks", "reach", "placement"}

_NUMERIC_FIELDS = {"spend", "impressions", "reach", "clicks", "ctr_reported",
                   "cpc_reported", "conversions", "cost_per_result", "revenue"}


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _find_header_row(raw: pd.DataFrame, scan: int = 12) -> int:
    """Return the row index whose cells best match known header names."""
    best_i, best_hits = 0, 0
    for i in range(min(scan, len(raw))):
        cells = {_norm(x) for x in raw.iloc[i].tolist()}
        hits = sum(1 for h in _HEADER_HINTS
                   if any(h in c for c in cells if c and c != "nan"))
        if hits > best_hits:
            best_i, best_hits = i, hits
    return best_i


def _pick_sheet(xls: pd.ExcelFile) -> str:
    """Prefer a raw-data / creative-reporting sheet over a formatted one."""
    pref = ["raw data", "creative reporting", "raw", "data", "report"]
    names = xls.sheet_names
    for p in pref:
        for n in names:
            if p in _norm(n):
                return n
    return names[0]


def _map_columns(cols: list[str]) -> dict[str, str]:
    """Map canonical field -> actual source column name (first/best match)."""
    normed = {c: _norm(c) for c in cols}
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for field_name, synonyms in CANONICAL_FIELDS.items():
        for syn in synonyms:                       # synonyms are priority-ordered
            match = None
            # exact normalised match first, then substring
            for col, ncol in normed.items():
                if col in used:
                    continue
                if ncol == syn:
                    match = col
                    break
            if match is None:
                for col, ncol in normed.items():
                    if col in used:
                        continue
                    if syn in ncol:
                        match = col
                        break
            if match is not None:
                mapping[field_name] = match
                used.add(match)
                break
    return mapping


def _to_num(series: pd.Series) -> pd.Series:
    """Coerce a money/number column to float, stripping symbols and commas."""
    if series.dtype.kind in "if":
        return series.astype(float)
    cleaned = (series.astype(str)
               .str.replace(r"[^0-9.\-]", "", regex=True)
               .replace({"": np.nan, "-": np.nan}))
    return pd.to_numeric(cleaned, errors="coerce")


def _detect_currency(df: pd.DataFrame, mapping: dict[str, str], cols: list[str]) -> str:
    if "currency" in mapping:
        vals = df[mapping["currency"]].dropna().astype(str)
        if len(vals):
            return vals.mode().iloc[0].upper()[:3]
    # else parse from a "amount spent (XXX)" column name
    if "spend" in mapping:
        m = re.search(r"\(([a-z]{3})\)", mapping["spend"].lower())
        if m:
            return m.group(1).upper()
    return "GBP"


@dataclass
class NormalizeReport:
    n_rows_in: int
    n_rows_kept: int
    currency: str
    mapped: dict          # canonical -> source column
    missing: list         # canonical fields we couldn't find
    warnings: list
    sheet: str | None = None


def normalize_export(data: bytes | str, filename: str = "") -> tuple[pd.DataFrame, NormalizeReport]:
    """Parse a Meta/Google/template export into our canonical row schema.

    `data` may be raw bytes (an upload) or a filesystem path. Returns the clean
    DataFrame plus a report of what was mapped / missing.
    """
    is_csv = filename.lower().endswith(".csv")
    buf: Any = io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data
    warnings: list[str] = []
    sheet_name: str | None = None

    if is_csv:
        raw = pd.read_csv(buf, header=None, dtype=str)
    else:
        xls = pd.ExcelFile(buf)
        sheet_name = _pick_sheet(xls)
        raw = pd.read_excel(xls, sheet_name=sheet_name, header=None, dtype=str)

    hdr = _find_header_row(raw)
    header = [str(x) for x in raw.iloc[hdr].tolist()]
    df = raw.iloc[hdr + 1:].copy()
    df.columns = header
    df = df.loc[:, [c for c in df.columns if c and c.lower() != "nan"]]

    mapping = _map_columns(list(df.columns))
    out = pd.DataFrame()
    for field_name, src in mapping.items():
        col = df[src]
        out[field_name] = _to_num(col) if field_name in _NUMERIC_FIELDS else col.astype(str).str.strip()

    currency = _detect_currency(df, mapping, list(df.columns))
    n_in = len(out)

    # Drop summary/total rows: need a real ad name + real impressions.
    if "ad_name" in out:
        out = out[out["ad_name"].notna()
                  & ~out["ad_name"].str.lower().isin(["all", "nan", "", "total"])]
    if "impressions" in out:
        out = out[_to_num(out["impressions"]).fillna(0) > 0]

    # Derive metrics that aren't present.
    if "impressions" in out and "clicks" in out:
        out["real_ctr"] = out["clicks"] / out["impressions"].replace(0, np.nan)
    if "impressions" in out and "spend" in out:
        out["real_cpm"] = out["spend"] / out["impressions"].replace(0, np.nan) * 1000
    if "clicks" in out and "spend" in out:
        out["real_cpc"] = out["spend"] / out["clicks"].replace(0, np.nan)
    # Conversion rate ONLY from a genuine results/purchases count. We do NOT
    # derive it from "cost per result": Meta's "result" is whatever the campaign
    # optimised for (reach, engagement, video views…), so that count routinely
    # exceeds clicks and is meaningless as a post-click conversion rate.
    if {"conversions", "clicks"} <= set(out.columns):
        cvr = out["conversions"] / out["clicks"].replace(0, np.nan)
        out["real_cvr"] = cvr.where((cvr > 0) & (cvr <= 1))   # drop impossible CVRs
    else:
        warnings.append("No clean conversions/purchases column — conversion-rate "
                        "and ROAS not calibrated (CTR/CPM/CPC still are).")
    if {"revenue", "spend"} <= set(out.columns):
        out["real_roas"] = out["revenue"] / out["spend"].replace(0, np.nan)
    else:
        warnings.append("No revenue/conversion-value column found — ROAS can't be "
                        "calibrated from this file (CTR/CPM/CPC still usable).")

    out["currency"] = currency
    out = out.reset_index(drop=True)

    missing = [f for f in ("ad_name", "spend", "impressions", "clicks") if f not in mapping]
    report = NormalizeReport(
        n_rows_in=n_in, n_rows_kept=len(out), currency=currency,
        mapped=mapping, missing=missing, warnings=warnings, sheet=sheet_name,
    )
    return out, report


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------

def _platform_key(row: pd.Series) -> str:
    """Bucket a row to a coarse platform we can map to the simulator."""
    hay = " ".join(str(row.get(k, "")) for k in ("platform", "placement", "campaign")).lower()
    if "linkedin" in hay:
        return "linkedin"
    if "instagram" in hay or "ig " in hay:
        return "meta_instagram"
    if "facebook" in hay or "fb " in hay or "meta" in hay:
        return "meta_facebook"
    if "tiktok" in hay:
        return "tiktok"
    if "youtube" in hay:
        return "youtube"
    if "google" in hay or "search" in hay:
        return "google_search"
    return "meta_facebook"   # Meta exports default here when placement is "All"


def _confidence(n_ads: int, impressions: float) -> str:
    if n_ads >= 20 and impressions >= 200_000:
        return "high"
    if n_ads >= 6 and impressions >= 30_000:
        return "medium"
    return "low"


def _agg(df: pd.DataFrame) -> dict:
    spend = float(df["spend"].sum()) if "spend" in df else 0.0
    impr = float(df["impressions"].sum()) if "impressions" in df else 0.0
    clicks = float(df["clicks"].sum()) if "clicks" in df else 0.0
    conv = float(df["conversions"].sum()) if "conversions" in df else 0.0
    rev = float(df["revenue"].sum()) if "revenue" in df else 0.0
    # Guard CVR to a sane range — counts that exceed clicks aren't conversions.
    cvr = conv / clicks if clicks and conv else None
    if cvr is not None and not (0 < cvr <= 1):
        cvr = None
    out: dict[str, Any] = {
        "n_ads": int(len(df)),
        "impressions": int(impr),
        "real_ctr": round(clicks / impr, 5) if impr else None,
        "real_cpm": round(spend / impr * 1000, 3) if impr else None,
        "real_cpc": round(spend / clicks, 3) if clicks else None,
        "real_cvr": round(cvr, 5) if cvr is not None else None,
        "real_roas": round(rev / spend, 3) if spend and rev else None,
        "confidence": _confidence(int(len(df)), impr),
    }
    return out


def calibrate(df: pd.DataFrame, currency: str = "GBP") -> dict:
    """Per-platform + overall real benchmarks, impression-weighted."""
    if df.empty or "impressions" not in df:
        return {"currency": currency, "overall": {}, "by_platform": {}, "usable": False}
    df = df.copy()
    df["_platform"] = df.apply(_platform_key, axis=1)
    by_platform = {}
    for plat, grp in df.groupby("_platform"):
        by_platform[str(plat)] = _agg(grp)
    return {
        "currency": currency,
        "overall": _agg(df),
        "by_platform": by_platform,
        "usable": True,
    }


def ingest_and_calibrate(data: bytes | str, filename: str = "") -> dict:
    """End-to-end: normalize a file then calibrate. Returns a JSON-able dict."""
    df, report = normalize_export(data, filename)
    cal = calibrate(df, currency=report.currency)
    # A compact preview of the cleaned rows for the UI.
    preview_cols = [c for c in ("ad_name", "platform", "placement", "spend",
                                "impressions", "clicks", "real_ctr", "real_cpm",
                                "conversions", "real_roas") if c in df.columns]
    preview = (df[preview_cols].head(8)
               .replace({np.nan: None}).to_dict("records")) if preview_cols else []
    return {
        "report": asdict(report),
        "calibration": cal,
        "preview": preview,
        "rows": df.replace({np.nan: None}).to_dict("records"),
    }
