"""Mesa consumer agent for the ad simulation.

Each :class:`AdConsumerAgent` wraps one synthetic persona. When stepped, an
exposed agent runs a two-stage funnel:

    exposure -> click? -> (if clicked) buy?

Probability model
-----------------
Both click and conversion probabilities are assembled on the **logit scale**
and squashed with a sigmoid, so the result is always a valid probability.
This matches the calibration module, whose psychology weights are logit-scale.

    click_logit = base_rate(channel)
                + visual_scores . visual_weights
                + persona_match (category / channel / receptivity)
                + psychology_rules (calibrated weight x persona modulation)
                + word_of_mouth
                + ad_fatigue
    click_prob  = sigmoid(click_logit)

The psychology term is the interesting ABM bit: the *population-average*
weight comes from calibration, but each persona modulates it (a scarcity
appeal lands harder on an impulsive agent than a conscientious one). The
modulation is centred on 1.0, so the population-average effect still equals
the calibrated weight.

Design for testability
----------------------
All scoring lives in pure module-level functions
(:func:`compute_click_probability`, :func:`compute_conversion_probability`)
that take plain dicts and return a :class:`ProbabilityBreakdown`. The Mesa
agent is a thin wrapper. Mesa is imported gracefully, so these pure functions
can be imported and unit-tested even where Mesa is not installed.

Limitations
-----------
The visual weights and funnel constants below are reasoned defaults grounded
in advertising principles, NOT calibrated from data (no public dataset links
analysed ad images to outcomes). Only the psychology-rule weights are
data-calibrated. Treat absolute probabilities as directional.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Allow `python src/agent.py` to find config.py in the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import PSYCHOLOGY_FEATURES, VISUAL_SCORE_KEYS  # noqa: E402

try:
    from src.data_loader import BENCHMARK_BASE_RATES, tag_creative_features
except ImportError:  # when run as `python src/agent.py`
    from data_loader import BENCHMARK_BASE_RATES, tag_creative_features

# Mesa is imported gracefully: if it is missing (e.g. on an older Python),
# the pure scoring functions below can still be imported and tested.
try:
    from mesa import Agent as _MesaAgent
    _MESA_AVAILABLE = True
except ImportError:
    _MesaAgent = object
    _MESA_AVAILABLE = False

__all__ = [
    "AdStimulus",
    "ProbabilityBreakdown",
    "AdConsumerAgent",
    "compute_click_probability",
    "compute_conversion_probability",
    "base_logit_for_channel",
    "DEFAULT_VISUAL_WEIGHTS",
]


# ===========================================================================
# Tunable model constants (reasoned defaults -- not data-calibrated)
# ===========================================================================

# Logit weight applied to each 0-1 visual score. Attention and emotion drive
# the click; clarity and relevance-potential matter but less at the click.
DEFAULT_VISUAL_WEIGHTS = {
    "emotional_arousal": 0.35,
    "visual_clarity": 0.25,
    "attention_capture": 0.45,
    "relevance_potential": 0.40,
}

# Conversion (buy | click) base rate -- a typical post-click conversion of
# ~10% expressed on the logit scale.
DEFAULT_CONVERSION_BASE_LOGIT = math.log(0.10 / 0.90)

# Ad fatigue / banner blindness: each prior exposure shaves the click logit.
FATIGUE_PER_EXPOSURE = 0.10
FATIGUE_CAP = 8

# Word-of-mouth: a unit of social influence is scaled by how susceptible the
# persona is to it.
WOM_BASE_SCALE = 0.5

# Plausibility guardrails (guardrails, NOT measured effects): bound how far a
# single creative can move CTR / conversion away from the channel benchmark.
# Without this, the additive visual + psychology + persona-match terms stack
# into fantasy uplifts -- a merely-good ad computing ~4x the benchmark CTR and
# a 20x+ ROAS. These caps keep the directional forecast inside a believable
# band while preserving the relative ordering (weak < neutral < strong).
#
# Logit scale, applied to the deviation from the anchored benchmark. Clicks and
# conversion get DIFFERENT caps on purpose: a strong creative can roughly
# double click-through, but it has far less leverage over post-click
# conversion -- that is driven mostly by price, product and landing page, none
# of which the creative analysis can even see. A creative can also fail harder
# than it can win, so the downside drag is looser than the upside.
#   click uplift +0.7 ~ 2.0x odds  | drag -2.0 ~ 0.13x
#   conv  uplift +0.5 ~ 1.6x odds  | drag -1.2 ~ 0.30x
CLICK_MAX_LOGIT_UPLIFT = 0.7
CLICK_MAX_LOGIT_DRAG = 2.0
CONV_MAX_LOGIT_UPLIFT = 0.5
CONV_MAX_LOGIT_DRAG = 1.2

# How a product category maps onto persona interest tags (soft fit).
_CATEGORY_INTEREST_HINTS = {
    "apparel": {"fashion"},
    "electronics": {"tech", "gaming"},
    "beauty": {"beauty", "fashion"},
    "home": {"diy", "cooking"},
    "food_bev": {"cooking"},
    "fitness": {"fitness", "outdoors", "sports"},
    "travel": {"travel", "outdoors"},
    "finance": {"finance"},
    "auto": {"cars"},
    "entertainment": {"movies", "music", "gaming", "reading"},
}

# Which persona platforms count as "on channel" for channel-fit.
CHANNEL_PLATFORMS = {
    "social_feed": {"tiktok", "instagram", "facebook", "linkedin"},
    "video": {"youtube", "streaming_tv"},
    "display": {"news_sites"},
    "search": set(),    # intent-driven -- persona platform is not relevant
    "email": set(),
}


# ===========================================================================
# Numeric helpers
# ===========================================================================

def _sigmoid(x: float) -> float:
    """Numerically stable scalar logistic function."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def _logit(p: float) -> float:
    """Inverse logistic; input clamped away from 0 and 1."""
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _get(persona: dict, key: str, default: float = 0.5) -> float:
    """Read a numeric persona attribute with a neutral default."""
    val = persona.get(key, default)
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def base_logit_for_channel(channel: str) -> float:
    """Return the logit-scale base CTR for a marketing channel."""
    ctr = BENCHMARK_BASE_RATES.get(channel, BENCHMARK_BASE_RATES["social_feed"])
    return _logit(ctr)


