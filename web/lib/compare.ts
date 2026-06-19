// Variant comparison analysis — turns a campaign's variants into a ranked
// "best / worst, and WHY" read. The ranking (relative order) is the
// trustworthy output; the absolute ROAS is directional only.
import type { SavedVariantResult } from './types';

export interface VariantMetrics {
  label: string;
  headline: string;
  thumbnailUrl: string | null;
  roas: number;
  roiPct: number;
  ctrPct: number;
  reach: number | null;
  cpm: number | null;
  // 0–1 creative drivers (higher = better)
  emotional: number | null;
  clarity: number | null;
  attention: number | null;
  relevance: number | null;
  brandFit: number | null;
  coherence: number | null;
  banLevel: string;
  runnable: boolean;
  forecastValid: boolean;
  economicsVerdict: string | null;
  isHeuristic: boolean;
}

// Human labels for the 0–1 driver dimensions used in the reasoning.
export const DRIVER_LABELS: Record<string, string> = {
  attention: 'stopping power',
  emotional: 'emotional pull',
  clarity: 'visual clarity',
  relevance: 'relevance of the value prop',
  brandFit: 'brand fit',
  coherence: 'image–copy match',
};

const num = (x: unknown, d: number | null = null): number | null =>
  typeof x === 'number' && !Number.isNaN(x) ? x : d;

export function variantMetrics(v: SavedVariantResult): VariantMetrics {
  const r = v.result;
  const vis = r.visual?.scores ?? {};
  return {
    label: v.label,
    headline: v.headline,
    thumbnailUrl: v.thumbnailUrl,
    roas: v.roasP50,
    roiPct: v.roiP50 * 100,
    ctrPct: v.ctrPct,
    reach: num(r.kpis?.reach?.value ?? r.plain_verdict?.reach_value ?? r.mc?.total_impressions),
    cpm: num(r.kpis?.cpm?.value),
    emotional: num(vis['emotional_arousal']),
    clarity: num(vis['visual_clarity']),
    attention: num(vis['attention_capture']),
    relevance: num(vis['relevance_potential']),
    brandFit: num(r.visual?.brand_relevance),
    coherence: num(r.visual?.image_copy_coherence),
    banLevel: String(r.visual?.ban_risk?.level ?? 'unknown'),
    runnable: r.viability ? r.viability.runnable !== false : true,
    forecastValid: r.viability ? r.viability.forecast_valid !== false : true,
    economicsVerdict: r.economics?.verdict ?? null,
    isHeuristic: r.visual?.is_heuristic ?? false,
  };
}

export interface CompareAnalysis {
  metrics: VariantMetrics[];
  ranked: VariantMetrics[];     // eligible variants, best → worst by ROAS
  best: VariantMetrics | null;  // null when every variant is void/blocked
  worst: VariantMetrics | null;
  bestReasons: string[];
  worstReasons: string[];
  allVoid: boolean;
  objective: string;     // awareness | consideration | conversion
  rankLabel: string;     // reach | CTR | ROAS — the metric variants are ranked by
}

const DRIVER_KEYS: (keyof VariantMetrics)[] = [
  'attention', 'emotional', 'clarity', 'relevance', 'brandFit', 'coherence',
];

function fieldAverages(metrics: VariantMetrics[]): Record<string, number> {
  const avg: Record<string, number> = {};
  for (const k of DRIVER_KEYS) {
    const vals = metrics.map((m) => m[k]).filter((x): x is number => typeof x === 'number');
    if (vals.length) avg[k as string] = vals.reduce((a, b) => a + b, 0) / vals.length;
  }
  return avg;
}

// Dimensions where `m` most exceeds (sign +1) or trails (sign -1) the field.
function topDeltas(m: VariantMetrics, avg: Record<string, number>, sign: 1 | -1, n = 2): string[] {
  const deltas: { key: string; delta: number; val: number }[] = [];
  for (const k of DRIVER_KEYS) {
    const v = m[k];
    const a = avg[k as string];
    if (typeof v === 'number' && typeof a === 'number') {
      deltas.push({ key: k as string, delta: (v - a) * sign, val: v });
    }
  }
  return deltas
    .filter((d) => d.delta > 0.04)            // only material gaps
    .sort((a, b) => b.delta - a.delta)
    .slice(0, n)
    .map((d) => `${DRIVER_LABELS[d.key]} (${Math.round(d.val * 100)}%)`);
}

export function analyzeVariants(variants: SavedVariantResult[]): CompareAnalysis {
  const metrics = variants.map(variantMetrics);
  // Rank by the objective's real metric — never ROAS on a non-conversion
  // campaign (ROAS only means something for a conversion objective).
  const objective = String(variants[0]?.result?.kpis?.objective ?? 'conversion');
  const rankLabel = objective === 'awareness' ? 'reach' : objective === 'consideration' ? 'CTR' : 'ROAS';
  const rankKey = (m: VariantMetrics) =>
    objective === 'awareness' ? (m.reach ?? 0) : objective === 'consideration' ? m.ctrPct : m.roas;
  const eligible = metrics.filter((m) => m.runnable && m.forecastValid);
  const ranked = [...eligible].sort((a, b) => rankKey(b) - rankKey(a));
  const allVoid = eligible.length === 0;

  const best = ranked[0] ?? null;
  // Worst = a void/blocked variant if any, else the lowest-ROAS eligible one.
  const voided = metrics.filter((m) => !m.runnable || !m.forecastValid);
  const worst = voided[0] ?? (ranked.length > 1 ? ranked[ranked.length - 1] : null);

  const avg = fieldAverages(metrics);
  const bestReasons: string[] = [];
  const worstReasons: string[] = [];

  if (best) {
    const wins = topDeltas(best, avg, 1);
    if (wins.length) bestReasons.push(`Leads the field on ${wins.join(' and ')}.`);
    if (best.economicsVerdict === 'comfortable')
      bestReasons.push('Its break-even maths clears with room to spare.');
    if (best.ctrPct > 0)
      bestReasons.push(`Highest modelled click-through of the runnable variants (${best.ctrPct.toFixed(2)}%).`);
    if (!bestReasons.length)
      bestReasons.push('Edges ahead on the blended forecast, though the variants are close.');
  }

  if (worst) {
    if (!worst.runnable) {
      worstReasons.push("Won't run — a policy/ban issue voids it entirely, so its real ROAS is £0 regardless of the forecast.");
    } else if (!worst.forecastValid) {
      worstReasons.push('Forecast void — the image and copy/brand don\'t match, so no benchmark forecast applies.');
    } else {
      const losses = topDeltas(worst, avg, -1);
      if (losses.length) worstReasons.push(`Trails the field on ${losses.join(' and ')}.`);
      if (worst.economicsVerdict === 'shortfall')
        worstReasons.push('Its break-even maths falls short — modelled CTR is below what it needs.');
      if (!worstReasons.length)
        worstReasons.push('Lowest blended forecast, though the gap to the others is small.');
    }
  }

  return { metrics, ranked, best, worst, bestReasons, worstReasons, allVoid, objective, rankLabel };
}
