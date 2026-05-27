"""Calibration of psychology-rule weights from public CTR data.

This is the "background training" step. Given a creative-labelled CTR dataset
(see ``data_loader``), it estimates **how much each psychology rule moves
click-through rate**: emotional appeal, scarcity, social proof, relevance.

Method
------
* CTR is a probability, so the right model is **logistic regression**, fitted
  on the logit scale. All four psychology features are in [0, 1].
* Public CTR data is aggregated (one row = one ad with N impressions and K
  clicks). We fit a **grouped binomial** logistic regression via IRLS / Fisher
  scoring -- the textbook GLM estimator -- weighting each ad by its impression
  count. No row expansion, no external ML dependency.
* Real ad data is **overdispersed**: two ads with identical copy still differ.
  Treating each ad as pure binomial would understate uncertainty, so we apply
  a **quasi-binomial dispersion correction** (Pearson phi) and inflate the
  standard errors accordingly. Reported p-values are therefore honest.

Why logit scale matters downstream
----------------------------------
The fitted coefficients are logit-scale weights. The agent (see ``agent.py``)
combines base rate + visual + persona + psychology contributions **on the
logit scale**, then applies a sigmoid. This keeps every predicted probability
inside [0, 1] -- a plain additive model in probability space cannot guarantee
that.

Benchmark tuning
----------------
``recalibrate_intercept`` anchors the model's overall CTR level to a trusted
benchmark (e.g. a channel base rate) while keeping the *relative* psychology
weights from the fitted data. Rationale: the absolute CTR of a training
dataset rarely matches the channel you are simulating, but the relative pull
of psychology features transfers far better than the absolute level.

Run directly to calibrate against whatever training data is available:
    python src/calibration.py
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Allow `python src/calibration.py` to find config.py in the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
from config import CALIBRATION_FILE, PSYCHOLOGY_FEATURES  # noqa: E402

# data_loader lives in the same package; support both import styles.
try:
    from src.data_loader import BENCHMARK_BASE_RATES, load_training_data
except ImportError:  # when run as `python src/calibration.py`
    from data_loader import BENCHMARK_BASE_RATES, load_training_data

__all__ = [
    "CalibrationResult",
    "compare_high_low_ctr",
    "calibrate_psychology_weights",
    "evaluate_calibration",
    "recalibrate_intercept",
    "predict_ctr",
    "relative_importance",
    "save_calibration",
    "load_calibration",
    "run_calibration",
]

_EPS = 1e-12


# ===========================================================================
# Small numeric helpers
# ===========================================================================

def _sigmoid(x: np.ndarray) -> np.ndarray:
    """Numerically stable logistic function.

    The input is clamped to +/-709 so exp() cannot overflow float64; both
    saturated ends still map cleanly onto 0 and 1.
    """
    x = np.clip(x, -709.0, 709.0)
    return 1.0 / (1.0 + np.exp(-x))


def _logit(p: float) -> float:
    """Inverse logistic; input is clamped away from 0 and 1."""
    p = min(max(p, _EPS), 1 - _EPS)
    return math.log(p / (1 - p))


def _norm_cdf(x: float) -> float:
    """Standard normal CDF (for two-sided coefficient p-values)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _grouped_loglik(y: np.ndarray, mu: np.ndarray, w: np.ndarray) -> float:
    """Weighted binomial log-likelihood for grouped (rate) data."""
    mu = np.clip(mu, _EPS, 1 - _EPS)
    return float(np.sum(w * (y * np.log(mu) + (1 - y) * np.log(1 - mu))))


# ===========================================================================
# Grouped binomial logistic regression (IRLS / Fisher scoring)
# ===========================================================================