# ===========================================================================
# Ad stimulus
# ===========================================================================

@dataclass
class AdStimulus:
    """Everything the agents react to: one ad creative in one channel."""
    visual_scores: dict          # 4 VISUAL_SCORE_KEYS, each 0-1
    psychology_features: dict    # 4 PSYCHOLOGY_FEATURES, each 0-1
    product_category: str = "general"
    channel: str = "social_feed"
    ad_text: str = ""

    def __post_init__(self):
        # Fill any missing keys so downstream maths never KeyErrors.
        self.visual_scores = {k: float(self.visual_scores.get(k, 0.5))
                              for k in VISUAL_SCORE_KEYS}
        self.psychology_features = {
            k: float(self.psychology_features.get(k, 0.0))
            for k in PSYCHOLOGY_FEATURES}

    @classmethod
    def build(cls, visual_scores: dict, ad_text: str = "",
              product_category: str = "general",
              channel: str = "social_feed") -> "AdStimulus":
        """Construct from visual scores + raw copy.

        Psychology features are derived from the copy via the shared keyword
        tagger, so callers only need the visual scores and the text.
        """
        return cls(
            visual_scores=visual_scores,
            psychology_features=tag_creative_features(ad_text),
            product_category=product_category,
            channel=channel,
            ad_text=ad_text,
        )


# ===========================================================================
# Probability breakdown
# ===========================================================================

@dataclass
class ProbabilityBreakdown:
    """A computed probability plus its additive logit contributions.

    ``contributions`` holds the named top-level terms; ``detail`` holds the
    per-feature decomposition. Both feed the explanation module.
    """
    probability: float
    total_logit: float
    contributions: dict
    detail: dict = field(default_factory=dict)

    def top_factors(self, n: int = 3) -> list:
        """Return the n largest-magnitude contributions (excluding 'base')."""
        items = [(k, v) for k, v in self.contributions.items() if k != "base"]
        items.sort(key=lambda kv: abs(kv[1]), reverse=True)
        return items[:n]


# ===========================================================================
# Persona <-> ad fit helpers
# ===========================================================================

