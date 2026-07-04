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
    "spend":         ["amount spent", "total spent", "total cost", "spend", "cost"],
    "impressions":   ["impressions", "impr.", "impression"],
    "reach":         ["reach"],
    "frequency":     ["frequency", "freq"],
    "clicks":        ["link clicks", "clicks (destination)", "clicks (all)",
                      "total clicks", "clicks", "link click"],
    "ctr_reported":  ["ctr (link click-through rate)", "ctr (destination)",
                      "click through rate (ctr)", "click-through rate (ctr)",
                      "ctr (all)", "ctr (link)", "click through rate", "ctr"],
    "cpc_reported":  ["cpc (cost per link click)", "cpc (destination)",
                      "average cpc", "avg. cpc", "cpc (all)", "cpc", "cost per click"],
    # NB: bare "result" is intentionally excluded — it would wrongly grab the
    # text "Result type" column. "Cost per result" is mapped separately below.
    "conversions":   ["results", "purchases", "website purchases",
                      "external website conversions", "total conversions",
                      "complete payment", "complete payments", "conversions",
                      "leads"],
    "result_type":   ["result type", "result indicator"],
    "cost_per_result": ["cost per result", "cost per result type"],
    "revenue":       ["purchase conversion value", "purchases conversion value",
                      "total complete payment value", "total conv. value",
                      "all conv. value", "conv. value", "purchase value",
                      "conversion value", "revenue", "total conversion value"],
    "currency":      ["currency", "currency code"],
    "date_start":    ["reporting starts", "start date (in utc)", "start date",
                      "day", "date start", "starts", "week"],
    "date_end":      ["reporting ends", "end date (in utc)", "end date",
                      "date end", "ends"],
    "objective":     ["objective"],
    "ad_copy":       ["body", "primary text", "ad copy", "title", "headline"],
    "test_group":    ["test group", "test_group", "experiment"],
    # Audience targeting hint — used by Pillar B segment-keyed calibration.
    # Meta/LinkedIn exports vary: sometimes a literal audience name, sometimes
    # tucked into ad_set_name. We capture any of them; _segment_key() unions
    # everything we know about the row and pattern-matches.
    "audience":      ["audience", "audience name", "saved audience"],
    "ad_set_name":   ["ad set name", "ad set", "adset name", "adset",
                      "ad group", "ad group name"],
    "targeting":     ["targeting", "audience targeting", "demographics"],
}

# Header synonyms we scan for when locating the header row under title rows.
_HEADER_HINTS = {"ad name", "campaign name", "impressions", "amount spent",
                 "link clicks", "reach", "placement", "clicks", "cost",
                 "spend", "conversions"}

_NUMERIC_FIELDS = {"spend", "impressions", "reach", "frequency", "clicks",
                   "ctr_reported", "cpc_reported", "conversions",
                   "cost_per_result", "revenue"}


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


def _one_num(s: str) -> float:
    """Parse a single money/number string, locale-aware on the decimal mark.

    Handles UK/US '1,234.56', European '1.234,56', and bare '2,5' / '2.5'
    without silently corrupting them (the old strip-everything approach turned
    '1.234,56' into '1.234.56' -> NaN, or '2,5' into '25').
    """
    t = re.sub(r"[^0-9.,\-]", "", str(s)).strip()
    if t in ("", "-", ".", ","):
        return float("nan")
    has_dot, has_comma = "." in t, "," in t
    if has_dot and has_comma:
        # The LAST separator is the decimal mark; the other groups thousands.
        if t.rfind(",") > t.rfind("."):      # European: 1.234,56
            t = t.replace(".", "").replace(",", ".")
        else:                                 # UK/US: 1,234.56
            t = t.replace(",", "")
    elif has_comma:
        # Comma only: decimal if it looks like one (e.g. '2,5'), else thousands.
        t = t.replace(",", "." if re.fullmatch(r"-?\d{1,3},\d{1,2}", t) else "")
    try:
        return float(t)
    except ValueError:
        return float("nan")


def _to_num(series: pd.Series) -> pd.Series:
    """Coerce a money/number column to float, locale-aware (see _one_num)."""
    if series.dtype.kind in "if":
        return series.astype(float)
    return series.astype(str).map(_one_num).astype(float)


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