def _irls_logistic(X: np.ndarray, y: np.ndarray, w: np.ndarray,
                   max_iter: int = 100, tol: float = 1e-9):
    """Fit a weighted grouped-binomial logistic regression by IRLS.

    Implemented as damped Fisher scoring (Newton-Raphson with step-halving):
    each step solves the Fisher-information system for a coefficient update,
    then shrinks the step until the negative log-likelihood does not increase.
    Working with the score/Hessian directly -- rather than the classic
    working-response form -- avoids the divide-by-tiny-variance blow-up that
    occurs when predicted CTR saturates. The result is the same MLE, computed
    robustly on heavily weighted, overdispersed ad data.

    Parameters
    ----------
    X : (n, p) design matrix -- MUST include an intercept column of ones.
    y : (n,)   observed click proportion (CTR) per row, in [0, 1].
    w : (n,)   binomial denominator per row (impression count).

    Returns
    -------
    (beta, cov_binomial, n_iter, converged) where ``cov_binomial`` is the
    model-based covariance assuming pure binomial noise (later inflated by the
    quasi-binomial dispersion factor).
    """
    n, p = X.shape
    beta = np.zeros(p)
    # Warm-start the intercept at the pooled log-odds for fast convergence.
    pooled = float(np.clip(np.average(y, weights=w), _EPS, 1 - _EPS))
    beta[0] = math.log(pooled / (1 - pooled))

    def neg_loglik(b: np.ndarray) -> float:
        mu = np.clip(_sigmoid(X @ b), _EPS, 1 - _EPS)
        return -_grouped_loglik(y, mu, w)

    converged, n_iter = False, max_iter
    # numpy's SIMD matmul can raise spurious divide/overflow FPE warnings even
    # on perfectly finite inputs (a known numpy quirk). We silence those flags
    # for the linear algebra and instead verify the result is finite below --
    # a genuine numerical blow-up is still caught and raised loudly.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        cur_nll = neg_loglik(beta)
        for it in range(1, max_iter + 1):
            mu = np.clip(_sigmoid(X @ beta), _EPS, 1 - _EPS)
            gradient = X.T @ (w * (y - mu))                  # score vector
            fisher = (X.T * (w * mu * (1 - mu))) @ X         # Fisher info
            fisher += 1e-10 * np.eye(p)                      # ridge for safety
            step = np.linalg.solve(fisher, gradient)

            # Step-halving line search -- guarantees the likelihood improves.
            t, cand_nll = 1.0, cur_nll
            for _ in range(40):
                cand_nll = neg_loglik(beta + t * step)
                if cand_nll <= cur_nll + 1e-12:
                    break
                t *= 0.5

            delta = float(np.max(np.abs(t * step)))
            beta, cur_nll = beta + t * step, cand_nll
            if delta < tol:
                converged, n_iter = True, it
                break

        # Covariance at the final estimate: inverse Fisher information.
        mu = np.clip(_sigmoid(X @ beta), _EPS, 1 - _EPS)
        fisher = (X.T * (w * mu * (1 - mu))) @ X + 1e-10 * np.eye(p)
        cov_binomial = np.linalg.inv(fisher)

    if not (np.all(np.isfinite(beta)) and np.all(np.isfinite(cov_binomial))):
        raise FloatingPointError(
            "Logistic regression did not produce finite estimates -- check "
            "the input data for degenerate or extreme values."
        )
    return beta, cov_binomial, n_iter, converged


# ===========================================================================
# Calibration result container
# ===========================================================================

@dataclass
class CalibrationResult:
    """Calibrated psychology-rule weights plus fit diagnostics.

    All weights are on the **logit scale**: a coefficient of 0.6 means raising
    that feature from 0 to 1 adds 0.6 to the click logit.
    """
    intercept: float                       # logit-scale base
    coefficients: dict                     # feature -> logit weight
    std_errors: dict                       # 'intercept' + feature -> SE
    p_values: dict                         # 'intercept' + feature -> p-value
    feature_names: tuple
    base_ctr: float                        # sigmoid(intercept)
    mean_features: dict                    # training-set feature means
    std_features: dict                     # training-set feature SDs
    n_ads: int
    total_impressions: int
    is_synthetic: bool
    converged: bool
    diagnostics: dict = field(default_factory=dict)
    notes: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat(
                timespec="seconds")

    def summary(self) -> str:
        """Return a readable, client-facing summary of the calibration."""
        lines = ["Calibrated psychology-rule weights (logit scale)",
                 "-" * 52]
        for f in self.feature_names:
            star = self._significance(self.p_values.get(f, 1.0))
            lines.append(
                f"  {f:<18s} {self.coefficients[f]:+.3f}  "
                f"(SE {self.std_errors[f]:.3f}, "
                f"{self._fmt_p(self.p_values[f])}) {star}"
            )
        lines += [
            "-" * 52,
            f"  base CTR (all features 0): {self.base_ctr:.4f}",
            f"  fitted on {self.n_ads:,} ads / "
            f"{self.total_impressions:,} impressions",
            f"  pseudo-R^2: {self.diagnostics.get('pseudo_r2', float('nan')):.3f}"
            f"  | dispersion phi: "
            f"{self.diagnostics.get('dispersion', float('nan')):.2f}",
        ]
        if self.is_synthetic:
            lines.append("  NOTE: fitted on SYNTHETIC data -- illustrative "
                         "only, not a real-world effect estimate.")
        return "\n".join(lines)

    @staticmethod
    def _significance(p: float) -> str:
        return "***" if p < 0.001 else "**" if p < 0.01 else \
               "*" if p < 0.05 else "(ns)"

    @staticmethod
    def _fmt_p(p: float) -> str:
        """Format a p-value; tiny values underflow to 0, so report a bound."""
        return "p<0.001" if p < 0.001 else f"p={p:.3f}"


