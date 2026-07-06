'use client';
// Account Signal — folded into existing surfaces (Data page card + dashboard
// badge), deliberately NOT a standalone page. Headline comes from the
// platform's own learning-phase state when a live pull captured it; depth
// comes from the same calibration gates that already govern forecasts; the
// only quantitative claim is the MEASURED forecast error from the accuracy
// ledger. Nothing here is an invented score.
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { useApp } from '@/lib/store';
import { getLatestCalibration, listBreakdowns } from '@/lib/db';
import { classifySignal } from '@/lib/maturity';
import type { SignalReadout, SignalStage } from '@/lib/maturity';
import { useAccuracyData } from '@/components/AccuracyCards';
import type { AccountCalibration } from '@/lib/types';

const STAGE_TONE: Record<SignalStage, 'muted' | 'warning' | 'danger' | 'coral' | 'success'> = {
  cold: 'muted', learning: 'warning', limited: 'danger',
  calibrated: 'coral', optimized: 'success',
};
const STAGE_ORDER: SignalStage[] = ['cold', 'learning', 'limited', 'calibrated', 'optimized'];

export function useSignal(): { readout: SignalReadout | null; loaded: boolean } {
  const currentCompanyId = useApp((s) => s.currentCompanyId);
  const { loaded: accLoaded, outcomes, stats } = useAccuracyData();
  const [cal, setCal] = useState<AccountCalibration | null>(null);
  const [hasBreakdowns, setHasBreakdowns] = useState(false);
  const [calLoaded, setCalLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    setCalLoaded(false);
    Promise.all([
      getLatestCalibration(currentCompanyId ?? undefined).catch(() => null),
      listBreakdowns(currentCompanyId ?? undefined).catch(() => []),
    ]).then(([c, bds]) => {
      if (!alive) return;
      setCal(c); setHasBreakdowns((bds?.length ?? 0) > 0); setCalLoaded(true);
    });
    return () => { alive = false; };
  }, [currentCompanyId]);

  const loaded = accLoaded && calLoaded;
  if (!loaded) return { readout: null, loaded: false };
  const nOutcomeAds = new Set(outcomes.map((o) => o.adName).filter(Boolean)).size;
  return {
    readout: classifySignal({ cal, nOutcomeAds, ledger: stats, hasBreakdowns }),
    loaded: true,
  };
}

/** Tiny inline badge (dashboard header). */
export function SignalBadge() {
  const { readout, loaded } = useSignal();
  if (!loaded || !readout) return null;
  return (
    <Link href="/data" title={readout.reasons[0] ?? ''}>
      <Pill tone={STAGE_TONE[readout.stage]} dot>Signal: {readout.label}</Pill>
    </Link>
  );
}

/** Full card (Data page). */
export function SignalCard() {
  const { readout, loaded } = useSignal();
  if (!loaded || !readout) return null;
  const r = readout;
  const rungs = STAGE_ORDER.filter((s) => s !== 'limited'); // ladder shows the healthy path
  const depthChecks: [string, boolean][] = [
    ['CTR/CPM anchored on your data', r.depth.anchorFromAccount],
    ['Conversion rate trusted', r.depth.cvrTrusted],
    ['Fatigue decay fitted', r.depth.fatigueFitted],
    ['CPM seasonality fitted', r.depth.seasonalityFitted],
    ['Audience breakdowns synced', r.depth.breakdownsPresent],
  ];
  return (
    <Card className="mb-5">
      <div className="flex items-center gap-2.5 flex-wrap mb-2">
        <div className="text-[11px] text-ink-muted uppercase tracking-[0.08em] font-bold">Account signal</div>
        <Pill tone={STAGE_TONE[r.stage]} dot>{r.label}</Pill>
        {r.measured ? (
          <span className="text-[12px] text-ink-muted">
            measured: median forecast error <strong className="text-ink">
              ±{Math.round((r.measured.medianAbsPctError ?? 0) * 100)}%</strong> over {r.measured.nMatches} matched forecasts
          </span>
        ) : (
          <span className="text-[12px] text-ink-faint">accuracy claim unlocks after 5 matched forecasts (Accuracy page)</span>
        )}
      </div>

      {/* Stage ladder */}
      <div className="flex items-center gap-1.5 mb-3 flex-wrap">
        {rungs.map((s, i) => {
          const reached = STAGE_ORDER.indexOf(r.stage === 'limited' ? 'learning' : r.stage) >= STAGE_ORDER.indexOf(s);
          return (
            <span key={s} className="flex items-center gap-1.5">
              {i > 0 && <span className="text-ink-faint text-[11px]">→</span>}
              <span className={`text-[11.5px] px-2 py-0.5 rounded-full border ${
                s === r.stage ? 'bg-coral-soft border-coral text-coral font-bold'
                  : reached ? 'border-border text-ink' : 'border-border-soft text-ink-faint'}`}>
                {s === 'cold' ? 'Cold start' : s[0].toUpperCase() + s.slice(1)}
              </span>
            </span>
          );
        })}
        {r.stage === 'limited' && (
          <Pill tone="danger">⚠ Learning limited — delivery stuck</Pill>
        )}
      </div>

      {/* Platform truth, when we have it */}
      {r.platformTruth && (
        <div className="text-[12.5px] text-ink mb-2">
          <strong>Meta&apos;s own delivery state</strong>
          {r.platformTruth.capturedAt && <span className="text-ink-faint"> (as of {r.platformTruth.capturedAt})</span>}:{' '}
          {r.platformTruth.exited} exited learning · {r.platformTruth.learning} learning · {r.platformTruth.limited} learning-limited
          {' '}of {r.platformTruth.activeAdsets} active ad sets — read directly from Meta, not estimated.
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 mb-3">
        {depthChecks.map(([label, ok]) => (
          <div key={label} className="text-[12.5px] flex items-center gap-2">
            <span className={ok ? 'text-lime-deep' : 'text-ink-faint'}>{ok ? '✓' : '○'}</span>
            <span className={ok ? 'text-ink' : 'text-ink-muted'}>{label}</span>
          </div>
        ))}
      </div>

      {r.nextSteps.length > 0 && (
        <div className="text-[12.5px] text-ink-muted mb-2">
          <strong className="text-ink">To reach the next stage:</strong>
          <ul className="list-disc ml-5 mt-0.5 space-y-0.5">
            {r.nextSteps.map((s) => <li key={s}>{s}</li>)}
          </ul>
        </div>
      )}

      <div className="text-[12.5px] bg-bg-deep border border-border rounded-md px-3 py-2">
        <strong>Bidding posture for this stage:</strong> {r.bidding}
        <span className="text-ink-faint"> (Meta learning-phase guidance{r.depth.anchorFromAccount ? ' + your calibrated numbers' : ''})</span>
      </div>
    </Card>
  );
}