# Pillar B: map an uploaded ad row to one of the simulator's 9
# AUDIENCE_SEGMENTS (see src/personas.py). The output of calibrate() can then
# expose by_segment alongside by_platform, so when the wizard's chosen
# audience matches a segment with enough real ads, that segment's CTR/CPM
# anchors the forecast — not just the platform average.
#
# Heuristic by design: real exports don't carry the simulator's segment
# vocabulary, so we substring-match on what the user typed (audience name,
# ad set name, campaign, placement, targeting). When nothing matches we
# return "unknown" — better to be honestly unsegmented than to fake it.
_SEGMENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Generational — age-band shorthand or explicit labels.
    ("gen_z",         ("gen z", "gen-z", "genz", "18-24", "18 to 24",
                        "tiktok native", "young adult", "students",
                        "uni students", "college")),
    ("millennials",   ("millennial", "millennials", "25-34", "25-40",
                        "25 to 34", "25 to 40", "young profession")),
    ("gen_x",         ("gen x", "gen-x", "genx", "35-54", "41-55",
                        "middle aged", "parents")),
    ("boomers",       ("boomer", "boomers", "55+", "56+", "65+",
                        "seniors", "retirees", "older adults")),
    # Wallet / lifestyle.
    ("high_income",   ("high income", "affluent", "luxury", "premium",
                        "wealth", "executives", "c-suite", "c suite",
                        "decision makers", "decision-makers", "vip")),
    ("budget_conscious", ("budget", "discount", "value", "deal seekers",
                          "deal-seekers", "thrifty", "savings", "save",
                          "bargain", "low income")),
    # Adopter / influence.
    ("early_adopters", ("early adopter", "innovators", "tech enthusiast",
                         "beta", "tech savvy", "tech-savvy", "geeks")),
    ("socially_influenced", ("social", "influencer", "community", "trend",
                              "trendy", "trendsetter", "fomo", "viral")),
)


def _segment_key(row: pd.Series) -> str:
    """Bucket a row to one of the simulator's 9 AUDIENCE_SEGMENTS.

    Returns the segment slug or 'unknown' when no signal is present — the
    calibration consumer treats 'unknown' as no segment data, falling back
    to the per-platform anchor.
    """
    hay = " ".join(str(row.get(k, "")) for k in
                   ("audience", "ad_set_name", "targeting", "campaign",
                    "placement")).lower()
    if not hay.strip():
        return "unknown"
    for seg, patterns in _SEGMENT_PATTERNS:
        if any(p in hay for p in patterns):
            return seg
    return "unknown"


# Pillar B+: 12-bucket interest taxonomy for the (segment × interest) cross-tab.
# Patterns are ordered shortest-to-most-specific within each bucket so the
# first-match wins consistently. The buckets deliberately overlap with the
# wizard's product_category vocabulary (see _CATEGORY_INTEREST_HINTS in
# agent.py) so the same words land the same place from either side.
_INTEREST_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("fitness",       ("fitness", "gym", "workout", "yoga", "running",
                        "cycling", "crossfit", "athleisure")),
    ("fashion",       ("fashion", "apparel", "clothing", "streetwear",
                        "luxury wear", "menswear", "womenswear")),
    ("beauty",        ("beauty", "skincare", "makeup", "cosmetic",
                        "haircare", "fragrance")),
    ("tech",          ("tech", "electronics", "gadget", "saas", "software",
                        "ai ", " ai", "gaming", "developer", "startup")),
    ("travel",        ("travel", "vacation", "holiday", "flights", "hotels",
                        "tourism", "adventure travel")),
    ("food",          ("food", "drink", "beverage", "restaurant", "cooking",
                        "recipe", "foodie", "coffee", "wine")),
    ("home",          ("home", "diy", "furniture", "interior", "decor",
                        "garden", "kitchen")),
    ("finance",       ("finance", "investing", "crypto", "trading",
                        "wealth", "personal finance", "loans", "mortgage")),
    ("automotive",    ("automotive", "auto", "cars", "ev", "electric vehicle",
                        "motorbike", "trucks")),
    ("entertainment", ("entertainment", "movies", "music", "streaming",
                        "podcast", "reading", "books")),
    ("business",      ("business", "b2b", "professional", "decision maker",
                        "decision-maker", "marketing", "sales", "hr ",
                        "operations", "c-suite", "leadership")),
    ("wellness",      ("wellness", "mindfulness", "mental health", "self-care",
                        "self care", "meditation", "sleep")),
)

