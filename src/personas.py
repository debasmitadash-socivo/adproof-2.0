"""Synthetic persona generation for the ad-simulator platform.

This module builds a population of synthetic consumer personas that stand in
for a real survey panel (YouGov-style). Each persona carries demographic,
psychographic, media-habit, Big Five personality, and purchase-behaviour
attributes.

Design notes
------------
* Personas are *synthetic*: sampled from plausible marginal distributions
  (loosely aligned to US adult population statistics) with a handful of
  deliberate correlations baked in -- e.g. income rises with education,
  younger people skew toward TikTok/Instagram, conscientiousness rises with
  age. They are NOT a real research panel (see README disclaimers).
* Correlations are modelled as transparent weighted sums + noise rather than a
  full covariance matrix. This keeps every attribute explainable: you can
  trace exactly why a given persona scored the way it did.
* One seeded RNG drives the whole population, so results are reproducible.

Public API
----------
generate_personas(n, seed)   -> pandas.DataFrame
save_personas(df, path)      -> Path
load_personas(path)          -> pandas.DataFrame
filter_personas(df, segment) -> pandas.DataFrame
summarize_personas(df)       -> str

Run directly to generate and save the default population:
    python src/personas.py --count 1000 --seed 42
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# Allow `python src/personas.py` to find config.py in the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import DEFAULT_PERSONA_COUNT, PERSONA_FILE, RANDOM_SEED  # noqa: E402

__all__ = [
    "generate_personas",
    "save_personas",
    "load_personas",
    "filter_personas",
    "summarize_personas",
    "AUDIENCE_SEGMENTS",
]

# ===========================================================================
# Distribution constants
# ---------------------------------------------------------------------------
# All weight vectors below are approximate and chosen for plausibility, not
# precision. Adjust them here to re-shape the synthetic population.
# ===========================================================================

AGE_BRACKETS = [(18, 24), (25, 34), (35, 44), (45, 54), (55, 64), (65, 75)]
AGE_BRACKET_WEIGHTS = [0.13, 0.20, 0.18, 0.17, 0.17, 0.15]
AGE_BRACKET_LABELS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65-75"]

GENDERS = ["male", "female", "nonbinary"]
GENDER_WEIGHTS = [0.49, 0.49, 0.02]

EDUCATION_LEVELS = ["high_school", "some_college", "bachelors", "graduate"]
EDUCATION_WEIGHTS = [0.28, 0.26, 0.28, 0.18]
# Baseline annual income (USD) anchored per education tier; later modulated by
# an age earnings curve and lognormal noise.
EDUCATION_INCOME_BASE = {
    "high_school": 38_000,
    "some_college": 50_000,
    "bachelors": 74_000,
    "graduate": 98_000,
}

REGIONS = ["Northeast", "Midwest", "South", "West"]
REGION_WEIGHTS = [0.17, 0.21, 0.38, 0.24]

URBANICITY = ["urban", "suburban", "rural"]
URBANICITY_WEIGHTS = [0.31, 0.55, 0.14]

# Employment mix conditioned on age-bracket index (students skew young,
# retirees skew old).
EMPLOYMENT = ["full_time", "part_time", "student", "unemployed", "retired"]
EMPLOYMENT_BY_AGE = {
    0: [0.40, 0.18, 0.32, 0.08, 0.02],  # 18-24
    1: [0.68, 0.13, 0.10, 0.07, 0.02],  # 25-34
    2: [0.74, 0.12, 0.03, 0.07, 0.04],  # 35-44
    3: [0.72, 0.12, 0.02, 0.07, 0.07],  # 45-54
    4: [0.55, 0.13, 0.01, 0.06, 0.25],  # 55-64
    5: [0.12, 0.10, 0.01, 0.03, 0.74],  # 65-75
}

# Primary media platform conditioned on age-bracket index.
# 2026 distribution: TikTok dominates Gen-Z, Reels eats Feed share at every
# age, Facebook decays toward older audiences, streaming + Shorts pull
# meaningful time from cable / linear TV.
PLATFORMS = ["tiktok", "instagram", "youtube", "facebook", "linkedin",
             "streaming_tv", "news_sites"]
PLATFORM_BY_AGE = {
    0: [0.38, 0.28, 0.18, 0.02, 0.03, 0.08, 0.03],  # 18-24 -- TikTok-first
    1: [0.28, 0.26, 0.18, 0.06, 0.08, 0.10, 0.04],  # 25-34 -- short-form heavy
    2: [0.18, 0.20, 0.18, 0.12, 0.09, 0.15, 0.08],  # 35-44 -- short-form rising
    3: [0.10, 0.12, 0.18, 0.20, 0.07, 0.20, 0.13],  # 45-54 -- FB still strong
    4: [0.05, 0.06, 0.15, 0.28, 0.04, 0.24, 0.18],  # 55-64
    5: [0.02, 0.04, 0.12, 0.32, 0.02, 0.26, 0.22],  # 65-75
}

PRODUCT_CATEGORIES = ["apparel", "electronics", "beauty", "home", "food_bev",
                      "fitness", "travel", "finance", "auto", "entertainment"]

# Schwartz-style personal values, picked per persona from a personality score.
VALUES = ["security", "achievement", "hedonism", "benevolence",
          "stimulation", "conformity"]

INTEREST_POOL = ["sports", "gaming", "cooking", "travel", "fashion", "tech",
                 "music", "fitness", "finance", "parenting", "outdoors",
                 "movies", "reading", "diy", "beauty", "cars"]
INTERESTS_PER_PERSONA = 3

# Float columns rounded to 3 dp for a tidy CSV.
_SCORE_COLUMNS = [
    "openness", "conscientiousness", "extraversion", "agreeableness",
    "neuroticism", "innovativeness", "price_consciousness",
    "brand_consciousness", "social_susceptibility", "ad_receptivity",
    "ad_skepticism", "brand_loyalty", "online_purchase_ratio", "impulsivity",
]


# ===========================================================================
# Sampling helpers
# ===========================================================================

def _clip01(x: np.ndarray) -> np.ndarray:
    """Clamp an array into the [0, 1] interval."""
    return np.clip(x, 0.0, 1.0)


def _beta(rng: np.random.Generator, mean, concentration: float,
          size: int) -> np.ndarray:
    """Sample Beta values with a target ``mean`` in (0, 1).

    ``concentration`` controls spread: higher -> tighter around the mean.
    ``mean`` may be a scalar or a per-row array (enables age-trended traits).
    """
    mean = np.clip(mean, 1e-3, 1 - 1e-3)
    a = mean * concentration
    b = (1 - mean) * concentration
    return rng.beta(a, b, size=size)


def _choice_by_group(rng: np.random.Generator, group_idx: np.ndarray,
                     prob_table: dict, labels: list) -> np.ndarray:
    """Vectorised categorical draw where the probability vector depends on
    each row's group index (e.g. age bracket).

    ``prob_table`` maps group index -> probability list aligned to ``labels``.
    """
    out = np.empty(len(group_idx), dtype=object)
    for group, probs in prob_table.items():
        mask = group_idx == group
        k = int(mask.sum())
        if k:
            out[mask] = rng.choice(labels, size=k, p=probs)
    return out


# ===========================================================================
# Core generator
# ===========================================================================

def generate_personas(n: int = DEFAULT_PERSONA_COUNT,
                       seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Generate ``n`` synthetic personas as a pandas DataFrame.

    Parameters
    ----------
    n : int
        Population size. The platform is designed for 500-2000; values outside
        that range still work but emit a warning (calibration assumes a
        reasonably sized panel).
    seed : int
        RNG seed for full reproducibility.

    Returns
    -------
    pandas.DataFrame
        One row per persona. Columns are grouped as demographics,
        Big Five personality, psychographics, media habits, and purchase
        behaviour. All 0-1 scores are rounded to 3 decimal places.
    """
    if not 500 <= n <= 2000:
        warnings.warn(
            f"n={n} is outside the recommended 500-2000 range; "
            "downstream calibration assumes a panel of that size.",
            stacklevel=2,
        )
    rng = np.random.default_rng(seed)

    # --- Demographics ------------------------------------------------------
    bracket_idx = rng.choice(len(AGE_BRACKETS), size=n, p=AGE_BRACKET_WEIGHTS)
    lows = np.array([b[0] for b in AGE_BRACKETS])
    highs = np.array([b[1] for b in AGE_BRACKETS])
    age = rng.integers(lows[bracket_idx], highs[bracket_idx] + 1)
    # Normalised age, 0.0 (youngest) .. 1.0 (oldest) -- a reusable driver.
    age01 = (age - 18) / (75 - 18)

    gender = rng.choice(GENDERS, size=n, p=GENDER_WEIGHTS)
    region = rng.choice(REGIONS, size=n, p=REGION_WEIGHTS)
    urbanicity = rng.choice(URBANICITY, size=n, p=URBANICITY_WEIGHTS)
    household_size = rng.choice([1, 2, 3, 4, 5], size=n,
                                p=[0.28, 0.34, 0.16, 0.15, 0.07])

    education_idx = rng.choice(len(EDUCATION_LEVELS), size=n,
                               p=EDUCATION_WEIGHTS)
    education = np.array(EDUCATION_LEVELS)[education_idx]
    # education_norm in [0, 1] -- used as an explanatory driver below.
    education_norm = education_idx / (len(EDUCATION_LEVELS) - 1)

    # Income: education anchor x age earnings curve x lognormal noise.
    # The earnings curve peaks near age 50 and tapers for the young/retired.
    edu_base = np.array([EDUCATION_INCOME_BASE[e] for e in education])
    age_earn_factor = 0.55 + 0.45 * np.exp(-((age - 50) ** 2) / (2 * 18 ** 2))
    income = edu_base * age_earn_factor * rng.lognormal(0.0, 0.35, size=n)
    income = (np.round(income / 1000) * 1000).astype(int)
    income01 = _clip01((income - 20_000) / 130_000)

    employment = _choice_by_group(rng, bracket_idx, EMPLOYMENT_BY_AGE,
                                  EMPLOYMENT)

    # --- Big Five personality (OCEAN) -------------------------------------
    # Each trait is Beta-distributed. Means are nudged by age to reflect
    # well-documented lifespan trends: conscientiousness and agreeableness
    # rise with age, neuroticism and openness decline modestly.
    openness = _beta(rng, 0.55 - 0.10 * age01, 8, n)
    conscientiousness = _beta(rng, 0.42 + 0.16 * age01, 8, n)
    extraversion = _beta(rng, 0.50, 7, n)
    agreeableness = _beta(rng, 0.45 + 0.14 * age01, 8, n)
    neuroticism = _beta(rng, 0.55 - 0.14 * age01, 8, n)

    def noise(scale: float = 0.08) -> np.ndarray:
        """Small zero-mean Gaussian noise so derived scores aren't perfectly
        determined by their inputs."""
        return rng.normal(0.0, scale, n)

    # --- Psychographics (derived, explainable weighted sums) --------------
    # Innovativeness / early-adopter tendency: open, younger, outgoing people.
    innovativeness = _clip01(
        0.55 * openness + 0.30 * (1 - age01) + 0.15 * extraversion + noise()
    )
    # Price consciousness: stronger at lower income and higher conscientiousness.
    price_consciousness = _clip01(
        0.45 * (1 - income01) + 0.30 * conscientiousness + 0.10 + noise()
    )
    # Brand consciousness: outgoing, higher-income, younger consumers.
    brand_consciousness = _clip01(
        0.40 * extraversion + 0.25 * income01 + 0.20 * (1 - age01) + noise()
    )
    # Ad skepticism: rises with conscientiousness, education, and age.
    # 2026 baseline lifted by +0.10 across the board -- post-AI-creative
    # saturation, audiences are noticeably more "ad-literate" and skeptical
    # of polished / clearly-promoted content than they were in 2024.
    ad_skepticism = _clip01(
        0.10 + 0.40 * conscientiousness + 0.25 * education_norm
        + 0.18 * age01 + noise()
    )
    # Ad receptivity: openness up, skepticism down, younger up.
    ad_receptivity = _clip01(
        0.50 * openness + 0.25 * (1 - ad_skepticism)
        + 0.15 * (1 - age01) + noise()
    )
    # Susceptibility to social influence (drives word-of-mouth uptake later).
    social_susceptibility = _clip01(
        0.35 * agreeableness + 0.25 * extraversion + 0.20 * neuroticism
        + 0.20 * (1 - age01) + noise()
    )

    # Primary personal value: highest-scoring Schwartz value given personality,
    # with Gumbel noise so the pick stays probabilistic rather than rigid.
    value_scores = np.stack([
        0.6 * conscientiousness + 0.5 * age01,                    # security
        0.7 * conscientiousness + 0.4 * income01,                 # achievement
        0.7 * openness + 0.5 * (1 - age01),                       # hedonism
        0.8 * agreeableness,                                      # benevolence
        0.7 * openness + 0.5 * extraversion + 0.3 * (1 - age01),  # stimulation
        0.6 * (1 - openness) + 0.4 * age01,                       # conformity
    ], axis=1)
    value_scores = value_scores + rng.gumbel(0.0, 0.4, value_scores.shape)
    primary_value = np.array(VALUES)[value_scores.argmax(axis=1)]

    # Interests: a few distinct tags per persona, stored semicolon-joined so
    # the CSV stays flat and easy to read.
    interests = [
        ";".join(rng.choice(INTEREST_POOL, size=INTERESTS_PER_PERSONA,
                            replace=False))
        for _ in range(n)
    ]

    # --- Media habits ------------------------------------------------------
    primary_platform = _choice_by_group(rng, bracket_idx, PLATFORM_BY_AGE,
                                        PLATFORMS)
    # 2026 baseline: average daily media time is up across all ages vs 2024
    # (short-form scroll, multi-screen). Young users push 5 hrs/day, oldest
    # bracket still pushes ~3 hrs.
    base_minutes = 290 - 105 * age01
    daily_media_minutes = np.round(
        base_minutes * rng.lognormal(0.0, 0.28, n)
    ).clip(30, 660).astype(int)

    # --- Purchase behaviour -----------------------------------------------
    # Impulsivity: low conscientiousness, higher neuroticism, younger/outgoing.
    impulsivity = _clip01(
        0.45 * (1 - conscientiousness) + 0.25 * neuroticism
        + 0.15 * (1 - age01) + 0.15 * extraversion + noise()
    )
    # Brand loyalty: builds with age, conscientiousness, agreeableness.
    brand_loyalty = _clip01(
        0.40 * age01 + 0.30 * conscientiousness
        + 0.20 * agreeableness + noise()
    )
    # Share of purchases made online: younger, higher-income, innovative.
    online_purchase_ratio = _clip01(
        0.45 * (1 - age01) + 0.25 * income01
        + 0.15 * innovativeness + noise()
    )
    # Discretionary purchases per month: scales with income and impulsivity.
    purchase_frequency = np.round(
        2 + 6 * income01 + 4 * impulsivity + rng.normal(0.0, 1.0, n)
    ).clip(0, 20).astype(int)
    # Average order value (USD): income-driven with lognormal spread, $5 steps.
    avg_order_value = np.maximum(5, np.round(
        (25 + 220 * income01) * rng.lognormal(0.0, 0.30, n) / 5
    ) * 5).astype(int)
    primary_category = rng.choice(PRODUCT_CATEGORIES, size=n)

    # Lifestyle segment: a readable label from two axes (adopter x wallet).
    lifestyle_segment = [
        ("early-adopter" if iv >= 0.55 else "mainstream") + "/"
        + ("budget" if pc >= 0.55 else "premium")
        for iv, pc in zip(innovativeness, price_consciousness)
    ]

    # --- Assemble ----------------------------------------------------------
    df = pd.DataFrame({
        "persona_id": [f"P{i:05d}" for i in range(1, n + 1)],
        # Demographics
        "age": age,
        "age_bracket": np.array(AGE_BRACKET_LABELS)[bracket_idx],
        "gender": gender,
        "income_usd": income,
        "education": education,
        "employment": employment,
        "region": region,
        "urbanicity": urbanicity,
        "household_size": household_size,
        # Big Five personality
        "openness": openness,
        "conscientiousness": conscientiousness,
        "extraversion": extraversion,
        "agreeableness": agreeableness,
        "neuroticism": neuroticism,
        # Psychographics
        "primary_value": primary_value,
        "lifestyle_segment": lifestyle_segment,
        "interests": interests,
        "innovativeness": innovativeness,
        "price_consciousness": price_consciousness,
        "brand_consciousness": brand_consciousness,
        "social_susceptibility": social_susceptibility,
        # Media habits
        "primary_platform": primary_platform,
        "daily_media_minutes": daily_media_minutes,
        "ad_receptivity": ad_receptivity,
        "ad_skepticism": ad_skepticism,
        # Purchase behaviour
        "primary_category": primary_category,
        "purchase_frequency": purchase_frequency,
        "avg_order_value": avg_order_value,
        "brand_loyalty": brand_loyalty,
        "online_purchase_ratio": online_purchase_ratio,
        "impulsivity": impulsivity,
    })

    # Income bracket: a readable band derived after income is finalised.
    df["income_bracket"] = pd.cut(
        df["income_usd"],
        bins=[0, 30_000, 50_000, 75_000, 100_000, 150_000, np.inf],
        labels=["<30k", "30-50k", "50-75k", "75-100k", "100-150k", "150k+"],
    ).astype(str)

    df[_SCORE_COLUMNS] = df[_SCORE_COLUMNS].round(3)
    return df