def _category_fit(persona: dict, ad: AdStimulus) -> float:
    """Raw logit fit between an ad's category and a persona's tastes."""
    cat = ad.product_category
    if cat in ("", "general"):
        return 0.0                                   # neutral, untargeted
    if cat == persona.get("primary_category"):
        return 0.60                                  # bullseye
    interests = set(str(persona.get("interests", "")).split(";"))
    if cat in interests:
        return 0.35
    if interests & _CATEGORY_INTEREST_HINTS.get(cat, set()):
        return 0.30                                  # soft interest match
    return -0.20                                     # unrelated category


def _channel_fit(persona: dict, ad: AdStimulus) -> float:
    """Raw logit fit between an ad's channel and a persona's media habits."""
    platforms = CHANNEL_PLATFORMS.get(ad.channel, set())
    if not platforms:                                # search / email: neutral
        return 0.0
    return 0.30 if persona.get("primary_platform") in platforms else -0.18


def _psych_modulation(persona: dict, feature: str) -> float:
    """Per-persona multiplier on a psychology rule's population weight.

    Centred on ~1.0 so the population-average effect equals the calibrated
    weight, but heterogeneous: a rule lands harder on receptive personas.
    """
    if feature == "emotional_appeal":
        # Emotion lands on the open and the emotionally reactive.
        drive = 0.5 * _get(persona, "openness") + \
            0.5 * _get(persona, "neuroticism")
        return _clip(0.60 + 0.80 * drive, 0.4, 1.6)
    if feature == "scarcity":
        # Urgency lands on the impulsive and the less self-controlled.
        drive = (_get(persona, "impulsivity")
                 + _get(persona, "neuroticism")
                 + (1 - _get(persona, "conscientiousness"))) / 3
        return _clip(0.60 + 0.80 * drive, 0.4, 1.6)
    if feature == "social_proof":
        # "Everyone loves it" lands on the agreeable and socially attuned.
        drive = (_get(persona, "agreeableness")
                 + _get(persona, "extraversion")
                 + _get(persona, "social_susceptibility")) / 3
        return _clip(0.60 + 0.80 * drive, 0.4, 1.6)
    # relevance: matters fairly universally; skeptical/careful personas
    # reward a clear value proposition slightly more.
    drive = 0.5 * _get(persona, "ad_skepticism") + \
        0.5 * _get(persona, "conscientiousness")
    return _clip(0.85 + 0.30 * drive, 0.7, 1.3)


# ===========================================================================
# Pure scoring functions
# ===========================================================================

def compute_click_probability(persona: dict,
                               ad: AdStimulus,
                               calibration,
                               base_logit: float,
                               visual_weights: dict | None = None,
                               social_influence: float = 0.0,
                               prior_exposures: int = 0,
                               anchor_logit: float | None = None
                               ) -> ProbabilityBreakdown:
    """Probability that ``persona`` clicks ``ad`` on a single exposure.

    ``calibration`` is any object exposing a ``coefficients`` dict mapping
    each psychology feature to its logit weight (see ``calibration.py``).

    ``anchor_logit`` is the anchored benchmark click logit. When supplied, the
    creative's deviation from it is clamped to a believable band (see
    ``MAX_CREATIVE_LOGIT_*``) so a strong creative can't compute a fantasy CTR.
    Leave it None (the default) to measure raw contributions -- the benchmark
    anchoring itself relies on the unclamped value.
    """
    vw = visual_weights or DEFAULT_VISUAL_WEIGHTS

    # --- Visual contribution ----------------------------------------------
    visual_detail = {k: ad.visual_scores[k] * vw.get(k, 0.0)
                     for k in VISUAL_SCORE_KEYS}
    visual_logit = sum(visual_detail.values())

    # --- Persona match ----------------------------------------------------
    match_detail = {
        "category_fit": _category_fit(persona, ad),
        "channel_fit": _channel_fit(persona, ad),
        "ad_receptivity": (_get(persona, "ad_receptivity") - 0.5) * 0.80,
        "ad_skepticism": -(_get(persona, "ad_skepticism") - 0.5) * 0.70,
    }
    match_logit = sum(match_detail.values())

    # --- Psychology rules (calibrated weight x persona modulation) --------
    psych_detail = {}
    for feat in PSYCHOLOGY_FEATURES:
        weight = float(getattr(calibration, "coefficients", {}).get(feat, 0.0))
        modulation = _psych_modulation(persona, feat)
        psych_detail[feat] = ad.psychology_features[feat] * weight * modulation
    psych_logit = sum(psych_detail.values())

    # --- Word-of-mouth ----------------------------------------------------
    wom_logit = social_influence * (
        WOM_BASE_SCALE + _get(persona, "social_susceptibility"))

    # --- Ad fatigue -------------------------------------------------------
    fatigue_logit = -FATIGUE_PER_EXPOSURE * min(prior_exposures, FATIGUE_CAP)

    total = (base_logit + visual_logit + match_logit + psych_logit
             + wom_logit + fatigue_logit)

    # Plausibility clamp: bound the creative's deviation from the benchmark so
    # the directional forecast stays in a believable range.
    clamp_adjust = 0.0
    if anchor_logit is not None:
        deviation = total - anchor_logit
        clamped = max(-CLICK_MAX_LOGIT_DRAG,
                      min(CLICK_MAX_LOGIT_UPLIFT, deviation))
        clamp_adjust = clamped - deviation        # 0 unless we hit a cap
        total += clamp_adjust

    contributions = {
        "base": base_logit,
        "visual": visual_logit,
        "persona_match": match_logit,
        "psychology": psych_logit,
        "word_of_mouth": wom_logit,
        "fatigue": fatigue_logit,
    }
    if clamp_adjust:
        contributions["plausibility_cap"] = clamp_adjust
    return ProbabilityBreakdown(
        probability=_sigmoid(total),
        total_logit=total,
        contributions=contributions,
        detail={
            "visual": visual_detail,
            "persona_match": match_detail,
            "psychology": psych_detail,
        },
    )


