"""Public CTR dataset loading for background training.

This module handles the "background training" data: public click-through-rate
(CTR) datasets used to calibrate how much each psychology rule (emotional
appeal, scarcity, social proof, relevance) moves real ad performance.

An honest note on the data
--------------------------
The largest, most trusted public CTR datasets (Avazu, Criteo) are *fully
anonymised* -- every feature is hashed, so they contain **no creative
semantics**. They are excellent for one thing: realistic **base CTR rates**
and how CTR varies by context (e.g. banner position). They cannot tell you
whether an ad used scarcity language.

Calibrating the *psychology rules* needs ad-level data with creative content
(ad text/headline) plus a performance signal. That is rarer in public form.
So this module follows a deliberate two-tier design:

  Tier 1 -- BASE RATES        : load_avazu() / load_criteo()  ->  compute_base_rates()
  Tier 2 -- PSYCHOLOGY RULES  : load_generic_creative_csv()  +  tag_creative_features()

Where a real creative-labelled dataset has not been downloaded yet,
``generate_synthetic_ctr_data()`` produces a clearly-labelled synthetic
fallback so the whole pipeline runs end-to-end. The fallback is for plumbing
and demos only -- it must be replaced with real data before any calibration
result is presented as meaningful.

Run directly to print download instructions and create the synthetic fallback:
    python src/data_loader.py
"""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# Allow `python src/data_loader.py` to find config.py in the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import (  # noqa: E402
    PSYCHOLOGY_FEATURES,
    RANDOM_SEED,
    RAW_DATA_DIR,
    SYNTHETIC_CTR_FILE,
)

__all__ = [
    "DATASETS",
    "BENCHMARK_BASE_RATES",
    "download_instructions",
    "tag_creative_features",
    "tag_dataframe",
    "load_avazu",
    "load_criteo",
    "load_generic_creative_csv",
    "generate_synthetic_ctr_data",
    "compute_base_rates",
    "load_training_data",
]

# ===========================================================================
# Canonical schemas
# ---------------------------------------------------------------------------
# Two row shapes flow through this module. Keeping them explicit means every
# downstream module knows exactly what columns to expect.
# ===========================================================================

# Tier 1 -- one row per impression, used for base-rate statistics.
BASE_RATE_COLUMNS = ["source", "clicked", "banner_pos",
                     "device_type", "hour_of_day"]

# Tier 2 -- one row per ad/ad-group, used for psychology-rule calibration.
CREATIVE_COLUMNS = ["ad_id", "source", "ad_text", "impressions",
                    "clicks", "ctr", *PSYCHOLOGY_FEATURES]

# Typical observed CTR by channel -- directional industry benchmark ranges,
# NOT measured for any specific brand. Used as the base rate when no real
# Tier-1 dataset has been downloaded, and as the channel base in the agent.
BENCHMARK_BASE_RATES = {
    "display": 0.006,
    "social_feed": 0.012,
    "search": 0.030,
    "video": 0.018,
    "email": 0.022,
}

# ===========================================================================
# Public dataset registry + download instructions
# ---------------------------------------------------------------------------
# URLs are given where they are stable. Mendeley DOIs are not hard-coded
# because the catalogue is not stable -- a search procedure is given instead.
# ===========================================================================