# A flat slug list — useful for the API + UI to know the full taxonomy
# without re-parsing the patterns tuple.
INTEREST_BUCKETS: tuple[str, ...] = tuple(slug for slug, _ in _INTEREST_PATTERNS)


def _interest_keys(row: pd.Series) -> list[str]:
    """Return all interest buckets matched by the row's audience / ad set /
    targeting text. Empty list when nothing matches.

    Used at calibrate() time to tag each row, and re-used by the wizard's
    consumer code to map the user's chosen filters into the same taxonomy
    so lookups across sides use the same vocabulary.
    """
    hay = " ".join(str(row.get(k, "")) for k in
                   ("audience", "ad_set_name", "targeting", "campaign",
                    "placement", "ad_copy")).lower()
    if not hay.strip():
        return []
    hits = []
    for slug, patterns in _INTEREST_PATTERNS:
        if any(p in hay for p in patterns):
            hits.append(slug)
    return hits


def _dominant_interest(interests: list[str]) -> str:
    """Pick the top interest from a row's matches.

    Order in _INTEREST_PATTERNS is the priority (more-specific first), so
    we return the FIRST hit. 'unknown' when the list is empty — consumer
    treats it like the segment 'unknown' and excludes the cell from the
    cross-tab.
    """
    return interests[0] if interests else "unknown"


def interests_from_chip_ids(chip_ids: list[str]) -> list[str]:
    """Map wizard filter-chip IDs (e.g. 'interest:fitness', 'custom:yoga')
    onto the canonical taxonomy. Used by the wizard at request-build time
    so the same row of words maps the same place from either side of the
    boundary.
    """
    if not chip_ids:
        return []
    bag = " ".join(c.split(":", 1)[-1].lower() for c in chip_ids
                   if not c.startswith(("gender:", "location:", "age:")))
    if not bag.strip():
        return []
    hits = []
    for slug, patterns in _INTEREST_PATTERNS:
        if any(p in bag for p in patterns):
            hits.append(slug)
    return hits


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


def _weighted_ctr(g: pd.DataFrame) -> float | None:
    imp = g["impressions"].sum()
    return float(g["clicks"].sum() / imp) if imp else None


# A time analysis is only meaningful with several distinct dates — many ad
# exports stamp every row with the report's single date range, which would
# otherwise masquerade as "time" when it's really just row order.
_MIN_DISTINCT_DATES = 6

# A per-platform base CTR learned from only a handful of training impressions is
# noise, not signal — one tiny-spend platform row would otherwise produce a
# garbage anchor for its held-out ads. Below this floor we fall back to the
# account-wide training rate instead.
_BACKTEST_MIN_PLATFORM_IMPR = 1000


def _trend(d: pd.DataFrame) -> dict | None:
    """Older-half vs recent-half click-through — the performance-decay signal."""
    if "_date" not in d or d["_date"].notna().sum() < 10 \
            or d["_date"].nunique() < _MIN_DISTINCT_DATES:
        return None
    dd = d[d["_date"].notna()].sort_values("_date")
    cut = len(dd) // 2
    older, recent = _weighted_ctr(dd.iloc[:cut]), _weighted_ctr(dd.iloc[cut:])
    if not older or not recent:
        return None
    change = (recent - older) / older
    return {
        "older_ctr": round(older, 5), "recent_ctr": round(recent, 5),
        "change_pct": round(change, 3),
        "direction": "down" if change < -0.05 else "up" if change > 0.05 else "flat",
    }


