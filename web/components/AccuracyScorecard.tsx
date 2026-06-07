'use client';
// The credibility hero: "how accurate is AdProof on YOUR account?"
// Reads the latest stored backtest (predicted-vs-actual click-through on
// held-out ads) for the current workspace and shows it persistently — instead
// of only flashing it once at CSV-upload time. Honest about what it validates
// (the click-rate calibration the forecast is built on, NOT per-creative ROAS)
// and about sample size.
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { useApp } from '@/lib/store';
import { getLatestBacktest } from '@/lib/db';
import type { Backtest } from '@/lib/types';

function pct(x?: number | null, dp = 2): string {
  if (x == null) return '—';
  return `${(x * 100).toFixed(dp)}%`;
}

export function AccuracyScorecard() {
  const companyId = useApp((s) => s.currentCompanyId);
  const hydrated = useApp((s) => s.hydrated);
  const [state, setState] = useState<'loading' | 'none' | 'ready'>('loading');
  const [bt, setBt] = useState<Backtest | null>(null);
  const [measuredAt, setMeasuredAt] = useState<number | null>(null);

  useEffect(() => {
    if (!hydrated) return;
    let alive = true;
    getLatestBacktest(companyId ?? undefined)
      .then((r) => {
        if (!alive) return;
        if (!r) { setState('none'); return; }
        setBt(r.backtest); setMeasuredAt(r.measuredAt); setState('ready');
      })
      .catch(() => { if (alive) setState('none'); });
    return () => { alive = false; };
  }, [companyId, hydrated]);

  if (state === 'loading') return null;

  // Empty state — no uploaded history yet. Doubles as the motivator to connect
  // / upload (the flywheel's fuel).
  if (state === 'none') {
    return (
      <Card className="!bg-violet-soft !border-violet/30">
        <div className="flex items-start gap-3">
          <span className="text-2xl">🎯</span>
          <div className="flex-1">
            <div className="font-heading text-[15px] font-bold">How accurate is AdProof on YOUR ads?</div>
            <p className="text-[13px] text-ink mt-1 leading-snug">
              Upload your real ad history and we&apos;ll show our predicted-vs-actual track record on
              <em> your</em> account — the honest proof, not a generic claim.
            </p>
            <Link href="/data" className="inline-block mt-2 text-coral font-semibold text-[13px]">Upload ad history →</Link>
          </div>
        </div>
      </Card>
    );
  }

  // Backtest exists but couldn't validate over time (e.g. single reporting period).
  if (bt && !bt.usable) {
    return (
      <Card className="!bg-warning-soft !border-warning/30">
        <div className="font-heading text-[15px] font-bold">Accuracy check — not enough to validate yet</div>
        <p className="text-[13px] text-ink mt-1 leading-snug">{bt.reason}</p>
        <Link href="/data" className="inline-block mt-2 text-coral font-semibold text-[13px]">Re-upload with a daily/weekly breakdown →</Link>
      </Card>
    );
  }
  if (!bt) return null;

  const med = bt.median_abs_pct_error ?? null;
  const within30 = bt.within_30pct ?? null;
  const n = bt.n_test ?? 0;
  const conf = n >= 20 ? { tone: 'success' as const, label: 'high confidence' }
    : n >= 8 ? { tone: 'lime' as const, label: 'medium confidence' }
    : { tone: 'warning' as const, label: 'early — small sample' };

  return (
    <Card className="!bg-lime-soft !border-lime-deep/30">
      <div className="flex items-center justify-between mb-1">
        <div className="text-[11.5px] text-lime-deep font-bold uppercase tracking-[0.09em]">Proven on your account</div>
        <Pill tone={conf.tone}>{conf.label}</Pill>
      </div>
      <div className="flex items-end gap-3 flex-wrap">
        <div className="display-italic text-[40px] leading-none">
          ±{med != null ? Math.round(med * 100) : '—'}%
        </div>
        <div className="text-[13.5px] text-ink mb-1 max-w-[460px]">
          typical miss on our click-through call, across <strong>{n}</strong> of your ads we held out and
          predicted blind.
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mt-3 text-[13px]">
        <div>
          <div className="text-ink-muted text-[11.5px]">Within ±30%</div>
          <div className="font-semibold">{within30 != null ? Math.round(within30 * 100) : '—'}% of ads</div>
        </div>
        <div>
          <div className="text-ink-muted text-[11.5px]">We predicted</div>
          <div className="font-semibold font-mono">{pct(bt.agg_predicted_ctr)} CTR</div>
        </div>
        <div>
          <div className="text-ink-muted text-[11.5px]">Actual was</div>
          <div className="font-semibold font-mono">{pct(bt.agg_actual_ctr)} CTR</div>
        </div>
      </div>
      <div className="text-[11.5px] text-ink-muted mt-3 leading-snug">
        {bt.split}. Validates the click-rate calibration the forecast is built on — not per-creative ROAS
        (that needs creative files + conversions).
        {measuredAt && <> · measured {new Date(measuredAt).toLocaleDateString('en-GB')}</>}
      </div>
    </Card>
  );
}