DATASETS = {
    "avazu": {
        "name": "Avazu Click-Through Rate Prediction",
        "source": "Kaggle competition",
        "url": "https://www.kaggle.com/competitions/avazu-ctr-prediction",
        "provides": "base CTR + CTR by banner position / device (anonymised)",
        "creative_features": False,
        "size": "~40M impressions (train.gz, ~1.2GB compressed)",
        "license": "Kaggle competition rules -- research/educational use",
        "steps": [
            "Create a free Kaggle account and accept the competition rules "
            "at the URL above (required before any download works).",
            "pip install kaggle, then put your API token at "
            "~/.kaggle/kaggle.json and run: chmod 600 ~/.kaggle/kaggle.json",
            "kaggle competitions download -c avazu-ctr-prediction -p data/raw/",
            "cd data/raw && unzip avazu-ctr-prediction.zip && gunzip train.gz",
            "Load with load_avazu('data/raw/train', nrows=200_000).",
        ],
    },
    "criteo": {
        "name": "Criteo Display Advertising Challenge",
        "source": "Kaggle competition",
        "url": "https://www.kaggle.com/c/criteo-display-ad-challenge",
        "provides": "overall base CTR only (all 39 features hashed/anonymised)",
        "creative_features": False,
        "size": "~45M rows (train.txt, ~11GB uncompressed)",
        "license": "Kaggle competition rules -- research/educational use",
        "steps": [
            "Accept the competition rules at the URL above.",
            "kaggle competitions download -c criteo-display-ad-challenge "
            "-p data/raw/",
            "cd data/raw && unzip criteo-display-ad-challenge.zip",
            "Load with load_criteo('data/raw/train.txt', nrows=200_000).",
        ],
    },
    "kaggle_fb": {
        "name": "Facebook Ad Campaign / Sales Conversion Optimization",
        "source": "Kaggle dataset",
        "url": "https://www.kaggle.com/datasets  "
               "(search: 'Sales Conversion Optimization')",
        "provides": "campaign-level impressions/clicks/spend/conversions by "
                    "age, gender, interest -- CTR + conversion funnel, but "
                    "no ad creative text",
        "creative_features": False,
        "size": "small (~1k rows, KAG_conversion_data.csv)",
        "license": "see the dataset page (typically open / CC)",
        "steps": [
            "Search Kaggle datasets for 'Sales Conversion Optimization'.",
            "Download KAG_conversion_data.csv into data/raw/.",
            "Useful for sanity-checking CTR-by-demographic; load it with "
            "load_generic_creative_csv() and a column mapping.",
        ],
    },
    "mendeley": {
        "name": "Mendeley Data -- online advertising / CTR datasets",
        "source": "Mendeley Data",
        "url": "https://data.mendeley.com/",
        "provides": "varies -- several CTR datasets are hosted; prefer one "
                    "that includes ad text/headline for psychology-rule "
                    "calibration",
        "creative_features": "varies",
        "size": "varies",
        "license": "per-dataset (most are CC-BY)",
        "steps": [
            "Mendeley dataset DOIs are not stable across the catalogue, so "
            "search rather than rely on a hard-coded link.",
            "Go to https://data.mendeley.com/ and search 'click-through "
            "rate', 'online advertising', or 'digital advertising'.",
            "Prefer a dataset that includes ad text/headline or creative "
            "attributes -- that is what enables psychology-rule calibration.",
            "Download the CSV into data/raw/ and load it with "
            "load_generic_creative_csv(path, text_col=..., ...).",
        ],
    },
}


def download_instructions(dataset: str | None = None) -> str:
    """Return formatted download instructions for one or all datasets."""
    keys = [dataset] if dataset else list(DATASETS)
    blocks = []
    for key in keys:
        if key not in DATASETS:
            raise KeyError(f"Unknown dataset '{key}'. "
                           f"Choose from: {sorted(DATASETS)}")
        d = DATASETS[key]
        lines = [
            f"[{key}] {d['name']}",
            f"  source   : {d['source']}",
            f"  url      : {d['url']}",
            f"  provides : {d['provides']}",
            f"  creative : {d['creative_features']}  | size: {d['size']}",
            f"  license  : {d['license']}",
            "  steps    :",
        ]
        lines += [f"    {i}. {s}" for i, s in enumerate(d["steps"], 1)]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ===========================================================================
# Creative feature tagging (heuristic)
# ---------------------------------------------------------------------------
# A transparent keyword/lexicon baseline that turns ad text into 0-1 scores
# for the four psychology rules. It is deliberately simple and inspectable;
# it can be swapped for an LLM tagger or a trained classifier later without
# changing any downstream code (same output schema).
#
# Note on `relevance`: from ad text alone we can only measure a proxy --
# message clarity / benefit specificity (concrete benefits, personalisation,
# numbers). True audience relevance is computed per-persona at simulation time
# (the agent's persona_match term), not here.
# ===========================================================================

_LEXICONS: dict[str, list[str]] = {
    "emotional_appeal": [
        "love", "amazing", "incredible", "stunning", "beautiful",
        "breathtaking", "unforgettable", "heartwarming", "shocking",
        "inspire", "dream", "joy", "thrill", "passion", "wow", "happy",
        "fear", "miss out", "regret", "feel",
    ],
    "scarcity": [
        "limited", "last chance", "hurry", "today only", "ends tonight",
        "ends soon", "expires", "while supplies last", "don't miss",
        "few left", "selling fast", "act fast", "final", "deadline",
        "only", "now", "before it's gone",
    ],
    "social_proof": [
        "bestseller", "best-selling", "best selling", "#1", "number one",
        "thousands", "millions", "customers", "reviews", "rated", "5-star",
        "five star", "trusted", "as seen", "award", "award-winning",
        "recommended", "popular", "join", "loved by", "voted", "testimonial",
    ],
    "relevance": [
        "you", "your", "save", "free", "get", "off", "guarantee", "results",
        "proven", "easy", "fast", "now you can", "exclusive", "for you",
        "designed for", "discount",
    ],
}


