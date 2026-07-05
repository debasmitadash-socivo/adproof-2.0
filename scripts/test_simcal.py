"""Parameter-recovery test for the simulation-based fatigue calibration.

The only way to trust that the loop returns the RIGHT constant is to plant a
known truth and demand the pipeline digs it back up:

    theta_true -> engine simulates synthetic ad history at varying frequency
               -> lambda fitted from that data with the REAL estimator
                  (auction.fit_fatigue_lambda, same code the account fit uses)
               -> fit_fatigue_theta(lambda) -> theta_hat must ~= theta_true

If recovery fails, the loop doesn't ship. Run: python scripts/test_simcal.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from config import PSYCHOLOGY_FEATURES, VISUAL_SCORE_KEYS
from src.agent import AdStimulus
from src.auction import fit_fatigue_lambda
from src.model import AdSimulationModel
from src.pipeline import get_resources
from src.simcal import (MAX_FREQ, MOMENT_PERSONAS, fit_fatigue_theta,
                        simulated_lambda)

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def make_context(target_ctr: float = 0.012, quality: float = 0.55):
    personas, calibration = get_resources()
    ad = AdStimulus(
        visual_scores={k: quality for k in VISUAL_SCORE_KEYS},
        psychology_features={k: 0.4 for k in PSYCHOLOGY_FEATURES},
        product_category="general",
        channel="instagram",
    )
    return personas, calibration, ad, target_ctr


def synthetic_ad_history(theta_true: float, personas, calibration, ad,
                         target_ctr: float, n_ads: int = 40,
                         imps_per_ad: int = 60_000, seed: int = 11) -> pd.DataFrame:
    """Engine-generated ad history at a KNOWN theta: ads whose viewers saw
    them f times each, cumulative CTR from the model's own click
    probabilities, binomial noise on top (real data is noisy)."""
    from src.agent import compute_click_probability

    rng = np.random.default_rng(seed)
    sample = personas.sample(MOMENT_PERSONAS, random_state=3)
    model = AdSimulationModel(sample, ad, calibration, channel="instagram",
                              sim_days=3, daily_reach=0.3,
                              target_ctr=target_ctr, seed=3)
    per_exposure = []
    for j in range(MAX_FREQ):
        probs = [compute_click_probability(
            a.persona, ad, calibration, model.base_logit, prior_exposures=j,
            anchor_logit=model._click_anchor_logit,
            fatigue_per_exposure=theta_true).probability
            for a in model.consumer_agents]
        per_exposure.append(float(np.mean(probs)))

    rows = []
    for i in range(n_ads):
        f = int(rng.integers(1, MAX_FREQ + 1))
        ctr = float(np.mean(per_exposure[:f]))
        clicks = int(rng.binomial(imps_per_ad, ctr))
        rows.append({"ad_name": f"ad_{i}", "frequency": float(f),
                     "impressions": imps_per_ad, "clicks": clicks})
    return pd.DataFrame(rows)


def main() -> int:
    personas, calibration, ad, target_ctr = make_context()
    sample = personas.sample(MOMENT_PERSONAS, random_state=3)
    model = AdSimulationModel(sample, ad, calibration, channel="instagram",
                              sim_days=3, daily_reach=0.3,
                              target_ctr=target_ctr, seed=3)
    agents = model.consumer_agents

    print("simcal — monotonicity of the simulated moment")
    lams = [simulated_lambda(t, model, ad, calibration, agents)
            for t in (0.0, 0.05, 0.10, 0.20, 0.35)]
    check("lambda_sim(0) == 0 (no fatigue, no decay)", abs(lams[0]) < 1e-9,
          f"got {lams[0]:.6f}")
    check("lambda_sim strictly increasing in theta",
          all(b > a for a, b in zip(lams, lams[1:])),
          " -> ".join(f"{v:.4f}" for v in lams))
    print("  note: sigmoid effect is real —",
          f"theta=0.20 produces observed lambda={lams[3]:.4f} (not 0.20)")

    print("simcal — parameter recovery (the gate)")
    for theta_true in (0.08, 0.18, 0.30):
        df = synthetic_ad_history(theta_true, personas, calibration, ad,
                                  target_ctr)
        fit = fit_fatigue_lambda(df)
        check(f"synthetic history at theta={theta_true} yields usable lambda",
              bool(fit["usable"]), str(fit.get("reason")))
        if not fit["usable"]:
            continue
        rec = fit_fatigue_theta(
            lambda_target=fit["lambda_per_exposure"], audience=personas,
            ad=ad, calibration=calibration, channel="instagram",
            target_ctr=target_ctr)
        err = abs(rec["theta"] - theta_true)
        check(f"theta recovered near {theta_true}", err <= 0.02,
              f"theta_hat={rec['theta']} (err {err:.4f}, "
              f"{rec['iterations']} iters, converged={rec['converged']})")

    print("simcal — edges")
    z = fit_fatigue_theta(lambda_target=0.0, audience=personas, ad=ad,
                          calibration=calibration, channel="instagram",
                          target_ctr=target_ctr)
    check("lambda<=0 short-circuits to theta=0", z["theta"] == 0.0 and z["converged"])

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("\nAll simcal checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
