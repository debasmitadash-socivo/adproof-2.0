// The Accuracy Ledger's brain: join what AdProof PREDICTED (creative_scores)
// with what actually HAPPENED (ad_outcomes), then score ourselves.
//
// Pure functions only — no I/O — so every rule here is unit-testable and the
// numbers a customer sees can be audited line by line. Honesty rules:
//  - a prediction with no confident match is UNMATCHED, never force-paired
//  - stats come only from matched pairs with enough real volume to be a fair
//    test (min impressions gate)
//  - we grade ourselves on the metric we actually predicted (CTR always;
//    ROAS only when the outcome data has revenue)
import type { PredictionRow, OutcomeRow } from './db';

// ---------------------------------------------------------------------------
// Matching
// ---------------------------------------------------------------------------

const MIN_IMPRESSIONS = 500;          // below this, real CTR is too noisy to grade
const MATCH_BEFORE_MS = 7 * 864e5;    // outcome may start ≤7d before the forecast…
const MATCH_AFTER_MS = 120 * 864e5;   // …or up to 120d after it

export function normalizeName(s: string | null | undefined): string {
  return (s ?? '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function tokens(s: string): Set<string> {
  return new Set(normalizeName(s).split(' ').filter((t) => t.length >= 3));
}

/** Jaccard-ish token similarity, 0..1. Requires real word overlap — "ad 1"
 *  vs "ad 2" style near-empty names can't accidentally match. */
export function nameSimilarity(a: string, b: string): number {
  const ta = tokens(a); const tb = tokens(b);
  if (ta.size === 0 || tb.size === 0) return 0;
  let shared = 0;
  for (const t of ta) if (tb.has(t)) shared++;
  return shared / Math.max(ta.size, tb.size);
}

/** One ad's real performance, pooled across its daily/breakdown rows. */
export interface PooledOutcome {
  key: string;                    // creative_url or normalized name
  adName: string;
  platform: string | null;        // one platform, or 'multi' when rows span several
  platforms: Set<string>;
  campaignName: string | null;
  adsetName: string | null;
  impressions: number;
  clicks: number;
  spend: number;
  revenue: number | null;
  conversions: number | null;
  reach: number | null;           // max across rows (reach doesn't sum cleanly)
  frequency: number | null;       // impression-weighted average
  realCtr: number | null;
  realRoas: number | null;
  firstDate: string | null;
  lastDate: string | null;
  creativeUrls: Set<string>;
}

export type PoolLevel = 'ad' | 'adset' | 'campaign';

export function poolOutcomes(rows: OutcomeRow[], level: PoolLevel = 'ad'): PooledOutcome[] {
  const byKey = new Map<string, PooledOutcome>();
  const freqWeighted = new Map<string, number>();     // sum(frequency × impressions)
  for (const r of rows) {
    const name = level === 'campaign' ? (r.campaignName ?? r.adName)
      : level === 'adset' ? (r.adsetName ?? r.adName)
        : r.adName;
    const key = normalizeName(name) || r.creativeUrl || r.id;
    let p = byKey.get(key);
    if (!p) {
      p = {
        key, adName: name ?? '(unnamed)', platform: r.platform,
        platforms: new Set(), campaignName: r.campaignName ?? null,
        adsetName: r.adsetName ?? null,
        impressions: 0, clicks: 0, spend: 0, revenue: null, conversions: null,
        reach: null, frequency: null,
        realCtr: null, realRoas: null, firstDate: r.dateStart, lastDate: r.dateStart,
        creativeUrls: new Set(),
      };
      byKey.set(key, p);
    }
    p.impressions += r.impressions;
    p.clicks += r.clicks;
    p.spend += r.spend;
    if (r.revenue != null) p.revenue = (p.revenue ?? 0) + r.revenue;
    if (r.conversions != null) p.conversions = (p.conversions ?? 0) + r.conversions;
    // Don't let a null-platform row blank the whole ad — keep any non-null,
    // and track the full set so mixed FB+IG ads can say so.
    if (r.platform) { p.platforms.add(r.platform); p.platform = p.platform ?? r.platform; }
    if (r.campaignName && !p.campaignName) p.campaignName = r.campaignName;
    if (r.adsetName && !p.adsetName) p.adsetName = r.adsetName;
    if (r.reach != null) p.reach = Math.max(p.reach ?? 0, r.reach);
    if (r.frequency != null && r.impressions > 0) {
      freqWeighted.set(key, (freqWeighted.get(key) ?? 0) + r.frequency * r.impressions);
    }
    if (r.creativeUrl) p.creativeUrls.add(r.creativeUrl);
    if (r.dateStart && (!p.firstDate || r.dateStart < p.firstDate)) p.firstDate = r.dateStart;
    if (r.dateStart && (!p.lastDate || r.dateStart > p.lastDate)) p.lastDate = r.dateStart;
  }
  for (const p of byKey.values()) {
    p.realCtr = p.impressions > 0 ? p.clicks / p.impressions : null;
    p.realRoas = (p.revenue != null && p.spend > 0) ? p.revenue / p.spend : null;
    const fw = freqWeighted.get(p.key);
    if (fw != null && p.impressions > 0) p.frequency = fw / p.impressions;
    if (p.platforms.size > 1) p.platform = 'multi';
  }
  return [...byKey.values()];
}

export interface LedgerMatch {
  prediction: PredictionRow;
  campaignName: string | null;
  outcome: PooledOutcome;
  matchBasis: 'creative' | 'name';
  matchScore: number;             // 1 for creative match, similarity for name
  predictedCtr: number;           // fraction
  realCtr: number;                // fraction
  ctrAbsPctError: number;         // |pred-real|/real
  predictedRoas: number | null;
  realRoas: number | null;
}

/** Match each prediction to at most one pooled outcome; each outcome is used
 *  at most once (greedy, best-score-first). */
export function matchLedger(
  predictions: PredictionRow[],
  outcomes: OutcomeRow[],
  campaignNames: Map<string, string>,
): { matches: LedgerMatch[]; unmatchedPredictions: number; lowVolumeMatches: number } {
  const pooled = poolOutcomes(outcomes);
  const candidates: { pi: number; oi: number; basis: 'creative' | 'name'; score: number }[] = [];

  predictions.forEach((pred, pi) => {
    const campName = pred.campaignId ? campaignNames.get(pred.campaignId) ?? null : null;
    pooled.forEach((out, oi) => {
      // Date sanity: the ad should have started around/after the forecast.
      if (out.firstDate) {
        const started = new Date(out.firstDate).getTime();
        if (started < pred.createdAt - MATCH_BEFORE_MS
          || started > pred.createdAt + MATCH_AFTER_MS) return;
      }
      if (pred.creativeUrl && out.creativeUrls.has(pred.creativeUrl)) {
        candidates.push({ pi, oi, basis: 'creative', score: 1 });
        return;
      }
      // Name match: real ad name vs the AdProof campaign name (+ variant).
      if (campName) {
        const full = pred.adName && pred.adName.length > 1
          ? `${campName} ${pred.adName}` : campName;
        const sim = Math.max(nameSimilarity(out.adName, campName),
          nameSimilarity(out.adName, full));
        if (sim >= 0.5) candidates.push({ pi, oi, basis: 'name', score: sim });
      }
    });
  });

  candidates.sort((a, b) => b.score - a.score);
  const usedPred = new Set<number>(); const usedOut = new Set<number>();
  const matches: LedgerMatch[] = [];
  let lowVolume = 0;

  for (const c of candidates) {
    if (usedPred.has(c.pi) || usedOut.has(c.oi)) continue;
    const pred = predictions[c.pi]; const out = pooled[c.oi];
    if (pred.forecastCtr == null || out.realCtr == null) continue;
    usedPred.add(c.pi); usedOut.add(c.oi);
    if (out.impressions < MIN_IMPRESSIONS) { lowVolume++; continue; }
    matches.push({
      prediction: pred,
      campaignName: pred.campaignId ? campaignNames.get(pred.campaignId) ?? null : null,
      outcome: out,
      matchBasis: c.basis,
      matchScore: c.score,
      predictedCtr: pred.forecastCtr,
      realCtr: out.realCtr,
      ctrAbsPctError: Math.abs(pred.forecastCtr - out.realCtr) / Math.max(out.realCtr, 1e-9),
      predictedRoas: pred.forecastRoas,
      realRoas: out.realRoas,
    });
  }
  return {
    matches,
    unmatchedPredictions: predictions.length - usedPred.size,
    lowVolumeMatches: lowVolume,
  };
}

// ---------------------------------------------------------------------------
// Scoring ourselves
// ---------------------------------------------------------------------------

export interface LedgerStats {
  nMatches: number;
  nWithin25: number;                 // CTR within ±25% of real
  medianAbsPctError: number | null;  // on CTR
  // Pairwise ranking: of all pairs where we predicted a meaningful CTR gap,
  // how often was the predicted-better ad really better?
  rankingPairs: number;
  rankingWins: number;
  // ROAS ranking (only pairs where both ads have real revenue)
  roasPairs: number;
  roasWins: number;
}

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

export function ledgerStats(matches: LedgerMatch[]): LedgerStats {
  const errs = matches.map((m) => m.ctrAbsPctError);
  let rankingPairs = 0; let rankingWins = 0;
  let roasPairs = 0; let roasWins = 0;
  for (let i = 0; i < matches.length; i++) {
    for (let j = i + 1; j < matches.length; j++) {
      const a = matches[i]; const b = matches[j];
      // Only grade pairs where we actually claimed a difference (>10% rel).
      const predGap = Math.abs(a.predictedCtr - b.predictedCtr)
        / Math.max(Math.min(a.predictedCtr, b.predictedCtr), 1e-9);
      if (predGap > 0.10) {
        rankingPairs++;
        const predSign = Math.sign(a.predictedCtr - b.predictedCtr);
        const realSign = Math.sign(a.realCtr - b.realCtr);
        if (predSign === realSign) rankingWins++;
      }
      if (a.predictedRoas != null && b.predictedRoas != null
        && a.realRoas != null && b.realRoas != null
        && a.predictedRoas !== b.predictedRoas) {
        roasPairs++;
        if (Math.sign(a.predictedRoas - b.predictedRoas)
          === Math.sign(a.realRoas - b.realRoas)) roasWins++;
      }
    }
  }
  return {
    nMatches: matches.length,
    nWithin25: matches.filter((m) => m.ctrAbsPctError <= 0.25).length,
    medianAbsPctError: median(errs),
    rankingPairs, rankingWins, roasPairs, roasWins,
  };
}

// ---------------------------------------------------------------------------
// Protected budget — the personalised "what AdProof caught" number.
// ---------------------------------------------------------------------------
// Two honest, auditable components; never "you saved £X":
//  1) avoided waste: creatives we verdicted don't-run / underperforming,
//     valued at the account's REAL average per-ad test spend (from their own
//     synced outcomes; campaign-budget fallback clearly labelled)
//  2) how many launches we graded first (context, not money)

const CAUGHT_VERDICTS = new Set([
  'wont_run', 'broken_creative', 'underperforming', 'weak_engagement', 'void',
]);

export interface ProtectedBudget {
  caughtCount: number;               // bad creatives flagged before spend
  avgTestSpend: number | null;       // their real average per-ad spend
  spendBasis: 'your_outcomes' | 'campaign_budgets' | 'none';
  protectedAmount: number | null;    // caughtCount × avgTestSpend
  gradedCount: number;               // total forecasts made
}

export function protectedBudget(
  predictions: PredictionRow[],
  outcomes: OutcomeRow[],
  campaignBudgets: number[],
): ProtectedBudget {
  const caught = predictions.filter(
    (p) => p.verdictClass && CAUGHT_VERDICTS.has(p.verdictClass)).length;

  // Their real average per-ad test spend: pooled outcome spend per distinct ad.
  const pooled = poolOutcomes(outcomes).filter((p) => p.spend > 0);
  let avg: number | null = null;
  let basis: ProtectedBudget['spendBasis'] = 'none';
  if (pooled.length >= 3) {
    avg = pooled.reduce((s, p) => s + p.spend, 0) / pooled.length;
    basis = 'your_outcomes';
  } else if (campaignBudgets.length >= 3) {
    // Fallback: what they SAID they'd spend per test in the wizard.
    avg = campaignBudgets.reduce((s, b) => s + b, 0) / campaignBudgets.length;
    basis = 'campaign_budgets';
  }
  return {
    caughtCount: caught,
    avgTestSpend: avg,
    spendBasis: basis,
    protectedAmount: avg != null && caught > 0 ? caught * avg : null,
    gradedCount: predictions.length,
  };
}