def _contains(text: str, phrase: str) -> bool:
    """Whole-word (or phrase) match. Falls back to substring for tokens that
    contain non-word characters such as '#1'."""
    if re.fullmatch(r"[\w' -]+", phrase):
        return re.search(rf"\b{re.escape(phrase)}\b", text) is not None
    return phrase in text


def tag_creative_features(text: str) -> dict[str, float]:
    """Score ad ``text`` on the four psychology rules, each in [0, 1].

    Scores saturate: each additional cue matters less than the previous one
    (``1 - exp(-rate * hits)``), which mirrors diminishing returns in copy.
    """
    text = (text or "").lower()
    scores: dict[str, float] = {}
    for feature, lexicon in _LEXICONS.items():
        hits = sum(1 for phrase in lexicon if _contains(text, phrase))
        # Feature-specific extra cues beyond the keyword list.
        if feature == "emotional_appeal":
            hits += min(text.count("!"), 3)          # exclamation intensity
        if feature == "relevance":
            hits += 1 if re.search(r"\d", text) else 0   # concrete numbers
            hits += 1 if "%" in text else 0              # explicit offer size
        scores[feature] = round(float(1 - np.exp(-0.55 * hits)), 3)
    return scores


def tag_dataframe(df: pd.DataFrame, text_col: str = "ad_text") -> pd.DataFrame:
    """Add the four psychology-rule columns to ``df`` derived from ``text_col``.

    Returns a copy; the original frame is left untouched.
    """
    if text_col not in df.columns:
        raise KeyError(f"Column '{text_col}' not found in DataFrame.")
    out = df.copy()
    tagged = out[text_col].fillna("").map(tag_creative_features)
    for feature in PSYCHOLOGY_FEATURES:
        out[feature] = tagged.map(lambda d, f=feature: d[f])
    return out


# ===========================================================================
# Tier 1 loaders -- real anonymised CTR datasets (base rates)
# ===========================================================================

def load_avazu(path: str | Path, nrows: int = 200_000) -> pd.DataFrame:
    """Load an Avazu ``train`` file into the Tier-1 base-rate schema.

    Only the columns relevant to base rates are read (click, banner position,
    device type, hour). ``nrows`` caps the read -- the full file is ~40M rows.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Avazu file not found at {path}. "
            f"See download_instructions('avazu')."
        )
    usecols = ["click", "banner_pos", "device_type", "hour"]
    raw = pd.read_csv(path, usecols=usecols, nrows=nrows)
    out = pd.DataFrame({
        "source": "avazu",
        "clicked": raw["click"].astype(int),
        "banner_pos": raw["banner_pos"],
        "device_type": raw["device_type"],
        # Avazu 'hour' is encoded YYMMDDHH; take the last two digits.
        "hour_of_day": raw["hour"].astype("Int64") % 100,
    })
    return out[BASE_RATE_COLUMNS]


def load_criteo(path: str | Path, nrows: int = 200_000) -> pd.DataFrame:
    """Load a Criteo ``train.txt`` file into the Tier-1 base-rate schema.

    Criteo is tab-separated with no header: column 0 is the click label and
    the remaining 39 columns are hashed/anonymised, so only the overall base
    rate is recoverable (context columns are left NaN).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Criteo file not found at {path}. "
            f"See download_instructions('criteo')."
        )
    raw = pd.read_csv(path, sep="\t", header=None, usecols=[0],
                      names=["label"], nrows=nrows)
    out = pd.DataFrame({
        "source": "criteo",
        "clicked": raw["label"].astype(int),
        "banner_pos": np.nan,
        "device_type": np.nan,
        "hour_of_day": np.nan,
    })
    return out[BASE_RATE_COLUMNS]


# ===========================================================================
# Tier 2 loader -- generic creative-labelled CSV
# ===========================================================================