# ===========================================================================
# High vs low CTR pattern comparison (intuitive, model-free)
# ===========================================================================

def compare_high_low_ctr(creative_df: pd.DataFrame,
                          quantile: float = 0.33) -> pd.DataFrame:
    """Compare mean psychology-feature values in high- vs low-CTR ads.

    A model-free sanity check: before trusting the fitted weights, confirm
    that high-CTR ads really do score higher on these features.
    """
    feats = list(PSYCHOLOGY_FEATURES)
    df = creative_df.dropna(subset=feats + ["ctr"])
    lo_cut, hi_cut = df["ctr"].quantile([quantile, 1 - quantile])
    low = df[df["ctr"] <= lo_cut]
    high = df[df["ctr"] >= hi_cut]
    table = pd.DataFrame({
        "low_ctr_mean": low[feats].mean(),
        "high_ctr_mean": high[feats].mean(),
    })
    table["lift"] = table["high_ctr_mean"] - table["low_ctr_mean"]
    return table.round(3)


# ===========================================================================
# Core calibration
# ===========================================================================

def _prediction_metrics(y: np.ndarray, mu: np.ndarray,
                        w: np.ndarray) -> dict:
    """CTR-level goodness-of-fit metrics (used by calibrate + evaluate)."""
    pooled = float(np.average(y, weights=w))
    ll_model = _grouped_loglik(y, mu, w)
    ll_null = _grouped_loglik(y, np.full_like(y, pooled), w)
    pseudo_r2 = 1.0 - ll_model / ll_null if ll_null != 0 else float("nan")
    wrmse = math.sqrt(float(np.sum(w * (mu - y) ** 2) / np.sum(w)))
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        corr = float(np.corrcoef(mu, y)[0, 1]) if len(y) > 1 else float("nan")
    return {
        "pseudo_r2": round(pseudo_r2, 4),
        "weighted_rmse_ctr": round(wrmse, 5),
        "pred_obs_correlation": round(corr, 4),
    }