def calibrate(df: pd.DataFrame, currency: str = "GBP", recent_days: int = 120,
              platform: str = "auto") -> dict:
    """Per-platform + overall real benchmarks, impression-weighted.

    Calibrates on RECENT data when dates allow (click-rates decay over time, so
    old ads mislead the forecast), falling back to all history when sparse.
    Also returns a trend signal so the UI can warn about decay.

    Pillar B (segment-keyed): when the upload carries audience hints
    (audience / ad_set_name / targeting / campaign keywords), each row is
    additionally tagged to one of the simulator's 9 AUDIENCE_SEGMENTS, and
    a ``by_segment`` block is emitted alongside ``by_platform``. The wizard
    can then anchor the forecast to the chosen audience's real numbers, not
    just the platform average. Rows that can't be classified group as
    'unknown' and are intentionally excluded from ``by_segment`` so the
    consumer's fallback chain (segment → platform → overall) stays honest.
    """
    if df.empty or "impressions" not in df.columns:
        return {"currency": currency, "overall": {},
                "by_platform": {}, "by_segment": {},
                "by_interest": {}, "by_segment_interest": {},
                "usable": False}
    d = df.copy()
    # Explicit per-upload platform tag wins (a LinkedIn upload only ever writes
    # the linkedin cell — isolation). Default "auto" keeps the original
    # row-by-row detection (Meta exports unchanged).
    if platform and platform != "auto":
        d["_platform"] = platform
    else:
        d["_platform"] = d.apply(_platform_key, axis=1)
    d["_segment"] = d.apply(_segment_key, axis=1)
    # Pillar B+: per-row interest tagging. _interests is the full list,
    # _interest is the dominant bucket for the cross-tab.
    d["_interests"] = d.apply(_interest_keys, axis=1)
    d["_interest"] = d["_interests"].apply(_dominant_interest)
    d["_date"] = (pd.to_datetime(d["date_start"], errors="coerce")
                  if "date_start" in d.columns else pd.NaT)

    used, window = d, "all available ads"
    if d["_date"].notna().sum() >= 20 and d["_date"].nunique() >= _MIN_DISTINCT_DATES:
        recent = d[d["_date"] >= d["_date"].max() - pd.Timedelta(days=recent_days)]
        if len(recent) >= 20:                       # enough recent data to trust
            used, window = recent, f"most recent {recent_days} days ({len(recent)} ads)"

    by_platform = {str(plat): _agg(grp) for plat, grp in used.groupby("_platform")}
    # Pillar B: only emit segments that have ENOUGH ads to be trustworthy
    # and aren't 'unknown' (which means we couldn't classify the row).
    # The threshold (3+ ads, 5k+ impressions) is deliberately low because
    # most users won't have huge per-segment volumes; the per-segment
    # _agg() also returns a confidence band that the UI can degrade on.
    def _ok(grp: pd.DataFrame) -> bool:
        if len(grp) < 3:
            return False
        return ("impressions" not in grp.columns
                or float(grp["impressions"].sum()) >= 5_000)

    by_segment: dict = {}
    for seg, grp in used.groupby("_segment"):
        seg_name = str(seg)
        if seg_name == "unknown" or not _ok(grp):
            continue
        by_segment[seg_name] = _agg(grp)
    # Pillar B+: flat by-interest aggregation — useful for users whose
    # uploaded data doesn't carry audience info but DOES carry interest
    # hints (e.g. ad_set_name has "fitness campaign" but no age band).
    by_interest: dict = {}
    for interest, grp in used.groupby("_interest"):
        i_name = str(interest)
        if i_name == "unknown" or not _ok(grp):
            continue
        by_interest[i_name] = _agg(grp)
    # Pillar B+: the (segment × interest) cross-tab — the actual answer to
    # "which audience + interest combo wins for my account". Each cell
    # has to clear the same ≥3 ads + ≥5k impressions threshold; thin cells
    # are not emitted so the consumer's 4-level fallback chain stays clean
    # (segment×interest → segment → platform → overall).
    by_segment_interest: dict = {}
    for (seg, interest), grp in used.groupby(["_segment", "_interest"]):
        seg_name, i_name = str(seg), str(interest)
        if seg_name == "unknown" or i_name == "unknown":
            continue
        if not _ok(grp):
            continue
        by_segment_interest.setdefault(seg_name, {})[i_name] = _agg(grp)

    n_unknown = int((used["_segment"] == "unknown").sum())
    n_interest_unknown = int((used["_interest"] == "unknown").sum())

    # P3b: auction-layer parameters (CPM seasonality + fatigue slope) fitted
    # from the same rows. Rides inside the calibration dict so it persists to
    # calibrations.params (jsonb) with zero schema/frontend-save changes.
    # Fitted on ALL history (d), not the recent window — seasonality needs
    # the calendar breadth. Best-effort: never block calibration on it.
    try:
        try:
            from src.auction import auction_block
        except ImportError:
            from auction import auction_block
        auction = auction_block(d)
    except Exception as exc:                          # noqa: BLE001
        auction = {"cpm_seasonality": {"usable": False, "reason": str(exc)[:120]},
                   "fatigue": {"usable": False, "reason": str(exc)[:120]}}

    return {
        "currency": currency,
        "overall": _agg(used),
        "by_platform": by_platform,
        "by_segment": by_segment,
        "by_interest": by_interest,
        "by_segment_interest": by_segment_interest,
        "by_segment_unknown": n_unknown,
        "by_interest_unknown": n_interest_unknown,
        "usable": True,
        "window": window,
        "trend": _trend(d),
        "auction": auction,
    }