def load_generic_creative_csv(
    path: str | Path,
    text_col: str = "ad_text",
    impressions_col: str | None = "impressions",
    clicks_col: str | None = "clicks",
    ctr_col: str | None = None,
    id_col: str | None = None,
    source: str = "custom",
) -> pd.DataFrame:
    """Load any creative-labelled ad CSV into the Tier-2 schema.

    Handles datasets downloaded from Mendeley/Kaggle that include ad text and
    a performance signal. CTR is taken from ``ctr_col`` if given, otherwise
    derived from clicks / impressions. Psychology-rule features are tagged
    from ``text_col`` via :func:`tag_creative_features`.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found at {path}.")
    raw = pd.read_csv(path)

    if text_col not in raw.columns:
        raise KeyError(
            f"Text column '{text_col}' not in {path.name}. "
            f"Available columns: {list(raw.columns)}"
        )

    out = pd.DataFrame()
    out["ad_text"] = raw[text_col].fillna("").astype(str)
    out["ad_id"] = (raw[id_col].astype(str) if id_col and id_col in raw.columns
                    else [f"AD{i:05d}" for i in range(1, len(raw) + 1)])
    out["source"] = source

    has_imp = impressions_col and impressions_col in raw.columns
    has_clk = clicks_col and clicks_col in raw.columns
    out["impressions"] = (raw[impressions_col] if has_imp else np.nan)
    out["clicks"] = (raw[clicks_col] if has_clk else np.nan)

    if ctr_col and ctr_col in raw.columns:
        out["ctr"] = raw[ctr_col].astype(float)
    elif has_imp and has_clk:
        # Guard against divide-by-zero on rows with no impressions.
        imp = out["impressions"].replace({0: np.nan})
        out["ctr"] = (out["clicks"] / imp).astype(float)
    else:
        raise ValueError(
            "Cannot determine CTR: provide ctr_col, or both "
            "impressions_col and clicks_col."
        )

    tagged = tag_dataframe(out, text_col="ad_text")
    return tagged[CREATIVE_COLUMNS]


# ===========================================================================
# Synthetic fallback (clearly labelled)
# ===========================================================================

# Illustrative ad copy lines used only to give synthetic rows non-empty text.
# The numeric psychology features are the ground truth for synthetic rows --
# this text is cosmetic and is NOT re-tagged.
_SYNTHETIC_AD_LINES = [
    "Upgrade your everyday routine today.",
    "Limited release -- only a few left this week.",
    "Join thousands of happy customers who already switched.",
    "Save 30% when you order before midnight.",
    "The award-winning choice, rated five stars.",
    "Discover something you'll genuinely love.",
    "Your best results, made easy and fast.",
    "Don't miss out -- this offer ends tonight.",
    "Trusted by millions. Try it free.",
    "An incredible experience designed for you.",
    "Proven results, guaranteed satisfaction.",
    "Exclusive deal: get yours now.",
]

# Illustrative logit-scale coefficients for how each psychology rule moves
# CTR. Directionally consistent with advertising literature (relevance and
# emotional appeal carry the most weight; scarcity is real but smaller and
# context-dependent). These are PRIORS for the synthetic fallback, not
# measured effects -- calibration on real data should override them.
_SYNTHETIC_COEFFICIENTS = {
    "emotional_appeal": 0.60,
    "scarcity": 0.35,
    "social_proof": 0.50,
    "relevance": 0.70,
}


def generate_synthetic_ctr_data(n: int = 600,
                                seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Generate a clearly-labelled synthetic Tier-2 CTR dataset.

    Each row is a synthetic ad with the four psychology features and an
    observed CTR generated from them via a logistic model plus binomial
    sampling noise. This exists so the calibration/simulation pipeline runs
    end-to-end before any real dataset is downloaded.

    WARNING: synthetic. Calibrating on this only recovers the priors baked in
    above -- it does not represent real-world effects. Replace with a real
    creative-labelled dataset before presenting calibration results.
    """
    rng = np.random.default_rng(seed)

    # Feature values: Beta(2,3) -> mean 0.4, right-skewed (most ads are mild).
    features = {f: np.clip(rng.beta(2, 3, n), 0, 1)
                for f in PSYCHOLOGY_FEATURES}

    # Logistic CTR model around a ~1.2% display base rate.
    base_logit = np.log(0.012 / (1 - 0.012))
    logit = np.full(n, base_logit)
    for f, coef in _SYNTHETIC_COEFFICIENTS.items():
        logit = logit + coef * features[f]
    logit = logit + rng.normal(0.0, 0.40, n)         # unexplained variation
    true_ctr = 1.0 / (1.0 + np.exp(-logit))

    impressions = rng.integers(3_000, 80_000, n)
    clicks = rng.binomial(impressions, true_ctr)
    ctr = clicks / impressions

    df = pd.DataFrame({
        "ad_id": [f"SYN{i:05d}" for i in range(1, n + 1)],
        "source": "synthetic",
        "ad_text": rng.choice(_SYNTHETIC_AD_LINES, size=n),
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr.round(5),
    })
    for f in PSYCHOLOGY_FEATURES:
        df[f] = features[f].round(3)
    return df[CREATIVE_COLUMNS]


