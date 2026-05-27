"""Mesa model: the ad-campaign simulation.

:class:`AdSimulationModel` builds a population of :class:`AdConsumerAgent`s
from synthetic personas, wires them into a NetworkX social graph for
word-of-mouth, and runs the campaign day by day.

Each simulated day:
  1. Word-of-mouth influence from previous days decays.
  2. A budget-driven subset of the audience is exposed to the ad today
     (exposure is weighted by how much media each persona consumes).
  3. Every exposed agent runs its click -> buy funnel.
  4. Agents who bought (advocates) -- and, more weakly, those who clicked --
     push word-of-mouth influence to their network neighbours for tomorrow.
  5. Daily metrics are recorded.

Sample vs. real campaign
------------------------
The synthetic audience is a *representative sample* of the target market, so
the model's headline outputs are RATES (CTR, conversion rate). Turning those
rates into absolute clicks / conversions / ROI for a real budget is done in
``simulation.py`` -- this module deliberately stays rate-focused.

Mesa is imported gracefully (same pattern as ``agent.py``) so the model can
be exercised even where Mesa is not installed; it is a genuine ``mesa.Model``
with genuine ``mesa.Agent``s whenever Mesa is present.
"""
from __future__ import annotations

import math
import random
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np

# Allow `python src/model.py` to find config.py in the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import (  # noqa: E402
    DEFAULT_SIM_DAYS, PSYCHOLOGY_FEATURES, VISUAL_SCORE_KEYS,
)

try:
    from src.agent import (AdConsumerAgent, AdStimulus,  # noqa: F401
                           DEFAULT_CONVERSION_BASE_LOGIT,
                           base_logit_for_channel,
                           compute_click_probability,
                           compute_conversion_probability)
except ImportError:  # when run as `python src/model.py`
    from agent import (AdConsumerAgent, AdStimulus,  # noqa: F401
                       DEFAULT_CONVERSION_BASE_LOGIT,
                       base_logit_for_channel,
                       compute_click_probability,
                       compute_conversion_probability)

try:
    from mesa import Model as _MesaModel
    _MESA_AVAILABLE = True
except ImportError:
    _MesaModel = object
    _MESA_AVAILABLE = False

__all__ = ["AdSimulationModel", "SimulationResults"]


# ===========================================================================
# Word-of-mouth constants (tunable)
# ===========================================================================

WOM_DECAY = 0.50            # daily decay of accumulated social influence
WOM_ADVOCATE_SPREAD = 0.50  # logit influence a buyer pushes to each neighbour
WOM_CLICKER_SPREAD = 0.15   # smaller push from a non-buying clicker
WOM_INFLUENCE_CAP = 2.50    # ceiling on a single agent's social influence
# A click counts as "WoM-assisted" only when the social-influence logit
# contribution at click time exceeded this threshold (a small but real nudge:
# ~5% relative click-prob uplift). Stricter thresholds zero out the metric
# on short / small-audience runs even when WoM is flowing.
WOM_ASSIST_THRESHOLD = 0.05


# ===========================================================================
# Results container
# ===========================================================================

@dataclass
class SimulationResults:
    """Outcome of one full model run (one campaign, one random seed)."""
    daily_records: list                # list of per-day metric dicts
    n_agents: int
    sim_days: int
    channel: str
    total_exposures: int
    total_clicks: int
    total_purchases: int
    ctr: float                         # clicks / exposures
    conversion_rate: float             # purchases / clicks (empirical)
    expected_conversion_rate: float    # mean of per-click conversion probs
    buy_rate: float                    # purchases / exposures
    n_unique_buyers: int
    mean_buyer_aov: float
    wom_assisted_clicks: int           # clicks by agents carrying WoM influence
    network_avg_degree: float
    aggregate_click_factors: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        wom_pct = (self.wom_assisted_clicks / self.total_clicks * 100
                   if self.total_clicks else 0.0)
        return "\n".join([
            f"Campaign simulation -- {self.channel}, {self.sim_days} days, "
            f"{self.n_agents:,} agents",
            "-" * 56,
            f"  exposures        {self.total_exposures:,}",
            f"  clicks           {self.total_clicks:,}  "
            f"(CTR {self.ctr:.4f})",
            f"  purchases        {self.total_purchases:,}  "
            f"(conv {self.conversion_rate:.4f} of clicks)",
            f"  unique buyers    {self.n_unique_buyers:,}  "
            f"(mean AOV ${self.mean_buyer_aov:,.0f})",
            f"  WoM-assisted     {self.wom_assisted_clicks:,} clicks "
            f"({wom_pct:.1f}%)",
            f"  network degree   {self.network_avg_degree:.1f} avg connections",
        ])


