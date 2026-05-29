'use client';
import Link from 'next/link';
import clsx from 'clsx';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { useApp } from '@/lib/store';
import { analyzeVariants, type VariantMetrics } from '@/lib/compare';

const VERDICT_TONE: Record<string, 'success' | 'coral' | 'warning' | 'danger'> = {
  strong: 'success', positive: 'coral', break_even: 'warning', underperforming: 'danger',
};

// Matrix rows. `kind` controls formatting + which direction is "better".
type RowKind = 'roas' | 'pct' | 'frac' | 'ban' | 'viability' | 'econ';
const ROWS: { key: keyof VariantMetrics; label: string; kind: RowKind; hint?: string }[] = [
  { key: 'roas', label: 'ROAS (directional)', kind: 'roas', hint: 'model estimate — compare, don\'t bank on it' },
  { key: 'roiPct', label: 'Return on spend', kind: 'pct' },
  { key: 'ctrPct', label: 'Click-through', kind: 'pct' },
  { key: 'attention', label: 'Stopping power', kind: 'frac' },
  { key: 'emotional', label: 'Emotional pull', kind: 'frac' },
  { key: 'clarity', label: 'Visual clarity', kind: 'frac' },
  { key: 'relevance', label: 'Relevance of value prop', kind: 'frac' },
  { key: 'brandFit', label: 'Brand fit', kind: 'frac' },
  { key: 'coherence', label: 'Image–copy match', kind: 'frac' },
  { key: 'banLevel', label: 'Account-ban risk', kind: 'ban' },
  { key: 'forecastValid', label: 'Viability', kind: 'viability' },
  { key: 'economicsVerdict', label: 'Break-even maths', kind: 'econ' },
];

function bestValueForRow(metrics: VariantMetrics[], key: keyof VariantMetrics, kind: RowKind): number | null {
  if (!(kind === 'roas' || kind === 'pct' || kind === 'frac')) return null;
  const vals = metrics.map((m) => m[key]).filter((x): x is number => typeof x === 'number');
  return vals.length ? Math.max(...vals) : null;
}

function fmtCell(m: VariantMetrics, key: keyof VariantMetrics, kind: RowKind) {
  const v = m[key];
  switch (kind) {
    case 'roas': return typeof v === 'number' ? `${v.toFixed(2)}×` : '—';
    case 'pct': return typeof v === 'number' ? `${v >= 0 ? '' : ''}${v.toFixed(typeof v === 'number' && Math.abs(v) < 10 ? 2 : 0)}%` : '—';
    case 'frac': return typeof v === 'number' ? `${Math.round(v * 100)}%` : '—';
    case 'ban': return String(v ?? 'unknown');
    case 'viability': return m.runnable === false ? "won't run" : (m.forecastValid === false ? 'void' : 'runnable');
    case 'econ': return v ? String(v) : '—';
    default: return '—';
  }
}

