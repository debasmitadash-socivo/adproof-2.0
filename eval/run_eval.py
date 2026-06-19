#!/usr/bin/env python3
"""AdProof backend regression / sanity harness.

WHAT THIS IS (and is NOT)
-------------------------
This runs the REAL forecast handler (`api/main.simulate`) over a fixed set of
golden scenarios, LLM-FREE and DETERMINISTIC (critics disabled, heuristic
profile/audience parse, seeded Monte Carlo), captures a "fingerprint" of the
key outputs, checks a set of INVARIANTS (sanity rules that must always hold),
snapshots everything, and diffs the run against a saved baseline.

It answers: *"did this change break anything, violate a rule, or shift the
numbers unexpectedly?"* — i.e. STABILITY + SANITY + CONSISTENCY.

It does NOT measure real-world ACCURACY ("is the forecast closer to real
CTR/ROAS"). That needs real campaign outcomes to score against — the backtest,
which only becomes meaningful once real outcome data flows back from live
accounts. There is a clearly-marked slot for it below (`accuracy_backtest`).
Do not let this harness claim the model is "more accurate" — it can only show
the model is stable, sane, and changing (or not) in expected ways.

USAGE
-----
    .venv-preview/bin/python3 eval/run_eval.py               # run + diff vs baseline
    .venv-preview/bin/python3 eval/run_eval.py --set-baseline # run + save as new baseline
    .venv-preview/bin/python3 eval/run_eval.py --quiet        # less output (CI)

Exit code is non-zero if any invariant fails — so it can gate a commit/push.
Every run appends a line to eval/ledger.jsonl and writes a full snapshot to
eval/runs/<UTC>__<gitsha>.json, so the trajectory is tracked over time.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

# --- Make the run LLM-free + deterministic BEFORE importing the app ----------
for _flag in ("ADPROOF_LINKEDIN_CRITIC_ENABLED", "ADPROOF_META_CRITIC_ENABLED",
              "ADPROOF_REEL_QUALITY_ENABLED", "ADPROOF_SCRIPT_CRITIC_ENABLED"):
    os.environ[_flag] = "0"

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "api"))

import main  # noqa: E402  (api/main.py)
from main import SimulateRequest  # noqa: E402

try:
    from fastapi import HTTPException  # noqa: E402
except ImportError:                                    # pragma: no cover
    HTTPException = Exception  # type: ignore

# Force heuristic (deterministic, no-LLM) profile + audience parsing. The
# handler reads `have_any_key()` from main's globals to decide prefer_llm.
main.have_any_key = lambda: False  # type: ignore

_EVAL_DIR = Path(__file__).resolve().parent
_SCENARIOS = _EVAL_DIR / "scenarios.json"
_BASELINE = _EVAL_DIR / "baseline.json"
_RUNS_DIR = _EVAL_DIR / "runs"
_LEDGER = _EVAL_DIR / "ledger.jsonl"

# Monte-Carlo iterations for the harness — fewer than production for speed,
# fixed so runs stay comparable + deterministic. Override with EVAL_N_RUNS.
_EVAL_N_RUNS = int(os.environ.get("EVAL_N_RUNS", "30"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dig(obj, path: str):
    """Safe nested lookup: _dig(d, 'mc.predicted_roas.p50')."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(_ROOT),
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:                                  # noqa: BLE001
        return "nogit"


def _fingerprint(resp: dict) -> dict:
    """Pull the deterministic, regression-relevant numbers out of a forecast."""
    cc = resp.get("copy_critique") or []
    ling = resp.get("linguistics") or {}
    return {
        "runnable":         bool(_dig(resp, "viability.runnable")),
        "forecast_valid":   bool(_dig(resp, "viability.forecast_valid")),
        "verdict_class":    _dig(resp, "insights.verdict_class"),
        "kpi_lead":         _dig(resp, "kpis.lead"),
        "ctr_p50":          _dig(resp, "kpis.ctr.p50"),
        "cpm":              _dig(resp, "kpis.cpm.value"),
        "clicks_p50":       _dig(resp, "mc.predicted_clicks.p50"),
        "clicks_p10":       _dig(resp, "mc.predicted_clicks.p10"),
        "clicks_p90":       _dig(resp, "mc.predicted_clicks.p90"),
        "conv_p50":         _dig(resp, "mc.predicted_conversions.p50"),
        "roas_p10":         _dig(resp, "mc.predicted_roas.p10"),
        "roas_p50":         _dig(resp, "mc.predicted_roas.p50"),
        "roas_p90":         _dig(resp, "mc.predicted_roas.p90"),
        "impressions":      _dig(resp, "mc.total_impressions"),
        "audience_size":    _dig(resp, "mc.audience_size"),
        "clears_break_even": _dig(resp, "economics.clears_break_even"),
        "confidence_level": _dig(resp, "confidence.level"),
        "copy_issue_count": len(cc),
        "copy_socivo_count":  sum(1 for c in cc if c.get("source") == "socivo"),
        "ling_grade":       ling.get("grade_level"),
        "ling_persuasion":  ling.get("persuasion_count"),
    }