def compute_conversion_probability(persona: dict,
                                   ad: AdStimulus,
                                   base_logit: float | None = None,
                                   anchor_logit: float | None = None
                                   ) -> ProbabilityBreakdown:
    """Probability of a purchase GIVEN a click (post-click conversion).

    Driven by the persona's buying disposition and by ad cues that build
    purchase confidence (relevance, clarity, social proof, deal appeal).

    ``anchor_logit`` (the anchored benchmark conversion logit), when supplied,
    clamps the creative's deviation to a believable band -- same plausibility
    guardrail as the click model.
    """
    base = (DEFAULT_CONVERSION_BASE_LOGIT if base_logit is None
            else base_logit)

    contributions = {
        "base": base,
        # Buyer disposition.
        "impulsivity": (_get(persona, "impulsivity") - 0.5) * 0.90,
        "buyer_activity": (min(_get(persona, "purchase_frequency", 4.0), 20)
                           / 20 - 0.30) * 0.80,
        "online_habit": (_get(persona, "online_purchase_ratio") - 0.5) * 0.60,
        # Category relevance to this persona.
        "category_fit": _category_fit(persona, ad) * 0.70,
        # Ad cues that build purchase confidence.
        "ad_relevance": (ad.visual_scores["relevance_potential"] * 0.50
                         + ad.psychology_features["relevance"] * 0.40),
        "ad_clarity": (ad.visual_scores["visual_clarity"] - 0.5) * 0.50,
        "social_proof": ad.psychology_features["social_proof"] * 0.45,
        # Scarcity converts deal-seekers: scarcity x price consciousness.
        "deal_appeal": (ad.psychology_features["scarcity"]
                        * _get(persona, "price_consciousness") * 0.60),
    }
    total = sum(contributions.values())

    if anchor_logit is not None:
        deviation = total - anchor_logit
        clamped = max(-CONV_MAX_LOGIT_DRAG,
                      min(CONV_MAX_LOGIT_UPLIFT, deviation))
        adjust = clamped - deviation
        if adjust:
            contributions["plausibility_cap"] = adjust
            total += adjust

    return ProbabilityBreakdown(
        probability=_sigmoid(total),
        total_logit=total,
        contributions=contributions,
    )


# ===========================================================================
# Mesa agent
# ===========================================================================