def backtest(df: pd.DataFrame, min_ads: int = 12) -> dict:
    """Time-split validation: calibrate on the older ads, predict the newer
    ones, compare predicted vs ACTUAL click-through.

    This is the honest accuracy proof. We can only backtest what the exports
    actually contain: click-through (and CPM). We predict each held-out ad's
    CTR from the per-platform rate learned on the EARLIER ads — exactly what
    the forecast's calibrated anchor does — then measure the error. Because the
    split is by date, this also captures performance drift over time ('ads get
    harder'). Per-ad creative effects and ROAS need creative files + conversion
    data, which these exports lack — so we don't claim to backtest those.
    """
    if df.empty or "real_ctr" not in df.columns or "date_start" not in df.columns:
        return {"usable": False, "reason": "Need dated ads with click data to backtest."}
    d = df.copy()
    d["_date"] = pd.to_datetime(d["date_start"], errors="coerce")
    d = d[d["_date"].notna() & d["real_ctr"].notna() & (d["impressions"] > 0)]
    if len(d) < min_ads:
        return {"usable": False,
                "reason": f"Need at least {min_ads} dated ads to backtest; have {len(d)}."}
    if d["_date"].nunique() < _MIN_DISTINCT_DATES:
        return {"usable": False,
                "reason": ("This export uses a single reporting period (one date for "
                           "every ad), so we can't validate accuracy over time. "
                           "Re-export with a daily or weekly date breakdown to enable "
                           "the backtest.")}
    d = d.sort_values("_date")
    d["_platform"] = d.apply(_platform_key, axis=1)
    cut = int(len(d) * 0.7)
    train, test = d.iloc[:cut], d.iloc[cut:]

    base: dict[str, float] = {}
    for plat, g in train.groupby("_platform"):
        imp = g["impressions"].sum()
        # Min-impression floor: only trust a per-platform anchor backed by
        # enough volume; otherwise the held-out ads fall back to train_overall.
        if imp >= _BACKTEST_MIN_PLATFORM_IMPR:
            base[str(plat)] = float(g["clicks"].sum() / imp)
    train_overall = float(train["clicks"].sum() / max(train["impressions"].sum(), 1))

    preds, acts, imps, errs = [], [], [], []
    for _, r in test.iterrows():
        pred = base.get(str(r["_platform"]), train_overall)
        act = float(r["real_ctr"])
        if act > 0 and pred and pred > 0:
            preds.append(pred); acts.append(act)
            imps.append(float(r["impressions"])); errs.append(abs(act - pred) / act)
    if not errs:
        return {"usable": False, "reason": "No comparable held-out ads."}

    e = np.array(errs); iw = np.array(imps)
    agg_pred = float(np.average(preds, weights=iw))
    agg_act = float(np.average(acts, weights=iw))
    agg_err = abs(agg_act - agg_pred) / agg_act if agg_act else None
    return {
        "usable": True,
        "n_train": int(len(train)),
        "n_test": int(len(errs)),
        "split": "by date — calibrated on your older 70% of ads, tested on the newest 30%",
        "metric": "predicted vs actual click-through on held-out ads",
        "median_abs_pct_error": round(float(np.median(e)), 3),
        "within_20pct": round(float((e <= 0.20).mean()), 3),
        "within_30pct": round(float((e <= 0.30).mean()), 3),
        "agg_predicted_ctr": round(agg_pred, 5),
        "agg_actual_ctr": round(agg_act, 5),
        "agg_abs_pct_error": round(agg_err, 3) if agg_err is not None else None,
        "note": ("Validates the click-rate calibration (the forecast's foundation) "
                 "out-of-sample. Per-ad creative effects and ROAS need creative "
                 "files + conversion data to backtest."),
    }