def calibrate_psychology_weights(creative_df: pd.DataFrame,
                                 is_synthetic: bool = False,
                                 notes: str = "") -> CalibrationResult:
    """Fit psychology-rule weights from a creative-labelled CTR dataset.

    Expects the Tier-2 schema from ``data_loader``: the four psychology
    features plus ``ctr``, ``impressions``, and ``clicks``.
    """
    feats = list(PSYCHOLOGY_FEATURES)
    required = set(feats) | {"ctr", "impressions"}
    missing = required - set(creative_df.columns)
    if missing:
        raise KeyError(f"creative_df is missing columns: {sorted(missing)}")

    df = creative_df.dropna(subset=feats + ["ctr", "impressions"]).copy()
    df = df[df["impressions"] > 0]
    if len(df) < 20:
        raise ValueError(
            f"Need at least 20 ads to calibrate; got {len(df)}."
        )
    if "clicks" in df.columns and df["clicks"].notna().all():
        clicks = df["clicks"].to_numpy(float)
    else:  # derive click counts from ctr x impressions
        clicks = (df["ctr"] * df["impressions"]).round().to_numpy(float)

    X = np.column_stack([np.ones(len(df))]
                        + [df[f].to_numpy(float) for f in feats])
    y = df["ctr"].to_numpy(float)
    w = df["impressions"].to_numpy(float)

    beta, cov_binomial, n_iter, converged = _irls_logistic(X, y, w)

    # --- Quasi-binomial dispersion correction -----------------------------
    # Pearson chi-square / dof. phi > 1 means the data is overdispersed
    # relative to a pure binomial -- so we inflate the standard errors.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        mu = np.clip(_sigmoid(X @ beta), _EPS, 1 - _EPS)
    pearson_resid = (clicks - w * mu) / np.sqrt(w * mu * (1 - mu))
    dof = max(len(df) - X.shape[1], 1)
    dispersion = float(np.sum(pearson_resid ** 2) / dof)
    phi = max(dispersion, 1.0)               # never deflate uncertainty
    cov = cov_binomial * phi
    se = np.sqrt(np.diag(cov))

    # --- Coefficients, standard errors, p-values --------------------------
    names = ["intercept"] + feats
    coefficients = {f: float(beta[i + 1]) for i, f in enumerate(feats)}
    std_errors = {names[i]: float(se[i]) for i in range(len(names))}
    p_values = {}
    for i, name in enumerate(names):
        z = beta[i] / se[i] if se[i] > 0 else 0.0
        p_values[name] = round(2.0 * (1.0 - _norm_cdf(abs(z))), 6)

    diagnostics = _prediction_metrics(y, mu, w)
    diagnostics.update({
        "dispersion": round(dispersion, 3),
        "irls_iterations": n_iter,
    })

    return CalibrationResult(
        intercept=float(beta[0]),
        coefficients=coefficients,
        std_errors=std_errors,
        p_values=p_values,
        feature_names=tuple(feats),
        base_ctr=float(_sigmoid(np.array([beta[0]]))[0]),
        mean_features={f: round(float(df[f].mean()), 4) for f in feats},
        std_features={f: round(float(df[f].std()), 4) for f in feats},
        n_ads=int(len(df)),
        total_impressions=int(w.sum()),
        is_synthetic=is_synthetic,
        converged=converged,
        diagnostics=diagnostics,
        notes=notes,
    )


# ===========================================================================
# Prediction, evaluation, importance
# ===========================================================================

def predict_ctr(result: CalibrationResult, features: dict) -> float:
    """Predict CTR for a single ad given its psychology-feature values.

    Missing features default to 0. Output is a probability in (0, 1).
    """
    logit = result.intercept
    for f in result.feature_names:
        logit += result.coefficients[f] * float(features.get(f, 0.0))
    return float(_sigmoid(np.array([logit]))[0])


def evaluate_calibration(result: CalibrationResult,
                         creative_df: pd.DataFrame) -> dict:
    """Re-evaluate a calibration's fit on a (possibly held-out) dataset."""
    feats = list(result.feature_names)
    df = creative_df.dropna(subset=feats + ["ctr", "impressions"])
    df = df[df["impressions"] > 0]
    logit = result.intercept + sum(
        result.coefficients[f] * df[f].to_numpy(float) for f in feats)
    mu = np.clip(_sigmoid(logit), _EPS, 1 - _EPS)
    return _prediction_metrics(df["ctr"].to_numpy(float), mu,
                               df["impressions"].to_numpy(float))


def relative_importance(result: CalibrationResult) -> dict:
    """Rank psychology rules by real-world influence.

    Importance = |coefficient| x feature SD -- it scales the weight by how
    much the feature actually varies across ads, so a large weight on a
    near-constant feature is not overstated. Values sum to 1.
    """
    raw = {f: abs(result.coefficients[f]) * result.std_features.get(f, 0.0)
           for f in result.feature_names}
    total = sum(raw.values())
    if total <= 0:
        n = len(result.feature_names)
        return {f: round(1.0 / n, 4) for f in result.feature_names}
    return {f: round(v / total, 4) for f, v in raw.items()}


# ===========================================================================
# Benchmark tuning
# ===========================================================================

