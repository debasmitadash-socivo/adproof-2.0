'use client';
// Compact dashboard cards for the Accuracy Ledger + Protected budget.
// Self-contained: fetches predictions/outcomes for the active workspace and
// degrades gracefully at every data stage (no forecasts yet → no outcomes
// yet → no matches yet → real numbers).
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { useApp } from '@/lib/store';
import { listCreativeScores, listOutcomes } from '@/lib/db';
import type { PredictionRow, OutcomeRow } from '@/lib/db';
import {
  matchLedger, ledgerStats, protectedBudget,
} from '@/lib/accuracy';
import type { LedgerStats, ProtectedBudget } from '@/lib/accuracy';

export function useAccuracyData() {
  const currentCompanyId = useApp((s) => s.currentCompanyId);
  const campaigns = useApp((s) => s.savedCampaigns);
  const [predictions, setPredictions] = useState<PredictionRow[]>([]);
  const [outcomes, setOutcomes] = useState<OutcomeRow[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoaded(false);
    Promise.all([
      listCreativeScores(currentCompanyId ?? undefined),
      listOutcomes(currentCompanyId ?? undefined),
    ]).then(([p, o]) => {
      if (!alive) return;
      setPredictions(p); setOutcomes(o); setLoaded(true);
    }).catch(() => { if (alive) setLoaded(true); });
    return () => { alive = false; };
  }, [currentCompanyId]);

  const campaignNames = new Map(campaigns.map((c) => [c.id, c.name]));
  const { matches, unmatchedPredictions, lowVolumeMatches } =
    matchLedger(predictions, outcomes, campaignNames);
  const stats = ledgerStats(matches);
  const budgets = campaigns.map((c) => c.budget).filter((b): b is number => typeof b === 'number' && b > 0);
  const shield = protectedBudget(predictions, outcomes, budgets);

  return {
    loaded, predictions, outcomes, matches, stats, shield,
    unmatchedPredictions, lowVolumeMatches,
  };
}

export function AccuracyStatCards({
  stats, shield, loaded, hasOutcomes, currency, compact,
}: {
  stats: LedgerStats;
  shield: ProtectedBudget;
  loaded: boolean;
  hasOutcomes: boolean;
  currency: string;
  compact?: boolean;
}) {
  if (!loaded) return null;

  return (
    <div className={compact ? 'grid grid-cols-1 sm:grid-cols-2 gap-3 mb-6' : 'grid grid-cols-1 sm:grid-cols-2 gap-4'}>
      {/* ACCURACY */}
      <Card className="!p-4">
        <div className="flex items-center gap-2 mb-1">
          <div className="text-[11px] text-ink-muted uppercase tracking-[0.08em] font-bold">Forecast accuracy — your account</div>
          <Pill tone="violet">receipts</Pill>
        </div>
        {stats.nMatches > 0 ? (
          <>
            <div className="display-italic text-[30px] leading-tight">
              {stats.nWithin25}/{stats.nMatches}
              <span className="text-[14px] font-sans not-italic text-ink-muted ml-2">within ±25% of real CTR</span>
            </div>
            <div className="text-[12.5px] text-ink-muted mt-1">
              {stats.medianAbsPctError != null && <>Median error {Math.round(stats.medianAbsPctError * 100)}%.</>}
              {stats.rankingPairs > 0 && <> Ranked the better ad right {stats.rankingWins}/{stats.rankingPairs} times.</>}
              {' '}<Link href="/accuracy" className="text-violet underline">Every prediction →</Link>
            </div>
          </>
        ) : hasOutcomes ? (
          <div className="text-[13px] text-ink-muted">
            Real results are syncing, but none match a forecast yet. Name your live ads
            after your AdProof campaigns and the ledger fills itself.{' '}
            <Link href="/accuracy" className="text-violet underline">How matching works →</Link>
          </div>
        ) : (
          <div className="text-[13px] text-ink-muted">
            Forecast first, then connect your ad account on the{' '}
            <Link href="/data" className="text-violet underline">Data page</Link> — every prediction
            gets checked against what really happened, and this card shows the score.
          </div>
        )}
      </Card>

      {/* PROTECTED BUDGET */}
      <Card className="!p-4">
        <div className="flex items-center gap-2 mb-1">
          <div className="text-[11px] text-ink-muted uppercase tracking-[0.08em] font-bold">Protected budget</div>
          {shield.spendBasis === 'your_outcomes' && <Pill tone="success">based on your real spend</Pill>}
          {shield.spendBasis === 'campaign_budgets' && <Pill tone="muted">based on your planned budgets</Pill>}
        </div>
        {shield.caughtCount > 0 && shield.protectedAmount != null ? (
          <>
            <div className="display-italic text-[30px] leading-tight">
              ≈ {currency} {Math.round(shield.protectedAmount).toLocaleString()}
            </div>
            <div className="text-[12.5px] text-ink-muted mt-1">
              {shield.caughtCount} creative{shield.caughtCount === 1 ? '' : 's'} flagged before spend × your average
              test cost of {currency} {Math.round(shield.avgTestSpend ?? 0).toLocaleString()}/ad
              {shield.spendBasis === 'your_outcomes' ? ' (from your real results)' : ' (from your planned budgets)'}.
              {' '}<Link href="/accuracy" className="text-violet underline">See the math →</Link>
            </div>
          </>
        ) : shield.caughtCount > 0 ? (
          <div className="text-[13px] text-ink-muted">
            <strong>{shield.caughtCount} creative{shield.caughtCount === 1 ? '' : 's'} caught</strong> before
            spend. Connect results on the <Link href="/data" className="text-violet underline">Data page</Link> so
            we can value that in your money, not a guess.
          </div>
        ) : (
          <div className="text-[13px] text-ink-muted">
            When a forecast catches an ad that shouldn&apos;t run, the test budget it would have burned
            shows up here — valued at <em>your</em> average test cost, never a made-up number.
          </div>
        )}
      </Card>
    </div>
  );
}