def ingest_and_calibrate(data: bytes | str, filename: str = "",
                         segment: str = "general", platform: str = "auto") -> dict:
    """End-to-end: normalize a file then calibrate + backtest + fatigue.

    ``segment`` tags the fatigue thresholds (b2b_saas audiences fatigue sooner
    than a broad/general one). JSON-able dict.
    """
    df, report = normalize_export(data, filename)
    cal = calibrate(df, currency=report.currency, platform=platform)
    bt = backtest(df)
    # Creative-fatigue screen — best-effort, never break a calibration.
    try:
        try:
            from src.fatigue import analyze_fatigue
        except ImportError:
            from fatigue import analyze_fatigue
        fat = analyze_fatigue(df, segment=segment)
    except Exception as exc:                          # noqa: BLE001
        fat = {"usable": False, "segment": segment,
               "reason": f"Fatigue analysis unavailable: {exc}"}
    # A compact preview of the cleaned rows for the UI.
    preview_cols = [c for c in ("ad_name", "platform", "placement", "spend",
                                "impressions", "clicks", "real_ctr", "real_cpm",
                                "conversions", "real_roas") if c in df.columns]
    preview = (df[preview_cols].head(8)
               .replace({np.nan: None}).to_dict("records")) if preview_cols else []
    return {
        "report": asdict(report),
        "calibration": cal,
        "backtest": bt,
        "fatigue": fat,
        "preview": preview,
        "rows": df.replace({np.nan: None}).to_dict("records"),
    }


def calibrate_rows(rows: list[dict], currency: str = "GBP",
                   segment: str = "general", source: str = "live") -> dict:
    """Calibrate + backtest + fatigue on already-normalized ad_outcomes rows
    (e.g. pulled live from a connected ad account). Mirrors the shape of
    ingest_and_calibrate so the frontend renders the SAME result UI.
    """
    df = pd.DataFrame(rows or [])
    n_in = len(df)
    if not df.empty:
        for c in ("impressions", "clicks", "spend", "reach", "conversions", "revenue"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        if "impressions" in df.columns:
            df = df[df["impressions"].fillna(0) > 0].copy()
            if "clicks" in df.columns:
                df["real_ctr"] = (df["clicks"] / df["impressions"]).where(df["impressions"] > 0)
    cal = calibrate(df, currency=currency)
    bt = backtest(df)
    try:
        try:
            from src.fatigue import analyze_fatigue
        except ImportError:
            from fatigue import analyze_fatigue
        fat = analyze_fatigue(df, segment=segment)
    except Exception as exc:                          # noqa: BLE001
        fat = {"usable": False, "segment": segment,
               "reason": f"Fatigue analysis unavailable: {exc}"}
    preview_cols = [c for c in ("ad_name", "platform", "date_start", "spend",
                                "impressions", "clicks", "real_ctr",
                                "conversions", "revenue") if c in df.columns]
    preview = (df[preview_cols].head(8).replace({np.nan: None}).to_dict("records")
               if preview_cols and not df.empty else [])
    report = {
        "n_rows_in": n_in, "n_rows_kept": int(len(df)),
        "currency": currency, "mapped": {}, "missing": [],
        "warnings": [], "sheet": None, "source": source,
    }
    return {
        "report": report,
        "calibration": cal,
        "backtest": bt,
        "fatigue": fat,
        "preview": preview,
        "rows": (df.replace({np.nan: None}).to_dict("records") if not df.empty else []),
    }