def _run_scenario(sc: dict):
    """Returns (status, payload). status in {'ok','blocked','error'}."""
    try:
        params = dict(sc["request"])
        params["n_runs"] = _EVAL_N_RUNS          # fast + fixed for determinism
        req = SimulateRequest(**params)
    except Exception as exc:                           # noqa: BLE001
        return "error", {"detail": f"bad request model: {exc}"}
    try:
        resp = main.simulate(req)
        return "ok", resp
    except HTTPException as exc:                        # viability gate / 4xx
        return "blocked", {"status_code": getattr(exc, "status_code", None),
                           "detail": getattr(exc, "detail", str(exc))}
    except Exception as exc:                            # noqa: BLE001
        return "error", {"detail": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

def _check_invariants(sc: dict, status: str, payload) -> list[dict]:
    """Return a list of {name, ok, detail} for one scenario."""
    out: list[dict] = []

    def add(name, ok, detail=""):
        out.append({"scenario": sc["id"], "name": name, "ok": bool(ok), "detail": detail})

    expect = sc.get("expect", "runnable")

    if expect == "blocked":
        add("blocks_as_expected", status == "blocked",
            f"status={status} (wanted blocked); detail={str(payload)[:80]}")
        return out

    # expect == runnable
    if status != "ok":
        add("runs_without_error", False, f"status={status}: {str(payload)[:120]}")
        return out
    add("runs_without_error", True)

    fp = _fingerprint(payload)
    add("viability_runnable", fp["runnable"], "viability.runnable is false")
    add("forecast_valid", fp["forecast_valid"], "viability.forecast_valid is false")

    # CTR sane
    ctr = fp["ctr_p50"]
    add("ctr_in_range", ctr is not None and 0.0 <= ctr <= 1.0, f"ctr_p50={ctr}")
    # ROAS non-negative
    add("roas_nonneg", (fp["roas_p50"] or 0) >= 0, f"roas_p50={fp['roas_p50']}")
    # Impressions positive
    add("impressions_positive", (fp["impressions"] or 0) > 0, f"impressions={fp['impressions']}")

    # Monte-Carlo bands ordered (p10 <= p50 <= p90)
    for metric in ("clicks", "roas"):
        p10, p50, p90 = fp.get(f"{metric}_p10"), fp.get(f"{metric}_p50"), fp.get(f"{metric}_p90")
        if None not in (p10, p50, p90):
            add(f"{metric}_band_ordered", p10 <= p50 <= p90, f"{p10} <= {p50} <= {p90}")

    # Objective-awareness: the hero KPI must match the objective.
    lead_in = (sc.get("assert") or {}).get("kpi_lead_in")
    if lead_in:
        add("kpi_lead_matches_objective", fp["kpi_lead"] in lead_in,
            f"lead={fp['kpi_lead']} not in {lead_in}")

    # Copy-detector bounds
    asrt = sc.get("assert") or {}
    if "copy_socivo_min" in asrt:
        add("copy_socivo_min", fp["copy_socivo_count"] >= asrt["copy_socivo_min"],
            f"socivo={fp['copy_socivo_count']} < {asrt['copy_socivo_min']}")
    if "copy_socivo_max" in asrt:
        add("copy_socivo_max", fp["copy_socivo_count"] <= asrt["copy_socivo_max"],
            f"socivo={fp['copy_socivo_count']} > {asrt['copy_socivo_max']}")
    if asrt.get("linguistics_present"):
        add("linguistics_present", fp["ling_grade"] is not None, "linguistics missing")

    return out


# ---------------------------------------------------------------------------
# Diff vs baseline
# ---------------------------------------------------------------------------

_NUMERIC_EPS_REL = 0.001   # 0.1% relative change is "moved"


def _diff_against(baseline: dict, current: dict) -> list[dict]:
    rows: list[dict] = []
    for sid, cur_fp in current.items():
        base_fp = baseline.get(sid)
        if base_fp is None:
            rows.append({"scenario": sid, "field": "(scenario)", "old": "—", "new": "new"})
            continue
        for k, new_v in cur_fp.items():
            old_v = base_fp.get(k)
            if old_v == new_v:
                continue
            if isinstance(old_v, (int, float)) and isinstance(new_v, (int, float)) and old_v not in (None,):
                denom = abs(old_v) or 1.0
                if abs(new_v - old_v) / denom < _NUMERIC_EPS_REL:
                    continue  # within noise floor
            rows.append({"scenario": sid, "field": k, "old": old_v, "new": new_v})
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main_run(set_baseline: bool, quiet: bool) -> int:
    spec = json.loads(_SCENARIOS.read_text())
    scenarios = spec["scenarios"]

    current_fps: dict = {}
    raw_status: dict = {}
    all_inv: list[dict] = []

    for sc in scenarios:
        status, payload = _run_scenario(sc)
        raw_status[sc["id"]] = status
        if status == "ok":
            current_fps[sc["id"]] = _fingerprint(payload)
        all_inv.extend(_check_invariants(sc, status, payload))

    # Determinism check: re-run one scenario, compare fingerprint.
    det_id = spec.get("determinism_check")
    determinism_ok = None
    if det_id:
        sc = next((s for s in scenarios if s["id"] == det_id), None)
        if sc:
            status2, payload2 = _run_scenario(sc)
            determinism_ok = (status2 == "ok"
                              and _fingerprint(payload2) == current_fps.get(det_id))
            all_inv.append({"scenario": det_id, "name": "deterministic_rerun",
                            "ok": bool(determinism_ok),
                            "detail": "re-run fingerprint differs" if not determinism_ok else ""})

    # Cross-scenario invariants.
    for inv in spec.get("cross_scenario_invariants", []):
        a = current_fps.get(inv["greater_eq"], {}).get(inv["metric"])
        b = current_fps.get(inv["than"], {}).get(inv["metric"])
        ok = (a is not None and b is not None and a >= b)
        all_inv.append({"scenario": f"{inv['greater_eq']}≥{inv['than']}", "name": inv["name"],
                        "ok": bool(ok), "detail": f"{inv['metric']}: {a} vs {b}"})

    passed = [i for i in all_inv if i["ok"]]
    failed = [i for i in all_inv if not i["ok"]]

    # --- Snapshot + ledger ---
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    sha = _git_sha()
    snapshot = {"ts": ts, "git": sha, "fingerprints": current_fps,
                "status": raw_status, "invariants": all_inv}
    _RUNS_DIR.mkdir(exist_ok=True)
    (_RUNS_DIR / f"{ts}__{sha}.json").write_text(json.dumps(snapshot, indent=2, default=str))

    # --- Diff vs baseline ---
    diff_rows: list[dict] = []
    have_baseline = _BASELINE.exists()
    if have_baseline:
        baseline = json.loads(_BASELINE.read_text()).get("fingerprints", {})
        diff_rows = _diff_against(baseline, current_fps)

    ledger_line = {"ts": ts, "git": sha, "scenarios": len(scenarios),
                   "invariants_passed": len(passed), "invariants_failed": len(failed),
                   "determinism_ok": determinism_ok, "diffs_vs_baseline": len(diff_rows)}
    with _LEDGER.open("a") as fh:
        fh.write(json.dumps(ledger_line) + "\n")

    if set_baseline:
        _BASELINE.write_text(json.dumps(snapshot, indent=2, default=str))

    # --- Report ---
    if not quiet:
        print(f"\nAdProof eval — {ts}  (git {sha})")
        print("=" * 66)
        for sc in scenarios:
            sid = sc["id"]
            invs = [i for i in all_inv if i["scenario"] == sid]
            bad = [i for i in invs if not i["ok"]]
            mark = "FAIL" if bad else "ok  "
            fp = current_fps.get(sid, {})
            summary = (f"lead={fp.get('kpi_lead')} ctr={fp.get('ctr_p50')} "
                       f"roas={fp.get('roas_p50')} socivo={fp.get('copy_socivo_count')} "
                       f"grade={fp.get('ling_grade')}") if fp else f"({raw_status.get(sid)})"
            print(f"  [{mark}] {sid:30s} {summary}")
            for b in bad:
                print(f"         ↳ FAIL {b['name']}: {b['detail']}")
        print("-" * 66)
        print(f"  invariants: {len(passed)} passed, {len(failed)} failed"
              + (f" · determinism: {'OK' if determinism_ok else 'FAIL'}" if determinism_ok is not None else ""))
        if have_baseline:
            if diff_rows:
                print(f"\n  CHANGED vs baseline ({len(diff_rows)} fields):")
                for r in diff_rows[:40]:
                    print(f"    {r['scenario']:28s} {r['field']:18s} {r['old']} -> {r['new']}")
            else:
                print("\n  No changes vs baseline (outputs stable).")
        else:
            print("\n  No baseline yet — run with --set-baseline to anchor one.")
        if set_baseline:
            print("\n  Baseline saved.")
        print()

    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="AdProof backend regression/sanity harness.")
    ap.add_argument("--set-baseline", action="store_true", help="save this run as the baseline")
    ap.add_argument("--quiet", action="store_true", help="minimal output")
    args = ap.parse_args()
    sys.exit(main_run(set_baseline=args.set_baseline, quiet=args.quiet))
