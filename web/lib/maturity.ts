// Account Signal — where this workspace's DATA maturity actually stands,
// and what that means for how aggressively to bid.
//
// Two sources of truth, in strict priority order:
//  1. The platform's OWN learning-phase state per ad set (Meta's
//     learning_stage_info, captured at sync) — delivery-system reality,
//     zero heuristics. When present, it drives the headline.
//  2. AdProof's existing calibration gates (the same K_ADS / K_BENCH /
//     auction-fit thresholds that already gate forecasts) — used to grade
//     how deep OUR model's knowledge of the account goes.
//
// Deliberately NOT here: an invented 0–100 score. The only quantitative
// claim the Signal card makes is the measured forecast error from the
// accuracy ledger — a number with teeth, or "not enough matched forecasts
// yet" when it doesn't have them.
import type { AccountCalibration, AdsetStage } from './types';
import type { LedgerStats } from './accuracy';
import { K_ADS, K_BENCH } from './anchor';

export type SignalStage = 'cold' | 'learning' | 'limited' | 'calibrated' | 'optimized';

export interface SignalReadout {
  stage: SignalStage;
  label: string;                    // human name for the stage
  // Meta's real learning-phase tallies (only when a live pull captured them)
  platformTruth: {
    provider: string;
    capturedAt: string | null;
    learning: number;               // ad sets still in learning
    limited: number;                // learning limited (Meta status FAIL)
    exited: number;                 // exited learning (SUCCESS)
    activeAdsets: number;
  } | null;
  // What our calibration actually knows (drives forecast quality)
  depth: {
    nAds: number;
    anchorFromAccount: boolean;     // CTR/CPM anchored on real data
    cvrTrusted: boolean;            // ≥ K_BENCH conversion-carrying ads
    fatigueFitted: boolean;
    seasonalityFitted: boolean;
    breakdownsPresent: boolean;     // age×gender cells → Lab conditioning
  };
  // The claim with teeth — measured, never invented.
  measured: { nMatches: number; medianAbsPctError: number | null } | null;
  // Why this stage, and the ordered unlocks toward the next one.
  reasons: string[];
  nextSteps: string[];
  // Stage-appropriate bidding posture (grounded in Meta's published
  // learning-phase guidance + this account's own fitted numbers).
  bidding: string;
}

const LABEL: Record<SignalStage, string> = {
  cold: 'Cold start',
  learning: 'Learning',
  limited: 'Learning limited',
  calibrated: 'Calibrated',
  optimized: 'Optimized',
};