def recalibrate_intercept(result: CalibrationResult,
                          target_ctr: float,
                          reference_features: dict | None = None
                          ) -> CalibrationResult:
    """Anchor the model's CTR level to a benchmark, keeping relative weights.

    The intercept is shifted so that an ad at ``reference_features`` predicts
    exactly ``target_ctr``. By default the reference is the training-set mean
    ad, i.e. "the average ad in this channel should hit the benchmark CTR".
    Psychology-rule coefficients are left untouched.
    """
    if not 0 < target_ctr < 1:
        raise ValueError("target_ctr must be a probability in (0, 1).")
    ref = reference_features or result.mean_features
    current_logit = result.intercept + sum(
        result.coefficients[f] * float(ref.get(f, 0.0))
        for f in result.feature_names)
    shift = _logit(target_ctr) - current_logit

    tuned = CalibrationResult(**asdict(result))
    tuned.intercept = result.intercept + shift
    tuned.base_ctr = float(_sigmoid(np.array([tuned.intercept]))[0])
    tuned.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tuned.notes = (result.notes + " | " if result.notes else "") + \
        f"intercept anchored to benchmark CTR {target_ctr:.4f}"
    return tuned


# ===========================================================================
# Persistence
# ===========================================================================

def save_calibration(result: CalibrationResult,
                      path: Path = CALIBRATION_FILE) -> Path:
    """Write a calibration result to JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(result)
    data["feature_names"] = list(data["feature_names"])  # tuple -> JSON list
    path.write_text(json.dumps(data, indent=2))
    return path


def load_calibration(path: Path = CALIBRATION_FILE) -> CalibrationResult:
    """Load a calibration result previously saved with ``save_calibration``."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"No calibration file at {path}. Run `python src/calibration.py`."
        )
    data = json.loads(path.read_text())
    data["feature_names"] = tuple(data["feature_names"])
    return CalibrationResult(**data)


# ===========================================================================
# Orchestration
# ===========================================================================

def run_calibration(creative_df: pd.DataFrame | None = None,
                    target_base_ctr: float | None = None,
                    save: bool = True) -> CalibrationResult:
    """End-to-end calibration: load data, fit weights, optionally anchor + save.

    If ``creative_df`` is None, training data is pulled via ``data_loader``
    (which falls back to the clearly-labelled synthetic dataset).
    """
    if creative_df is None:
        bundle = load_training_data()
        creative_df = bundle["creative_df"]
        is_synthetic = bundle["is_synthetic"]
        notes = f"source: {bundle['creative_source']}"
    else:
        is_synthetic, notes = False, "source: caller-supplied DataFrame"

    result = calibrate_psychology_weights(creative_df,
                                          is_synthetic=is_synthetic,
                                          notes=notes)
    if target_base_ctr is not None:
        result = recalibrate_intercept(result, target_base_ctr)
    if save:
        save_calibration(result)
    return result


# ===========================================================================
# CLI entry point
# ===========================================================================

def _main() -> None:
    bundle = load_training_data()
    creative_df = bundle["creative_df"]

    print("=" * 60)
    print("HIGH vs LOW CTR -- psychology feature patterns")
    print("=" * 60)
    print(compare_high_low_ctr(creative_df).to_string())

    print("\n" + "=" * 60)
    print("CALIBRATION")
    print("=" * 60)
    result = calibrate_psychology_weights(
        creative_df, is_synthetic=bundle["is_synthetic"],
        notes=f"source: {bundle['creative_source']}")
    print(result.summary())

    print("\nRelative importance (|weight| x feature SD, sums to 1):")
    for f, imp in sorted(relative_importance(result).items(),
                         key=lambda kv: -kv[1]):
        print(f"  {f:<18s} {imp:6.1%}")

    # Benchmark tuning demo: anchor to the social-feed channel base rate.
    target = BENCHMARK_BASE_RATES["social_feed"]
    tuned = recalibrate_intercept(result, target)
    print(f"\nBenchmark tuning: base CTR {result.base_ctr:.4f} "
          f"-> anchored so the mean ad hits {target:.4f} "
          f"(new intercept base {tuned.base_ctr:.4f}).")

    path = save_calibration(tuned)
    print(f"Saved calibration -> {path}")
    if result.is_synthetic:
        print("\nREMINDER: synthetic training data -- weights are "
              "illustrative. Download real data (see data_loader) before "
              "presenting calibration figures to a client.")


if __name__ == "__main__":
    _main()