# ===========================================================================
# Persistence
# ===========================================================================

def save_personas(df: pd.DataFrame, path: Path = PERSONA_FILE) -> Path:
    """Write the persona DataFrame to CSV and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def load_personas(path: Path = PERSONA_FILE) -> pd.DataFrame:
    """Load a previously saved persona CSV.

    Raises
    ------
    FileNotFoundError
        If no persona file exists yet -- run ``generate_personas`` first.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"No persona file at {path}. Run `python src/personas.py` first."
        )
    return pd.read_csv(path)


# ===========================================================================
# Audience segmentation (used by the Gradio UI's segment selector)
# ===========================================================================

# Each segment maps to a predicate over the persona DataFrame. Extend freely.
AUDIENCE_SEGMENTS = {
    "all": lambda df: pd.Series(True, index=df.index),
    "gen_z": lambda df: df["age"] <= 27,
    "millennials": lambda df: df["age"].between(28, 43),
    "gen_x": lambda df: df["age"].between(44, 59),
    "boomers": lambda df: df["age"] >= 60,
    "high_income": lambda df: df["income_usd"] >= 90_000,
    "budget_conscious": lambda df: df["price_consciousness"] >= 0.60,
    "early_adopters": lambda df: df["innovativeness"] >= 0.60,
    "socially_influenced": lambda df: df["social_susceptibility"] >= 0.60,
}