export function classifySignal(opts: {
  cal: AccountCalibration | null;
  nOutcomeAds: number;              // distinct ads in stored outcomes
  ledger: LedgerStats | null;
  hasBreakdowns?: boolean;          // age×gender rows exist (Lab conditioning)
  provider?: string;
}): SignalReadout {
  const { cal, nOutcomeAds, ledger } = opts;

  // ---- Platform truth (Meta learning_stage_info), when captured ----------
  const stages: AdsetStage[] = cal?.adset_stages ?? [];
  const active = stages.filter((s) => s.effective_status === 'ACTIVE');
  const truth = stages.length ? {
    provider: opts.provider ?? 'meta',
    capturedAt: cal?.adset_stages_at ?? null,
    learning: active.filter((s) => s.learning_status === 'LEARNING').length,
    limited: active.filter((s) => s.learning_status === 'FAIL').length,
    exited: active.filter((s) => s.learning_status === 'SUCCESS').length,
    activeAdsets: active.length,
  } : null;

  // ---- Calibration depth (the gates that already exist elsewhere) --------
  const nAds = cal?.overall?.n_ads ?? nOutcomeAds;
  const anchorFromAccount = !!cal?.usable;
  const convAds = countConversionAds(cal);
  const cvrTrusted = convAds >= K_BENCH;
  const fatigueFitted = !!(cal?.auction?.fatigue?.usable
    && (cal.auction.fatigue.lambda_per_exposure ?? 0) > 0);
  const seasonalityFitted = !!cal?.auction?.cpm_seasonality?.usable;
  const breakdownsPresent = !!opts.hasBreakdowns;
  const depth = { nAds, anchorFromAccount, cvrTrusted, fatigueFitted,
    seasonalityFitted, breakdownsPresent };

  const measured = ledger && ledger.nMatches >= 5
    ? { nMatches: ledger.nMatches, medianAbsPctError: ledger.medianAbsPctError }
    : null;

  // ---- Stage decision -----------------------------------------------------
  const reasons: string[] = [];
  const nextSteps: string[] = [];
  let stage: SignalStage;

  if (!cal && nOutcomeAds === 0) {
    stage = 'cold';
    reasons.push('No ad history connected — forecasts run on industry benchmarks.');
    nextSteps.push('Connect an ad account (Data page) or upload a CSV export.',
      'Run one Pull & calibrate to unlock your real CTR/CPM anchors.');
  } else if (truth && truth.activeAdsets > 0 && truth.limited > truth.exited) {
    // The platform itself says most active ad sets can't gather signal.
    stage = 'limited';
    reasons.push(`Meta reports ${truth.limited} of ${truth.activeAdsets} active ad sets as `
      + 'Learning Limited — the delivery system can\'t gather its ~50 weekly events.');
    nextSteps.push('Consolidate ad sets so conversion events pool instead of splitting.',
      'Loosen or remove cost/bid caps until learning exits.',
      'Check daily budget ≥ (target CPA × 50) ÷ 7 for the main ad set.');
  } else if (!anchorFromAccount || nAds < K_ADS) {
    stage = 'learning';
    reasons.push(nAds > 0
      ? `${nAds} real ad${nAds === 1 ? '' : 's'} of history — below the ${K_ADS}-ad bar where your data starts outweighing benchmarks.`
      : 'History connected but not yet calibrated.');
    nextSteps.push('Sync a longer date range (or upload more history) to pass '
      + `${K_ADS} distinct ads.`,
      'Keep campaign structure stable — frequent edits reset platform learning.');
  } else if (cvrTrusted && fatigueFitted && seasonalityFitted) {
    stage = 'optimized';
    reasons.push('Full-depth calibration: trusted conversion rate, fitted fatigue decay and CPM seasonality.');
    nextSteps.push('Keep syncing monthly so the fits stay fresh.',
      'Use the Lab\'s Living Market to shift budget toward your strongest cells.');
  } else {
    stage = 'calibrated';
    reasons.push(`CTR/CPM anchored on your ${nAds} real ads.`);
    if (!cvrTrusted) nextSteps.push(`Conversion rate still blends with industry priors — needs ≥${K_BENCH} conversion-carrying ads (have ${convAds}).`);
    if (!fatigueFitted) nextSteps.push('Fatigue decay not yet fitted — needs 8+ ads with varied frequency.');
    if (!seasonalityFitted) nextSteps.push('CPM seasonality not yet fitted — needs 12+ dated ads across 2+ months.');
  }

  if (truth && stage !== 'limited' && truth.learning > 0) {
    reasons.push(`Meta reports ${truth.learning} active ad set${truth.learning === 1 ? '' : 's'} still in learning.`);
  }

  const bidding: Record<SignalStage, string> = {
    cold: 'When you launch: broad audience, Highest-Volume bidding, no caps — a cap now starves the platform of the events it needs to learn.',
    learning: 'No bid caps yet. Consolidate rather than split ad sets, and avoid frequent edits — each significant edit resets the learning clock.',
    limited: 'Fix delivery before efficiency: loosen caps, widen the audience or raise budget until ad sets exit Learning Limited — capped bids are the most common cause.',
    calibrated: 'Safe to test a Cost Cap ~1.3–1.5× your blended CPA (generous, so delivery doesn\'t choke). Time creative refreshes with your fitted fatigue curve.',
    optimized: 'Tighten toward Cost Cap / ROAS floor at your calibrated numbers; scale budgets in ≤20% steps to avoid learning resets.',
  };

  return { stage, label: LABEL[stage], platformTruth: truth, depth, measured,
    reasons, nextSteps, bidding: bidding[stage] };
}

// Conversion-carrying ad count across platform calibrations — the same
// volume gate anchor.ts uses for trusting CVR.
function countConversionAds(cal: AccountCalibration | null): number {
  if (!cal) return 0;
  let n = 0;
  const plats = Object.values(cal.by_platform ?? {});
  for (const p of plats) {
    if (p?.real_cvr != null && p.n_ads) n += p.n_ads;
  }
  if (n === 0 && cal.overall?.real_cvr != null) n = cal.overall?.n_ads ?? 0;
  return n;
}