class AdConsumerAgent(_MesaAgent):
    """A single synthetic consumer in the simulation.

    The model is expected to expose, as shared state:
        model.ad             -- an AdStimulus
        model.calibration    -- object with a `.coefficients` dict
        model.base_logit     -- logit-scale channel base CTR
        model.visual_weights -- dict of visual logit weights (optional)
        model.random         -- a seeded random.Random

    Each simulated day the model sets ``exposed_today`` on the agents it
    reaches, then steps them; word-of-mouth is applied by the model between
    days via ``social_influence``.
    """

    def __init__(self, model, persona: dict):
        if _MESA_AVAILABLE:
            super().__init__(model)          # Mesa auto-assigns unique_id
        else:                                # graceful path for testing
            self.model = model
        self.persona = dict(persona)

        # Per-run cumulative counters.
        self.times_exposed = 0
        self.total_clicks = 0
        self.total_purchases = 0
        # Sum of per-click conversion probabilities -- gives the model a
        # stable "expected conversions" estimate that doesn't collapse to
        # zero on small Monte Carlo runs where no buyer happened to roll.
        self.expected_conversions_total = 0.0
        # Per-day state (reset / set by the model each step).
        self.exposed_today = False
        self.clicked_today = False
        self.bought_today = False
        self.social_influence = 0.0          # set by the model from neighbours
        self.is_advocate = False             # has bought -> spreads WoM
        # Last computed breakdowns, kept for the explanation module.
        self.last_click_breakdown: ProbabilityBreakdown | None = None
        self.last_conversion_breakdown: ProbabilityBreakdown | None = None

    def step(self) -> None:
        """Run one simulated day for this agent."""
        self.clicked_today = False
        self.bought_today = False
        if not self.exposed_today:
            return

        model = self.model
        click = compute_click_probability(
            self.persona, model.ad, model.calibration, model.base_logit,
            visual_weights=getattr(model, "visual_weights", None),
            social_influence=self.social_influence,
            prior_exposures=self.times_exposed,
            anchor_logit=getattr(model, "_click_anchor_logit", None),
        )
        self.last_click_breakdown = click
        self.times_exposed += 1

        if model.random.random() < click.probability:
            self.clicked_today = True
            self.total_clicks += 1
            conv = compute_conversion_probability(
                self.persona, model.ad,
                base_logit=getattr(model, "conversion_base_logit", None),
                anchor_logit=getattr(model, "_conv_anchor_logit", None),
            )
            self.last_conversion_breakdown = conv
            self.expected_conversions_total += conv.probability
            if model.random.random() < conv.probability:
                self.bought_today = True
                self.total_purchases += 1
                self.is_advocate = True


# ===========================================================================
# CLI demo
# ===========================================================================

def _main() -> None:
    # A representative persona (mirrors a row of personas.csv).
    persona = {
        "age": 29, "income_usd": 64000, "primary_platform": "instagram",
        "primary_category": "beauty", "interests": "fashion;beauty;travel",
        "openness": 0.62, "conscientiousness": 0.41, "extraversion": 0.58,
        "agreeableness": 0.55, "neuroticism": 0.60, "impulsivity": 0.66,
        "ad_receptivity": 0.64, "ad_skepticism": 0.38,
        "social_susceptibility": 0.71, "price_consciousness": 0.58,
        "online_purchase_ratio": 0.73, "purchase_frequency": 7,
    }

    class _Calib:  # minimal stand-in for a CalibrationResult
        coefficients = {"emotional_appeal": 0.60, "scarcity": 0.35,
                        "social_proof": 0.50, "relevance": 0.70}

    ad = AdStimulus.build(
        visual_scores={"emotional_arousal": 0.7, "visual_clarity": 0.8,
                       "attention_capture": 0.75, "relevance_potential": 0.65},
        ad_text="Limited offer! Save 40% today -- loved by thousands.",
        product_category="beauty", channel="social_feed",
    )

    base = base_logit_for_channel(ad.channel)
    click = compute_click_probability(persona, ad, _Calib(), base)
    conv = compute_conversion_probability(persona, ad)

    print(f"Channel base CTR: {_sigmoid(base):.4f}  (logit {base:+.2f})\n")
    print(f"CLICK probability:      {click.probability:.4f}")
    for name, val in click.contributions.items():
        print(f"  {name:<16s} {val:+.3f}")
    print(f"  -> total logit {click.total_logit:+.3f}")
    print("  top factors:", [(k, round(v, 3))
                              for k, v in click.top_factors()])

    print(f"\nCONVERSION probability (buy|click): {conv.probability:.4f}")
    for name, val in conv.contributions.items():
        print(f"  {name:<16s} {val:+.3f}")

    joint = click.probability * conv.probability
    print(f"\nJoint buy probability per exposure: {joint:.5f}")
    print(f"Mesa available: {_MESA_AVAILABLE}")


if __name__ == "__main__":
    _main()