def filter_personas(df: pd.DataFrame, segment: str = "all") -> pd.DataFrame:
    """Return the subset of ``df`` matching a named audience segment."""
    if segment not in AUDIENCE_SEGMENTS:
        raise KeyError(
            f"Unknown segment '{segment}'. "
            f"Choose from: {sorted(AUDIENCE_SEGMENTS)}"
        )
    mask = AUDIENCE_SEGMENTS[segment](df)
    return df.loc[mask].reset_index(drop=True)


# ===========================================================================
# Reporting
# ===========================================================================

def summarize_personas(df: pd.DataFrame) -> str:
    """Return a short human-readable summary of a persona population."""
    ocean = ["openness", "conscientiousness", "extraversion",
             "agreeableness", "neuroticism"]
    top_platforms = df["primary_platform"].value_counts(normalize=True).head(3)
    edu_mix = df["education"].value_counts(normalize=True)
    lines = [
        f"Personas:        {len(df):,}",
        f"Age:             mean {df['age'].mean():.1f}, "
        f"range {df['age'].min()}-{df['age'].max()}",
        f"Income (USD):    median ${df['income_usd'].median():,.0f}, "
        f"mean ${df['income_usd'].mean():,.0f}",
        f"Gender mix:      " + ", ".join(
            f"{k} {v:.0%}" for k, v in
            df['gender'].value_counts(normalize=True).items()),
        f"Education mix:   " + ", ".join(
            f"{k} {v:.0%}" for k, v in edu_mix.items()),
        f"Top platforms:   " + ", ".join(
            f"{k} {v:.0%}" for k, v in top_platforms.items()),
        f"Big Five means:  " + ", ".join(
            f"{t[:4].upper()} {df[t].mean():.2f}" for t in ocean),
        f"Mean purchase freq/mo: {df['purchase_frequency'].mean():.1f}, "
        f"mean AOV ${df['avg_order_value'].mean():,.0f}",
    ]
    return "\n".join(lines)


# ===========================================================================
# CLI entry point
# ===========================================================================

def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic personas for the ad-simulator."
    )
    parser.add_argument("--count", type=int, default=DEFAULT_PERSONA_COUNT,
                        help="number of personas (500-2000 recommended)")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED,
                        help="RNG seed for reproducibility")
    parser.add_argument("--out", type=Path, default=PERSONA_FILE,
                        help="output CSV path")
    args = parser.parse_args()

    df = generate_personas(n=args.count, seed=args.seed)
    path = save_personas(df, args.out)
    print(summarize_personas(df))
    print(f"\nSaved {len(df):,} personas -> {path}")


if __name__ == "__main__":
    _main()
