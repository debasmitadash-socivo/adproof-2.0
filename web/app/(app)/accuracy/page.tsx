'use client';
// The Accuracy Ledger — every prediction AdProof made for this workspace,
// checked against what actually happened, with the math in the open. This
// page is the product's proof-of-work: nothing on it is a claim, everything
// is a join between a stored forecast and a synced real result.
import Link from 'next/link';
import { Card, CardTitle } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { useApp } from '@/lib/store';
import { useAccuracyData, AccuracyStatCards } from '@/components/AccuracyCards';

function pct(x: number | null | undefined, dp = 2) {
  return x == null ? '—' : `${(x * 100).toFixed(dp)}%`;
}

export default function AccuracyPage() {
  const profile = useApp((s) => s.companyProfile);
  const currency = profile?.currency || 'GBP';
  const {
    loaded, predictions, outcomes, matches, stats, shield,
    unmatchedPredictions, lowVolumeMatches,
  } = useAccuracyData();

  return (
    <div className="max-w-5xl">
      <h1 className="display-italic text-[34px] mb-1">
        The <span className="gradient-text">accuracy ledger</span>
      </h1>
      <p className="text-ink-muted text-[14.5px] mb-6 max-w-2xl">
        Every forecast we made for this workspace, checked against what your ads really did.
        No cherry-picking: a prediction either matched a real result or it&apos;s counted as unmatched below.
      </p>

      <AccuracyStatCards
        stats={stats} shield={shield} loaded={loaded}
        hasOutcomes={outcomes.length > 0} currency={currency}
      />

      {loaded && matches.length > 0 && (
        <Card className="!p-0 overflow-hidden mt-5">
          <div className="px-5 py-3 bg-bg-deep text-[11.5px] text-ink-muted uppercase tracking-[0.06em] font-bold">
            Prediction vs reality — {matches.length} matched ad{matches.length === 1 ? '' : 's'}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="text-[10.5px] text-ink-faint uppercase tracking-[0.06em]">
                <tr>
                  <th className="text-left px-4 py-2.5">Forecast</th>
                  <th className="text-left px-3 py-2.5">Matched real ad</th>
                  <th className="text-left px-3 py-2.5">Match</th>
                  <th className="text-right px-3 py-2.5">Predicted CTR</th>
                  <th className="text-right px-3 py-2.5">Real CTR</th>
                  <th className="text-right px-3 py-2.5">Error</th>
                  <th className="text-right px-3 py-2.5">Pred. ROAS</th>
                  <th className="text-right px-3 py-2.5">Real ROAS</th>
                </tr>
              </thead>
              <tbody>
                {matches.map((m, i) => (
                  <tr key={i} className="border-t border-border-soft">
                    <td className="px-4 py-2.5">
                      <div className="font-semibold truncate max-w-[220px]">{m.campaignName ?? '(campaign)'}</div>
                      <div className="text-[11px] text-ink-faint">
                        variant {m.prediction.adName ?? '—'} · {new Date(m.prediction.createdAt).toLocaleDateString()}
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="truncate max-w-[220px]">{m.outcome.adName}</div>
                      <div className="text-[11px] text-ink-faint">
                        {m.outcome.impressions.toLocaleString()} impressions
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <Pill tone={m.matchBasis === 'creative' ? 'success' : 'muted'}>
                        {m.matchBasis === 'creative' ? 'creative file' : `name ${Math.round(m.matchScore * 100)}%`}
                      </Pill>
                    </td>
                    <td className="text-right px-3 py-2.5 font-mono">{pct(m.predictedCtr)}</td>
                    <td className="text-right px-3 py-2.5 font-mono">{pct(m.realCtr)}</td>
                    <td className="text-right px-3 py-2.5">
                      <Pill tone={m.ctrAbsPctError <= 0.25 ? 'success' : m.ctrAbsPctError <= 0.5 ? 'warning' : 'danger'}>
                        {Math.round(m.ctrAbsPctError * 100)}%
                      </Pill>
                    </td>
                    <td className="text-right px-3 py-2.5 font-mono">
                      {m.predictedRoas != null ? `${m.predictedRoas.toFixed(2)}×` : '—'}
                    </td>
                    <td className="text-right px-3 py-2.5 font-mono">
                      {m.realRoas != null ? `${m.realRoas.toFixed(2)}×` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {loaded && (
        <Card className="mt-5">
          <CardTitle>How this works — and what&apos;s counted</CardTitle>
          <ul className="text-[13px] space-y-1.5 text-ink list-disc pl-5">
            <li>
              <strong>{predictions.length}</strong> forecast{predictions.length === 1 ? '' : 's'} stored for this
              workspace · <strong>{outcomes.length}</strong> real result row{outcomes.length === 1 ? '' : 's'} synced.
            </li>
            <li>
              A forecast matches a real ad by <strong>creative file</strong> (same uploaded image/video) or by{' '}
              <strong>name</strong> (your live ad&apos;s name vs your AdProof campaign name — name them alike and
              matching is automatic).
            </li>
            <li>
              <strong>{unmatchedPredictions}</strong> prediction{unmatchedPredictions === 1 ? '' : 's'} unmatched
              {lowVolumeMatches > 0 && <> · {lowVolumeMatches} matched but excluded (&lt;500 impressions — too little
                data to grade fairly)</>}. Unmatched isn&apos;t hidden; it&apos;s right here.
            </li>
            <li>
              <strong>Protected budget math:</strong> creatives verdicted &quot;won&apos;t run / underperforming&quot;
              ({shield.caughtCount}) × your average per-ad test spend
              ({shield.avgTestSpend != null ? `${currency} ${Math.round(shield.avgTestSpend).toLocaleString()}` : 'unknown yet'}
              {shield.spendBasis === 'your_outcomes' ? ', from your synced results' :
                shield.spendBasis === 'campaign_budgets' ? ', from your planned budgets' : ''}).
              We say &quot;estimated waste avoided&quot;, never &quot;you saved&quot; — we can&apos;t observe the
              universe where you didn&apos;t test.
            </li>
          </ul>
          {outcomes.length === 0 && (
            <div className="mt-3 text-[13px] bg-violet-soft border border-violet/30 rounded-md p-3">
              <strong>Next step:</strong> connect your ad account or upload a results CSV on the{' '}
              <Link href="/data" className="text-violet underline font-semibold">Data page</Link>. The ledger fills
              itself from there.
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