export default function ComparePage() {
  const campaign = useApp((s) => s.currentCampaign);
  const variants = campaign?.variants;

  if (!campaign || !variants || variants.length < 2) {
    return (
      <div className="max-w-md mx-auto text-center py-24">
        <h2 className="display-italic text-3xl mb-3">Nothing to compare yet.</h2>
        <p className="text-ink-muted mb-5">
          Run a campaign with two or more creative variants, then come back here to see which wins and why.
        </p>
        <Link href="/new"><Button>Run a multi-variant test</Button></Link>
      </div>
    );
  }

  const { metrics, best, worst, bestReasons, worstReasons, allVoid } = analyzeVariants(variants);

  return (
    <>
      <div className="text-[12.5px] text-ink-muted mb-2">
        Dashboard · Campaigns · {campaign.name} · Compare
      </div>
      <div className="flex items-center gap-3 mb-5 flex-wrap">
        <div className="display-italic text-[32px] leading-[1.05]">
          Comparing <span className="gradient-text">{variants.length} variants</span>
        </div>
        <div className="flex-1" />
        <Link href="/result"><Button variant="secondary" size="sm">← Back to detail</Button></Link>
      </div>

      {/* HONEST FRAMING */}
      <Card className="mb-5 !bg-bg-deep !border-border">
        <div className="text-[13px] text-ink leading-snug">
          All variants ran against the <strong>same audience, budget and format</strong>, so this is a fair fight.
          The <strong>ranking</strong> below is the reliable part. The ROAS figures are a <strong>directional model estimate</strong> —
          read them as <em>relative</em> (A beats B), not as a promise of exact return. The break-even row is grounded in your real economics.
        </div>
      </Card>

      {/* BEST / WORST VERDICT */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <Card className={allVoid ? '!bg-warning-soft !border-warning/50' : '!bg-lime-soft !border-lime-deep/40'}>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-2xl">{allVoid ? '⚠' : '🏆'}</span>
            <div className="text-[11.5px] font-bold uppercase tracking-[0.12em] text-ink-muted">Strongest bet</div>
          </div>
          {best ? (
            <>
              <div className="display-italic text-[26px] leading-tight mb-1">
                Variant {best.label}
                <span className="text-[15px] font-sans not-italic text-ink-muted ml-2">{best.roas.toFixed(2)}× ROAS</span>
              </div>
              <div className="text-[13px] text-ink-muted mb-2 truncate">{best.headline || 'No headline'}</div>
              <ul className="space-y-1.5">
                {bestReasons.map((r, i) => (
                  <li key={i} className="text-[13.5px] text-ink flex gap-2"><span className="text-success">✓</span>{r}</li>
                ))}
              </ul>
            </>
          ) : (
            <div className="text-[14px] text-ink">Every variant is blocked or void — none is shippable as-is. Fix the issues flagged below before picking a winner.</div>
          )}
        </Card>

        <Card className="!bg-danger-soft !border-danger/40">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-2xl">⚠</span>
            <div className="text-[11.5px] font-bold uppercase tracking-[0.12em] text-ink-muted">Weakest / fix or drop</div>
          </div>
          {worst ? (
            <>
              <div className="display-italic text-[26px] leading-tight mb-1">
                Variant {worst.label}
                <span className="text-[15px] font-sans not-italic text-ink-muted ml-2">
                  {worst.runnable === false ? 'N/A' : `${worst.roas.toFixed(2)}× ROAS`}
                </span>
              </div>
              <div className="text-[13px] text-ink-muted mb-2 truncate">{worst.headline || 'No headline'}</div>
              <ul className="space-y-1.5">
                {worstReasons.map((r, i) => (
                  <li key={i} className="text-[13.5px] text-ink flex gap-2"><span className="text-danger">✕</span>{r}</li>
                ))}
              </ul>
            </>
          ) : (
            <div className="text-[14px] text-ink">Only one variant — nothing to rank against.</div>
          )}
        </Card>
      </div>

      {/* COMPARISON MATRIX */}
      <Card className="!p-0 overflow-hidden">
        <div className="px-6 py-4 bg-gradient-to-r from-coral-soft to-magenta-soft border-b border-coral/30">
          <div className="text-[11.5px] text-coral font-bold uppercase tracking-[0.1em]">Side-by-side</div>
          <div className="text-[14px] mt-0.5">Every driver, every variant. The best value in each row is highlighted.</div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[13.5px]">
            <thead className="bg-bg-deep text-[11.5px] text-ink-muted uppercase tracking-[0.06em] font-bold">
              <tr>
                <th className="text-left px-5 py-3 sticky left-0 bg-bg-deep">Metric</th>
                {metrics.map((m) => (
                  <th key={m.label} className="text-right px-4 py-3 min-w-[110px]">
                    <div className="flex items-center justify-end gap-2">
                      {m.thumbnailUrl ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={m.thumbnailUrl} alt="" className="w-6 h-6 rounded object-cover border border-border" />
                      ) : null}
                      Variant {m.label}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => {
                const bestVal = bestValueForRow(metrics, row.key, row.kind);
                return (
                  <tr key={row.label} className="border-b border-border-soft last:border-b-0">
                    <td className="text-left px-5 py-2.5 sticky left-0 bg-surface">
                      <div className="font-semibold text-ink">{row.label}</div>
                      {row.hint && <div className="text-[11px] text-ink-faint">{row.hint}</div>}
                    </td>
                    {metrics.map((m) => {
                      const raw = m[row.key];
                      const isBest = bestVal != null && typeof raw === 'number'
                        && Math.abs(raw - bestVal) < 1e-9 && metrics.length > 1;
                      const text = fmtCell(m, row.key, row.kind);
                      let tone = '';
                      if (row.kind === 'ban') tone = (raw === 'high' ? 'text-danger font-bold' : raw === 'medium' ? 'text-warning' : 'text-ink');
                      if (row.kind === 'viability') tone = (m.runnable === false || m.forecastValid === false) ? 'text-danger font-bold' : 'text-success';
                      if (row.kind === 'econ') tone = (raw === 'comfortable' ? 'text-success' : raw === 'shortfall' ? 'text-danger' : 'text-ink');
                      return (
                        <td key={m.label}
                            className={clsx('text-right px-4 py-2.5 font-mono',
                              isBest ? 'bg-lime-soft font-bold text-ink' : tone || 'text-ink')}>
                          {text}{isBest && <span className="ml-1 text-success">★</span>}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="text-[12px] text-ink-faint mt-3">
        ★ = best in row. Ranking by ROAS excludes any variant that won&apos;t run or whose forecast is void.
      </div>
    </>
  );
}