# ===========================================================================
# Aggregation + orchestration
# ===========================================================================

def compute_base_rates(base_df: pd.DataFrame) -> dict:
    """Summarise a Tier-1 impression-level frame into base CTR statistics."""
    if "clicked" not in base_df.columns:
        raise KeyError("Expected a Tier-1 frame with a 'clicked' column.")
    stats: dict = {
        "n_impressions": int(len(base_df)),
        "overall_ctr": float(base_df["clicked"].mean()),
        "source": sorted(base_df["source"].dropna().unique().tolist()),
    }
    if base_df["banner_pos"].notna().any():
        stats["ctr_by_banner_pos"] = (
            base_df.groupby("banner_pos")["clicked"].mean().round(5).to_dict()
        )
    if base_df["device_type"].notna().any():
        stats["ctr_by_device_type"] = (
            base_df.groupby("device_type")["clicked"].mean().round(5).to_dict()
        )
    return stats


def load_training_data(creative_path: str | Path | None = None,
                        base_path: str | Path | None = None,
                        use_synthetic_fallback: bool = True) -> dict:
    """Assemble the background-training data for calibration.

    Parameters
    ----------
    creative_path : path or None
        A creative-labelled CSV (Tier 2). If None, the synthetic fallback is
        used (unless ``use_synthetic_fallback`` is False).
    base_path : path or None
        An Avazu/Criteo file (Tier 1) for base rates. If None, the directional
        benchmark base rates are used instead.

    Returns
    -------
    dict with keys: ``creative_df``, ``creative_source``, ``base_rates``,
    ``base_source``, ``is_synthetic``.
    """
    # --- Tier 2: creative-labelled data -----------------------------------
    if creative_path is not None:
        creative_df = load_generic_creative_csv(creative_path)
        creative_source = str(creative_path)
        is_synthetic = False
    elif use_synthetic_fallback:
        warnings.warn(
            "No real creative-labelled dataset supplied -- using the "
            "SYNTHETIC fallback. Calibration results are illustrative only. "
            "See download_instructions() to obtain real data.",
            stacklevel=2,
        )
        creative_df = generate_synthetic_ctr_data()
        creative_df.to_csv(SYNTHETIC_CTR_FILE, index=False)
        creative_source = f"synthetic ({SYNTHETIC_CTR_FILE.name})"
        is_synthetic = True
    else:
        raise FileNotFoundError(
            "No creative_path given and synthetic fallback disabled."
        )

    # --- Tier 1: base rates -----------------------------------------------
    if base_path is not None:
        base_path = Path(base_path)
        if base_path.suffix == ".txt":
            base_df = load_criteo(base_path)
        else:
            base_df = load_avazu(base_path)
        base_rates = compute_base_rates(base_df)
        base_source = str(base_path)
    else:
        base_rates = {
            "overall_ctr": BENCHMARK_BASE_RATES["social_feed"],
            "ctr_by_channel": dict(BENCHMARK_BASE_RATES),
            "note": "directional industry benchmark ranges -- not measured",
        }
        base_source = "benchmark defaults"

    return {
        "creative_df": creative_df,
        "creative_source": creative_source,
        "base_rates": base_rates,
        "base_source": base_source,
        "is_synthetic": is_synthetic,
    }


# ===========================================================================
# CLI entry point
# ===========================================================================

def _main() -> None:
    print("=" * 70)
    print("PUBLIC CTR DATASET -- DOWNLOAD INSTRUCTIONS")
    print("=" * 70)
    print(download_instructions())

    print("\n" + "=" * 70)
    print("CREATIVE FEATURE TAGGER -- demo")
    print("=" * 70)
    for sample in [
        "Limited time only! Save 50% today -- don't miss out.",
        "The #1 rated moisturizer, loved by thousands of customers.",
        "A calm, simple way to organize your week.",
    ]:
        print(f"  {sample!r}")
        print(f"    -> {tag_creative_features(sample)}")

    print("\n" + "=" * 70)
    print("SYNTHETIC FALLBACK -- generating Tier-2 training data")
    print("=" * 70)
    bundle = load_training_data()  # no real data -> synthetic fallback
    df = bundle["creative_df"]
    print(df.head(5).to_string(index=False))
    print(f"\nRows: {len(df)} | mean CTR: {df['ctr'].mean():.4f} "
          f"| CTR range: {df['ctr'].min():.4f}-{df['ctr'].max():.4f}")
    print(f"Saved synthetic dataset -> {SYNTHETIC_CTR_FILE}")
    print(f"Base rates source: {bundle['base_source']}")


if __name__ == "__main__":
    _main()
