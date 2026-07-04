// P3a — hierarchical calibration anchors with empirical-Bayes shrinkage.
//
// The old anchor was winner-takes-all: walk (segment×interest) → segment →
// interest → platform → overall and take the FIRST cell that exists. That
// creates a cliff — a 3-ad cell fully overrides everything below it, and a
// 2-ad cell is fully ignored. Real statistics blend instead: each level's
// estimate is pooled with its parent's, weighted by how much data the level
// actually has (partial pooling). With 3 ads you get mostly-parent,
// slightly-you; with 40 ads you get mostly-you. No cliffs, ever.
//
// The pooling chain, most general → most specific:
//   format benchmark (prior) → overall account → platform → interest →
//   segment → (segment × interest)
// Each present level updates the running estimate:
//   est = (n·level + K·est_prev) / (n + K)
// where n = the level's ad count and K = the parent's "pseudo-ads" strength.
// K_ADS = 8 means: a level with 8 ads is trusted 50/50 against its parent;
// 24 ads → 75%; 3 ads → 27%. The benchmark prior enters with K_BENCH
// pseudo-ads so a thin account leans on the published number instead of
// swinging wildly on 2 ads' luck.
//
// Pure functions, no I/O — unit-tested alongside lib/accuracy.ts.
import type { AccountCalibration, PlatformCalibration } from './types';

export const K_ADS = 8;      // parent strength when pooling account levels
export const K_BENCH = 12;   // benchmark prior strength (pseudo-ads)

export type AnchorPick = {
  source: string | null;     // most specific level that contributed (legacy format)
  nAds: number | null;       // that level's ad count (legacy meaning)
  ctr: number | null;
  cpm: number | null;
  cvr: number | null;
  // P3a additions — how much of the final CTR estimate comes from the
  // account's own data (vs the benchmark prior). 0..1. Surfaceable in UI.
  weightOnYourData: number;
  totalAdsUsed: number;      // sum of ads across contributing levels
};

export function calibrationPlatformKey(platformId: string): string {
  const p = platformId.toLowerCase();
  if (p.includes('instagram')) return 'meta_instagram';
  if (p.includes('facebook') || p.includes('meta')) return 'meta_facebook';
  if (p.includes('linkedin')) return 'linkedin';
  if (p.includes('tiktok')) return 'tiktok';
  if (p.includes('youtube')) return 'youtube';
  if (p.includes('google') || p.includes('search')) return 'google_search';
  return platformId;
}

// Pillar B+: same interest taxonomy as outcomes.INTEREST_BUCKETS (Python).
// Keep in sync — same slug + priority order so the frontend's calibration
// lookup matches what the backend's ingest tagged.
const INTEREST_PATTERNS: ReadonlyArray<readonly [string, readonly string[]]> = [
  ['fitness',       ['fitness', 'gym', 'workout', 'yoga', 'running', 'cycling', 'crossfit', 'athleisure']],
  ['fashion',       ['fashion', 'apparel', 'clothing', 'streetwear', 'menswear', 'womenswear']],
  ['beauty',        ['beauty', 'skincare', 'makeup', 'cosmetic', 'haircare', 'fragrance']],
  ['tech',          ['tech', 'electronics', 'gadget', 'saas', 'software', 'ai', 'gaming', 'developer', 'startup']],
  ['travel',        ['travel', 'vacation', 'holiday', 'flights', 'hotels', 'tourism']],
  ['food',          ['food', 'drink', 'beverage', 'restaurant', 'cooking', 'recipe', 'foodie', 'coffee', 'wine']],
  ['home',          ['home', 'diy', 'furniture', 'interior', 'decor', 'garden', 'kitchen']],
  ['finance',       ['finance', 'investing', 'crypto', 'trading', 'wealth', 'loans', 'mortgage']],
  ['automotive',    ['automotive', 'auto', 'cars', 'ev', 'electric vehicle', 'motorbike']],
  ['entertainment', ['entertainment', 'movies', 'music', 'streaming', 'podcast', 'reading', 'books']],
  ['business',      ['business', 'b2b', 'professional', 'decision maker', 'marketing', 'sales', 'operations', 'c-suite', 'leadership']],
  ['wellness',      ['wellness', 'mindfulness', 'mental health', 'self-care', 'meditation', 'sleep']],
];

export function interestsFromText(text: string): string[] {
  const hay = (text || '').toLowerCase();
  if (!hay.trim()) return [];
  const hits: string[] = [];
  for (const [slug, patterns] of INTEREST_PATTERNS) {
    if (patterns.some((p) => hay.includes(p))) hits.push(slug);
  }
  return hits;
}

export function interestsFromChipIds(chipIds: string[]): string[] {
  if (!chipIds.length) return [];
  const bag = chipIds
    .filter((c) => !c.startsWith('gender:') && !c.startsWith('location:') && !c.startsWith('age:'))
    .map((c) => c.split(':').slice(1).join(' ').toLowerCase())
    .join(' ');
  return interestsFromText(bag);
}

// ---------------------------------------------------------------------------
// Shrinkage
// ---------------------------------------------------------------------------

/** One metric's running pooled estimate. */
interface Pooled {
  value: number | null;      // current estimate
  accountWeight: number;     // 0..1 share of the estimate from account data
  hasAccountData: boolean;
}

/** Pool a level's observation into the running estimate. */
function pool(prev: Pooled, levelValue: number | null | undefined,
  nAds: number, k: number): Pooled {
  if (levelValue == null || !(nAds > 0)) return prev;
  if (prev.value == null) {
    // No prior at all — the level stands alone (fully account data).
    return { value: levelValue, accountWeight: 1, hasAccountData: true };
  }
  const w = nAds / (nAds + k);          // weight on this level's own data
  return {
    value: w * levelValue + (1 - w) * prev.value,
    // The level's data is account data; the residual keeps the previous mix.
    accountWeight: w + (1 - w) * prev.accountWeight,
    hasAccountData: true,
  };
}

