"""Simulation-based calibration (the approved ABM calibration loop, step 1).

THE PROBLEM. The account's real creative-fatigue decay is fitted from ad
history as lambda: the slope of ln(CTR) on exposure frequency (auction.py).
The engine's fatigue constant theta lives inside a LOGIT — one term summed
with creative, persona-fit and word-of-mouth terms before a sigmoid. Because
the sigmoid is non-linear, pasting lambda into theta produces a simulated
decay that is systematically wrong (usually too shallow: the other logit
terms already push probability toward its ceiling).

THE FIX (method of simulated moments). Don't invert the maths by hand — run
the model itself: guess theta, measure the decay slope the SIMULATION
produces with the same estimator the real fit uses, and bisect until the
simulated slope matches the account's fitted one. The relationship
lambda_sim(theta) is monotonically increasing (more logit decay per exposure
can only steepen observed CTR decay), so bisection is exact and fast.

Provenance contract: theta is only ever derived from a lambda that was
itself fitted (or explicitly set by the user in the Lab); when no lambda is
available the generic FATIGUE_PER_EXPOSURE constant stays in charge.

Proven by parameter recovery (scripts/test_simcal.py): simulate a known
theta_true, fit lambda from the synthetic data the real way, run this loop,
and the recovered theta_hat must land within tolerance of theta_true —
otherwise the loop doesn't ship.

KNOWN LIMITS (be honest about them):
- The simulated moment is measured over uniform frequencies 1..MAX_FREQ;
  a real account whose ads cluster at low frequency (1-3) sees a slightly
  steeper slope over that range (ln-cumulative-CTR is nonlinear in f), so
  theta carries a design bias of order ~10% for such accounts. Fixing this
  properly means passing the account's real frequency distribution through.
- The moment has a structural ceiling: cumulative CTR >= p1/f, so
  ln-cum-CTR can't fall faster than -ln f and lambda_sim maxes out around
  ~0.17-0.26 depending on regime. A fitted lambda above that (legal — the
  upstream clamp allows up to 0.35, and cross-ad fits can be confounded
  upward) hits the theta bracket cap with converged=False. Callers MUST
  check `converged` and present the result as 'closest achievable', not as
  a successful match.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from src.agent import compute_click_probability
    from src.model import AdSimulationModel
except ImportError:
    from agent import compute_click_probability
    from model import AdSimulationModel

import numpy as np

# The frequency range the moment is measured over. Mirrors real accounts:
# most fitted frequencies sit between 1 and ~8 (and the engine caps the
# fatigue term at FATIGUE_CAP=8 exposures anyway).
MAX_FREQ = 8

# Personas used per moment evaluation — subsampled for speed; the moment is
# a population MEAN so 150 personas pins it well.
MOMENT_PERSONAS = 150

# Bisection bracket for theta. 0 = no fatigue; 0.8 logit/exposure is far
# beyond any plausible account (lambda is clamped to <=0.35 upstream).
THETA_LO, THETA_HI = 0.0, 0.8

_SEED = 7

_cache: dict[tuple, dict] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 128


def _ols_slope(x: np.ndarray, y: np.ndarray) -> float:
    """Same estimator as auction.fit_fatigue_lambda: least-squares slope."""
    vx = float(np.var(x))
    if vx <= 1e-12:
        return 0.0
    return float(np.cov(x, y, bias=True)[0, 1] / vx)


def _exposure_probs(model: AdSimulationModel, ad, calibration,
                    theta: float, agents: list) -> list[float]:
    """Population-mean click probability at each prior-exposure count
    0..MAX_FREQ-1, from the engine's own click model — full logit, anchored
    base, plausibility clamp — with fatigue constant ``theta``."""
    out = []
    for j in range(MAX_FREQ):
        probs = [
            compute_click_probability(
                a.persona, ad, calibration, model.base_logit,
                prior_exposures=j,
                anchor_logit=model._click_anchor_logit,
                fatigue_per_exposure=theta,
            ).probability
            for a in agents
        ]
        out.append(float(np.mean(probs)))
    return out


def simulated_lambda(theta: float, model: AdSimulationModel, ad,
                     calibration, agents: list) -> float:
    """The fatigue slope the MODEL produces at constant ``theta``, measured
    exactly the way the account's real lambda is fitted: synthetic 'ads'
    whose viewers saw them f = 1..MAX_FREQ times each, cumulative
    CTR(f) = mean of the per-exposure click probs, then the OLS slope of
    ln(CTR) on f (sign-flipped, like auction.fit_fatigue_lambda)."""
    ps = _exposure_probs(model, ad, calibration, theta, agents)
    freqs = np.arange(1, MAX_FREQ + 1, dtype=float)
    ctr_f = np.array([np.mean(ps[:f]) for f in range(1, MAX_FREQ + 1)])
    ctr_f = np.clip(ctr_f, 1e-9, 1.0)
    return -_ols_slope(freqs, np.log(ctr_f))


def fit_fatigue_theta(*, lambda_target: float, audience, ad, calibration,
                      channel: str, target_ctr: float | None,
                      tol: float = 5e-4, max_iter: int = 24) -> dict:
    """Bisection: find the engine fatigue constant theta whose SIMULATED
    decay slope matches the account's observed ``lambda_target``.

    Returns {theta, lambda_sim, lambda_target, iterations, converged}.
    lambda_target <= 0 short-circuits to theta = 0 (no measured fatigue).
    """
    lam = float(lambda_target)
    if lam <= 0:
        return {"theta": 0.0, "lambda_sim": 0.0, "lambda_target": lam,
                "iterations": 0, "converged": True}

    # Cache on the decision-relevant regime: the anchor CTR moves the
    # sigmoid's operating point, which is exactly why this loop exists.
    # The FULL creative (visual + psychology dicts) is keyed — two ads with
    # equal mean visual score but different psychology land at genuinely
    # different thetas (measured ~1.7x apart), so a mean is not enough.
    def _sig(d: dict) -> tuple:
        return tuple(sorted((k, round(float(v), 4)) for k, v in d.items()))
    key = (round(lam, 4), channel,
           round(target_ctr, 5) if target_ctr else None,
           _sig(ad.visual_scores), _sig(ad.psychology_features),
           len(audience))
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    # One anchored model gives base_logit + anchor in the forecast's regime;
    # theta plays no part in anchoring (the reference is at zero exposures).
    sample = audience.sample(min(MOMENT_PERSONAS, len(audience)),
                             random_state=_SEED)
    model = AdSimulationModel(sample, ad, calibration, channel=channel,
                              sim_days=3, daily_reach=0.3,
                              target_ctr=target_ctr, seed=_SEED)
    agents = model.consumer_agents

    lo, hi = THETA_LO, THETA_HI
    lam_hi = simulated_lambda(hi, model, ad, calibration, agents)
    if lam_hi <= lam:
        # Target steeper than the engine can produce in-bracket: take the cap.
        result = {"theta": hi, "lambda_sim": lam_hi, "lambda_target": lam,
                  "iterations": 1, "converged": False}
    else:
        theta = lam  # warm start: lambda is the right order of magnitude
        lam_sim = simulated_lambda(theta, model, ad, calibration, agents)
        it = 1
        while abs(lam_sim - lam) > tol and it < max_iter:
            if lam_sim < lam:
                lo = theta
            else:
                hi = theta
            theta = (lo + hi) / 2
            lam_sim = simulated_lambda(theta, model, ad, calibration, agents)
            it += 1
        result = {"theta": round(theta, 5), "lambda_sim": round(lam_sim, 5),
                  "lambda_target": round(lam, 5), "iterations": it,
                  "converged": abs(lam_sim - lam) <= tol}

    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = result
    return result