# ===========================================================================
# The model
# ===========================================================================

class AdSimulationModel(_MesaModel):
    """One ad campaign run over a synthetic audience."""

    def __init__(self, personas, ad: AdStimulus, calibration, *,
                 channel: str | None = None,
                 daily_reach: float = 0.35,
                 sim_days: int = DEFAULT_SIM_DAYS,
                 network_type: str = "small_world",
                 avg_connections: int = 6,
                 rewire_p: float = 0.10,
                 visual_weights: dict | None = None,
                 anchor_to_benchmark: bool = True,
                 target_ctr: float | None = None,
                 target_conversion_rate: float | None = 0.025,
                 seed: int | None = None):
        """
        Parameters
        ----------
        personas : DataFrame of synthetic personas (already segment-filtered).
        ad : the AdStimulus all agents react to.
        calibration : object exposing a ``coefficients`` dict (calibration.py).
        channel : marketing channel; defaults to ``ad.channel``.
        daily_reach : fraction of the audience exposed each day (0-1).
        sim_days : number of simulated campaign days.
        network_type : 'small_world' (Watts-Strogatz) or 'scale_free'
            (Barabasi-Albert, with influencer hubs).
        avg_connections : target average node degree in the social graph.
        rewire_p : Watts-Strogatz rewiring probability.
        visual_weights : optional override of the agent visual logit weights.
        anchor_to_benchmark : if True (default), shifts ``base_logit`` so the
            audience's mean predicted click probability matches the channel
            benchmark CTR. Without this, the always-positive visual +
            psychology terms would inflate absolute CTRs above realistic
            ranges; with it, weak/strong creatives deviate around the
            benchmark instead of stacking on top of it.
        target_ctr : optional explicit click anchor (e.g. an expected
            category CTR); defaults to the channel's benchmark.
        target_conversion_rate : when anchoring, the post-click conversion
            rate the average persona/neutral ad should land at. Default
            0.025 (2.5%) is a directional cross-vertical mid-range; pass an
            explicit value for higher-converting categories. Set to None to
            disable conversion anchoring while keeping click anchoring.
        seed : RNG seed for reproducibility.
        """
        if _MESA_AVAILABLE:
            super().__init__(seed=seed)        # creates a seeded self.random
        else:
            self.random = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)

        if len(personas) < 2:
            raise ValueError("Need at least 2 personas to simulate.")
        if not 0.0 < daily_reach <= 1.0:
            raise ValueError("daily_reach must be in (0, 1].")

        # --- Shared state the agents read --------------------------------
        self.ad = ad
        self.calibration = calibration
        self.channel = channel or ad.channel
        self.base_logit = base_logit_for_channel(self.channel)
        self.visual_weights = visual_weights
        self.daily_reach = daily_reach
        self.sim_days = sim_days

        # --- Build the agent population ----------------------------------
        self.consumer_agents = [
            AdConsumerAgent(self, row) for row in personas.to_dict("records")
        ]
        self.n_agents = len(self.consumer_agents)

        # Exposure is weighted by media consumption: heavier media users are
        # more likely to be served an impression on any given day.
        minutes = np.array([a.persona.get("daily_media_minutes", 180)
                            for a in self.consumer_agents], dtype=float)
        spread = np.ptp(minutes)
        media_norm = (minutes - minutes.min()) / spread if spread > 0 \
            else np.full(self.n_agents, 0.5)
        weights = 0.4 + 0.6 * media_norm
        self._exposure_weights = weights / weights.sum()

        # --- Build the social network ------------------------------------
        self.social_graph = self._build_network(network_type, avg_connections,
                                                 rewire_p, seed)
        self.neighbors = {
            self.consumer_agents[i]: [self.consumer_agents[j]
                                      for j in self.social_graph.neighbors(i)]
            for i in range(self.n_agents)
        }
        degrees = [d for _, d in self.social_graph.degree()]
        self.network_avg_degree = float(np.mean(degrees)) if degrees else 0.0

        # --- Anchor base CTR to the channel benchmark --------------------
        if anchor_to_benchmark:
            if target_ctr is None:
                target_logit = self.base_logit          # current = channel base
            else:
                if not 0.0 < target_ctr < 1.0:
                    raise ValueError("target_ctr must be in (0, 1).")
                target_logit = math.log(target_ctr / (1 - target_ctr))
            self._anchor_base_logit(target_logit)
        self.is_anchored = bool(anchor_to_benchmark)

        # --- Anchor the conversion model too ---------------------------
        # Same logic for buy|click: an average persona on a neutral creative
        # should convert at the benchmark conversion rate (default 2.5%).
        # Without this, the always-positive conversion contributions inflate
        # buy rates to ~25%+ and ROAS becomes unrealistic.
        self.conversion_base_logit = DEFAULT_CONVERSION_BASE_LOGIT
        if anchor_to_benchmark and target_conversion_rate is not None:
            if not 0.0 < target_conversion_rate < 1.0:
                raise ValueError("target_conversion_rate must be in (0, 1).")
            conv_target_logit = math.log(
                target_conversion_rate / (1 - target_conversion_rate))
            self._anchor_conversion_base_logit(conv_target_logit)

        # --- Run state ---------------------------------------------------
        self.current_day = 0
        self.daily_records: list = []
        self._cum_exposures = 0
        self._cum_clicks = 0
        self._cum_purchases = 0
        self._cum_wom_clicks = 0

    # ----------------------------------------------------------------------
    # Network construction
    # ----------------------------------------------------------------------

    def _build_network(self, network_type: str, avg_connections: int,
                       rewire_p: float, seed: int | None) -> nx.Graph:
        """Construct the social graph; node i corresponds to agent i."""
        n = self.n_agents
        if network_type == "scale_free":
            m = max(1, min(avg_connections // 2, n - 1))
            return nx.barabasi_albert_graph(n, m, seed=seed)
        # default: small-world (Watts-Strogatz). k must be even and < n.
        k = min(avg_connections, n - 1)
        if k % 2 == 1:
            k -= 1
        k = max(k, 2) if n > 2 else max(k, 1)
        k = min(k, n - 1)
        return nx.watts_strogatz_graph(n, k, rewire_p, seed=seed)

    def _anchor_base_logit(self, target_logit: float) -> None:
        """Shift ``base_logit`` so an *average* creative on this audience
        predicts the benchmark CTR -- not the actual ad.

        Anchoring on the actual ad would erase the comparison signal (every
        ad would be rescaled to the same headline). Instead we build a
        NEUTRAL reference creative (mid-range visual scores, calibrated-mean
        psychology features, untargeted category, same channel), find the
        audience's mean contribution to that, and shift the base accordingly.
        The actual ad's strengths and weaknesses then move CTR up or down
        from the benchmark -- so relative comparisons stay valid and absolute
        numbers become credible.
        """
        # Use the calibrated population mean for psychology features when the
        # calibration provides them, else a neutral 0.4.
        psych_means = (getattr(self.calibration, "mean_features", None)
                       or {k: 0.4 for k in PSYCHOLOGY_FEATURES})
        reference = AdStimulus(
            visual_scores={k: 0.5 for k in VISUAL_SCORE_KEYS},
            psychology_features={k: float(psych_means.get(k, 0.4))
                                 for k in PSYCHOLOGY_FEATURES},
            product_category="general",                 # neutral category fit
            channel=self.ad.channel,
        )
        contribs = []
        for agent in self.consumer_agents:
            breakdown = compute_click_probability(
                agent.persona, reference, self.calibration, self.base_logit,
                visual_weights=self.visual_weights,
                social_influence=0.0, prior_exposures=0,
            )
            contribs.append(breakdown.total_logit - self.base_logit)
        mean_contrib = float(np.mean(contribs)) if contribs else 0.0
        self.base_logit = target_logit - mean_contrib

    def _anchor_conversion_base_logit(self, target_logit: float) -> None:
        """Shift ``conversion_base_logit`` so a neutral creative converts at
        the benchmark conversion rate on this audience. Same anchoring
        philosophy as the click base, applied to the buy-given-click model.
        """
        psych_means = (getattr(self.calibration, "mean_features", None)
                       or {k: 0.4 for k in PSYCHOLOGY_FEATURES})
        reference = AdStimulus(
            visual_scores={k: 0.5 for k in VISUAL_SCORE_KEYS},
            psychology_features={k: float(psych_means.get(k, 0.4))
                                 for k in PSYCHOLOGY_FEATURES},
            product_category="general",
            channel=self.ad.channel,
        )
        contribs = []
        for agent in self.consumer_agents:
            breakdown = compute_conversion_probability(
                agent.persona, reference,
                base_logit=self.conversion_base_logit,
            )
            contribs.append(breakdown.total_logit - self.conversion_base_logit)
        mean_contrib = float(np.mean(contribs)) if contribs else 0.0
        self.conversion_base_logit = target_logit - mean_contrib

    # ----------------------------------------------------------------------
    # Daily step
    # ----------------------------------------------------------------------

    def _assign_exposure(self) -> None:
        """Pick which agents see the ad today (media-weighted, no replacement)."""
        for agent in self.consumer_agents:
            agent.exposed_today = False
        n_expose = min(self.n_agents,
                       max(1, round(self.daily_reach * self.n_agents)))
        chosen = self.np_rng.choice(self.n_agents, size=n_expose,
                                    replace=False, p=self._exposure_weights)
        for i in chosen:
            self.consumer_agents[i].exposed_today = True

    def _propagate_word_of_mouth(self) -> None:
        """Buyers (and, weakly, clickers) push influence to their neighbours."""
        for agent in self.consumer_agents:
            if agent.bought_today:
                spread = WOM_ADVOCATE_SPREAD
            elif agent.clicked_today:
                spread = WOM_CLICKER_SPREAD
            else:
                continue
            for neighbour in self.neighbors[agent]:
                neighbour.social_influence = min(
                    neighbour.social_influence + spread, WOM_INFLUENCE_CAP)

    def _record_day(self) -> None:
        """Tally and store this day's metrics."""
        exposed = sum(a.exposed_today for a in self.consumer_agents)
        clicks = sum(a.clicked_today for a in self.consumer_agents)
        purchases = sum(a.bought_today for a in self.consumer_agents)
        # A click counts as WoM-assisted only when the word-of-mouth logit
        # contribution at click time was material (not just any background
        # trickle of influence), so the metric stays meaningful even after
        # the network has saturated.
        wom_clicks = sum(
            1 for a in self.consumer_agents
            if a.clicked_today and a.last_click_breakdown is not None
            and a.last_click_breakdown.contributions.get(
                "word_of_mouth", 0.0) >= WOM_ASSIST_THRESHOLD
        )

        self._cum_exposures += exposed
        self._cum_clicks += clicks
        self._cum_purchases += purchases
        self._cum_wom_clicks += wom_clicks
        self.daily_records.append({
            "day": self.current_day,
            "exposed": exposed,
            "clicks": clicks,
            "purchases": purchases,
            "cumulative_exposures": self._cum_exposures,
            "cumulative_clicks": self._cum_clicks,
            "cumulative_purchases": self._cum_purchases,
            "advocates": sum(a.is_advocate for a in self.consumer_agents),
        })

    def step(self) -> None:
        """Advance the simulation by one day."""
        self.current_day += 1
        # 1. Word-of-mouth decays before today's decisions.
        for agent in self.consumer_agents:
            agent.social_influence *= WOM_DECAY
        # 2. Choose today's exposed audience.
        self._assign_exposure()
        # 3. Step agents in random order (no positional bias).
        order = list(self.consumer_agents)
        self.random.shuffle(order)
        for agent in order:
            agent.step()
        # 4. Spread word-of-mouth for tomorrow; 5. record metrics.
        self._propagate_word_of_mouth()
        self._record_day()

    # ----------------------------------------------------------------------
    # Running + results
    # ----------------------------------------------------------------------

    def aggregate_click_factors(self) -> dict:
        """Mean logit contribution per term across agents that were scored.

        Feeds the explanation module's "why this ad performs" narrative.
        """
        totals: dict = {}
        count = 0
        for agent in self.consumer_agents:
            breakdown = agent.last_click_breakdown
            if breakdown is None:
                continue
            count += 1
            for term, value in breakdown.contributions.items():
                totals[term] = totals.get(term, 0.0) + value
        return {k: round(v / count, 4) for k, v in totals.items()} \
            if count else {}

    def build_results(self) -> SimulationResults:
        """Summarise the completed run into a SimulationResults."""
        buyers = [a for a in self.consumer_agents if a.total_purchases > 0]
        # Buyer-mean AOV when observed; otherwise fall back to the audience
        # mean so revenue scaling is well-defined on small Monte Carlo runs.
        all_aovs = [float(a.persona.get("avg_order_value", 0) or 0)
                    for a in self.consumer_agents]
        if buyers:
            mean_aov = float(np.mean([
                float(a.persona.get("avg_order_value", 0) or 0)
                for a in buyers]))
        elif all_aovs:
            mean_aov = float(np.mean(all_aovs))
        else:
            mean_aov = 0.0
        ctr = self._cum_clicks / self._cum_exposures \
            if self._cum_exposures else 0.0
        conv_empirical = self._cum_purchases / self._cum_clicks \
            if self._cum_clicks else 0.0
        # Expected conversion: stable under small samples (does not collapse
        # to 0 when no buyer happens to roll in this run).
        total_expected_conv = sum(a.expected_conversions_total
                                   for a in self.consumer_agents)
        conv_expected = (total_expected_conv / self._cum_clicks
                         if self._cum_clicks else 0.0)
        buy_rate = self._cum_purchases / self._cum_exposures \
            if self._cum_exposures else 0.0
        return SimulationResults(
            daily_records=self.daily_records,
            n_agents=self.n_agents,
            sim_days=self.sim_days,
            channel=self.channel,
            total_exposures=self._cum_exposures,
            total_clicks=self._cum_clicks,
            total_purchases=self._cum_purchases,
            ctr=ctr,
            conversion_rate=conv_empirical,
            expected_conversion_rate=conv_expected,
            buy_rate=buy_rate,
            n_unique_buyers=len(buyers),
            mean_buyer_aov=mean_aov,
            wom_assisted_clicks=self._cum_wom_clicks,
            network_avg_degree=self.network_avg_degree,
            aggregate_click_factors=self.aggregate_click_factors(),
        )

    def run(self) -> SimulationResults:
        """Run all simulated days and return the results."""
        for _ in range(self.sim_days):
            self.step()
        return self.build_results()


# ===========================================================================
# CLI demo
# ===========================================================================

def _main() -> None:
    # Pull in real personas + calibration produced by the earlier modules.
    try:
        from src.personas import filter_personas, load_personas
        from src.calibration import load_calibration, run_calibration
    except ImportError:
        from personas import filter_personas, load_personas
        from calibration import load_calibration, run_calibration

    try:
        personas = load_personas()
    except FileNotFoundError:
        from personas import generate_personas, save_personas
        personas = generate_personas(800)
        save_personas(personas)
    try:
        calibration = load_calibration()
    except FileNotFoundError:
        calibration = run_calibration()

    audience = filter_personas(personas, "millennials")
    print(f"Audience: 'millennials' -> {len(audience)} personas\n")

    ad = AdStimulus.build(
        visual_scores={"emotional_arousal": 0.7, "visual_clarity": 0.8,
                       "attention_capture": 0.75, "relevance_potential": 0.65},
        ad_text="Limited offer! Save 40% today -- loved by thousands.",
        product_category="beauty", channel="social_feed",
    )

    model = AdSimulationModel(audience, ad, calibration,
                              daily_reach=0.35, sim_days=14, seed=42)
    results = model.run()
    print(results.summary())

    print("\nDaily curve (day: exposed/clicks/purchases):")
    for rec in results.daily_records:
        print(f"  d{rec['day']:>2}: {rec['exposed']:>4} / "
              f"{rec['clicks']:>3} / {rec['purchases']:>3}")

    print("\nMean click-logit contributions across the audience:")
    for term, value in results.aggregate_click_factors.items():
        print(f"  {term:<16s} {value:+.3f}")


if __name__ == "__main__":
    _main()