/** Best cell across the user's interests (largest n wins), or null. */
function bestInterestCell(
  cells: Record<string, PlatformCalibration> | undefined,
  interests: string[],
): { cell: PlatformCalibration; interest: string } | null {
  if (!cells || !interests.length) return null;
  let best: { cell: PlatformCalibration; interest: string } | null = null;
  for (const interest of interests) {
    const cell = cells[interest];
    if (cell && cell.real_ctr != null
      && (!best || (cell.n_ads ?? 0) > (best.cell.n_ads ?? 0))) {
      best = { cell, interest };
    }
  }
  return best;
}

/**
 * Hierarchical anchor with partial pooling.
 *
 * `benchmark` is the chosen format's published CTR/CPM — the root prior.
 * When null (shouldn't happen in the wizard, but defensively), pooling
 * starts at the account's overall average instead.
 *
 * Honesty rules:
 * - ctr/cpm are returned only when SOME account data contributed — a pure
 *   benchmark answer returns nulls so the backend's own benchmark path
 *   (and its provenance wording) stays authoritative.
 * - cvr is returned only when the account's share of the CVR estimate is
 *   ≥ 50% — otherwise the honest-ROAS scenario band (P1) stays in charge
 *   rather than a prior-dressed-as-your-data.
 */
export function pickCalibrationAnchor(
  cal: AccountCalibration,
  segment: string | null,
  interests: string[],
  platformKey: string,
  benchmark?: { ctr?: number | null; cpm?: number | null } | null,
): AnchorPick {
  // Assemble the chain, most general first. Each entry: cell + its n.
  const levels: { pc: Partial<PlatformCalibration>; n: number; source: string }[] = [];
  if (cal.overall?.real_ctr != null) {
    levels.push({ pc: cal.overall, n: cal.overall.n_ads ?? 0, source: 'overall' });
  }
  const plat = cal.by_platform?.[platformKey];
  if (plat?.real_ctr != null) {
    levels.push({ pc: plat, n: plat.n_ads ?? 0, source: `platform:${platformKey}` });
  }
  const interestPick = bestInterestCell(cal.by_interest, interests);
  if (interestPick) {
    levels.push({
      pc: interestPick.cell, n: interestPick.cell.n_ads ?? 0,
      source: `interest:${interestPick.interest}`,
    });
  }
  if (segment && cal.by_segment?.[segment]?.real_ctr != null) {
    const seg = cal.by_segment[segment];
    levels.push({ pc: seg, n: seg.n_ads ?? 0, source: `segment:${segment}` });
  }
  if (segment) {
    const cellPick = bestInterestCell(cal.by_segment_interest?.[segment], interests);
    if (cellPick) {
      levels.push({
        pc: cellPick.cell, n: cellPick.cell.n_ads ?? 0,
        source: `segment:${segment}:interest:${cellPick.interest}`,
      });
    }
  }

  if (!levels.length) {
    return { source: null, nAds: null, ctr: null, cpm: null, cvr: null,
      weightOnYourData: 0, totalAdsUsed: 0 };
  }

  // Root prior: the format benchmark, entering with K_BENCH pseudo-ads.
  let ctr: Pooled = benchmark?.ctr != null
    ? { value: benchmark.ctr, accountWeight: 0, hasAccountData: false }
    : { value: null, accountWeight: 0, hasAccountData: false };
  let cpm: Pooled = benchmark?.cpm != null
    ? { value: benchmark.cpm, accountWeight: 0, hasAccountData: false }
    : { value: null, accountWeight: 0, hasAccountData: false };
  // No benchmark prior exists for CVR — the P1 scenario band is the prior.
  let cvr: Pooled = { value: null, accountWeight: 0, hasAccountData: false };

  let totalAds = 0;
  let cvrAds = 0;                 // ads that actually carried conversion data
  for (let i = 0; i < levels.length; i++) {
    const { pc, n } = levels[i];
    // First account level pools against the benchmark with K_BENCH;
    // deeper levels pool against the running estimate with K_ADS.
    const k = i === 0 && !ctr.hasAccountData ? K_BENCH : K_ADS;
    ctr = pool(ctr, pc.real_ctr, n, k);
    cpm = pool(cpm, pc.real_cpm, n, i === 0 && !cpm.hasAccountData ? K_BENCH : K_ADS);
    cvr = pool(cvr, pc.real_cvr, n, K_ADS);
    if (pc.real_cvr != null && n > 0) cvrAds += n;
    totalAds += n;
  }

  const deepest = levels[levels.length - 1];
  // CVR has no benchmark prior to blend against (the P1 scenario band IS the
  // prior), so accountWeight can't gate it — the first level would always
  // claim weight 1. Gate on volume instead: claiming "calibrated to your
  // data" requires at least K_BENCH ads' worth of conversion history, the
  // same evidence the benchmark itself would have counted for.
  const cvrTrusted = cvr.hasAccountData && cvrAds >= K_BENCH;
  return {
    source: deepest.source,
    nAds: deepest.n || null,
    ctr: ctr.hasAccountData ? ctr.value : null,
    cpm: cpm.hasAccountData ? cpm.value : null,
    cvr: cvrTrusted ? cvr.value : null,
    weightOnYourData: ctr.accountWeight,
    totalAdsUsed: totalAds,
  };
}
