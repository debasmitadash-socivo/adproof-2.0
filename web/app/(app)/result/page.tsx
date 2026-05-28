'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import clsx from 'clsx';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { PlotlyChart } from '@/components/Charts';
import { useApp } from '@/lib/store';
import { api } from '@/lib/api';
import type { PolicyCheckResponse, SavedCampaign, SavedVariantResult } from '@/lib/types';

const VERDICT_GRADIENT: Record<string, string> = {
  strong: 'from-success to-ink',
  positive: 'from-coral via-magenta to-violet',
  break_even: 'from-warning to-ink',
  underperforming: 'from-danger to-ink',
};
const VERDICT_GRADE: Record<string, string> = {
  strong: 'A', positive: 'B', break_even: 'C', underperforming: 'D',
};

const CHART_TABS = [
  { key: 'daily', label: 'Daily curve' },
  { key: 'roi', label: 'ROI distribution' },
  { key: 'factors', label: 'Click drivers' },
  { key: 'sens_budget', label: 'Sensitivity · budget' },
  { key: 'sens_reach', label: 'Sensitivity · reach' },
  { key: 'visual', label: 'Visual scores' },
];

export default function ResultPage() {
  const router = useRouter();
  const baseResult = useApp((s) => s.result);
  const campaign = useApp((s) => s.currentCampaign);
  const savedCampaigns = useApp((s) => s.savedCampaigns);
  const setResult = useApp((s) => s.setResult);
  const [tab, setTab] = useState('daily');
  const [activeVariantIdx, setActiveVariantIdx] = useState(0);

  // Multi-variant campaigns: leaderboard at top + detail below switches
  // depending on which variant tab is active. Single-variant campaigns just
  // show the one result.
  const hasVariants = !!campaign?.variants && campaign.variants.length > 1;
  const result = hasVariants && campaign?.variants
    ? campaign.variants[activeVariantIdx].result
    : baseResult;

  if (!result) {
    return (
      <div className="max-w-md mx-auto text-center py-24">
        <h2 className="display-italic text-3xl mb-3">No forecast yet.</h2>
        <p className="text-ink-muted mb-5">Run a simulation first.</p>
        <Link href="/new"><Button>Start a new analysis</Button></Link>
      </div>
    );
  }

  const mc = result.mc;
  const insights = result.insights;
  const verdictGradient = VERDICT_GRADIENT[insights.verdict_class] ?? VERDICT_GRADIENT.positive;
  const grade = VERDICT_GRADE[insights.verdict_class] ?? 'B';
  // The campaign currently shown is whichever one matches the result.
  // Show the rest as comparable.
  const comparables = savedCampaigns.filter((c) => c.result !== result).slice(0, 5);

  return (
    <>
      <div className="text-[12.5px] text-ink-muted mb-2">
        Dashboard · Campaigns · {result.company.company_name || 'Untitled'}
      </div>
      <div className="flex items-center gap-3 mb-6 no-print flex-wrap">
        <div className="display-italic text-[32px] leading-[1.05]">
          {result.company.company_name || 'Your campaign'} <span className="gradient-text">forecast</span>
        </div>
        <div className="flex-1" />
        <RerunButton campaign={campaign} />
        <Button variant="secondary" size="sm" onClick={() => duplicateToWizard(result, useApp.getState(), router)}>⎘ Duplicate</Button>
        <Button variant="secondary" size="sm" onClick={() => window.print()}>⇪ Export PDF</Button>
        <Link href="/new"><Button size="sm">Run another version</Button></Link>
      </div>

      {/* MULTI-VARIANT LEADERBOARD — only shows when the campaign has >1 variant */}
      {hasVariants && campaign?.variants && (
        <Card className="mb-6 !p-0 overflow-hidden">
          <div className="px-6 py-4 bg-gradient-to-r from-coral-soft to-magenta-soft border-b border-coral/30">
            <div className="text-[11.5px] text-coral font-bold uppercase tracking-[0.1em]">Variant leaderboard</div>
            <div className="text-[14px] mt-0.5">{campaign.variants.length} variants tested against the same audience &amp; budget — sorted by ROAS.</div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-bg-deep text-[11.5px] text-ink-muted uppercase tracking-[0.07em] font-bold">
                <tr>
                  <th className="text-left px-5 py-2.5">#</th>
                  <th className="text-left px-3 py-2.5">Variant</th>
                  <th className="text-left px-3 py-2.5">Headline</th>
                  <th className="text-right px-3 py-2.5">ROAS</th>
                  <th className="text-right px-3 py-2.5">ROI</th>
                  <th className="text-right px-3 py-2.5">CTR</th>
                  <th className="text-left px-3 py-2.5">Verdict</th>
                  <th className="px-3 py-2.5"></th>
                </tr>
              </thead>
              <tbody>
                {[...campaign.variants]
                  .map((v, originalIdx) => ({ v, originalIdx }))
                  .sort((a, b) => b.v.roasP50 - a.v.roasP50)
                  .map(({ v, originalIdx }, rank) => {
                    const winner = rank === 0;
                    const active = originalIdx === activeVariantIdx;
                    const tone = ({ strong: 'success', positive: 'coral', break_even: 'warning', underperforming: 'danger' } as const)[v.verdictClass];
                    return (
                      <tr key={v.label}
                          onClick={() => setActiveVariantIdx(originalIdx)}
                          className={clsx('cursor-pointer transition-colors border-b border-border-soft last:border-b-0',
                            active ? 'bg-coral-soft' : 'hover:bg-bg')}
                      >
                        <td className="px-5 py-3 text-[13.5px]">
                          {winner ? <span title="winner" className="text-coral text-[18px]">★</span> : <span className="text-ink-faint mono">{rank + 1}</span>}
                        </td>
                        <td className="px-3 py-3 text-[13.5px]">
                          <div className="flex items-center gap-2">
                            {v.thumbnailUrl ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img src={v.thumbnailUrl} alt="" className="w-8 h-8 rounded-md object-cover border border-border" />
                            ) : (
                              <div className="w-8 h-8 rounded-md bg-gradient-sunset" />
                            )}
                            <strong>{v.label}</strong>
                          </div>
                        </td>
                        <td className="px-3 py-3 text-[13px] text-ink max-w-[260px] truncate">{v.headline || <em className="text-ink-muted">No headline</em>}</td>
                        <td className="px-3 py-3 text-right font-mono text-[13.5px]"><strong>{v.roasP50.toFixed(2)}×</strong></td>
                        <td className="px-3 py-3 text-right font-mono text-[13px]">{(v.roiP50 * 100 >= 0 ? '+' : '') + Math.round(v.roiP50 * 100)}%</td>
                        <td className="px-3 py-3 text-right font-mono text-[13px]">{v.ctrPct.toFixed(2)}%</td>
                        <td className="px-3 py-3"><Pill tone={tone} dot>{v.verdictClass.replace('_', ' ')}</Pill></td>
                        <td className="px-3 py-3 text-right text-[12px] text-coral font-semibold">{active ? '— viewing' : 'view details →'}</td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
          <div className="px-5 py-3 bg-bg-deep text-[12.5px] text-ink-muted border-t border-border">
            Aggregate (mean across variants): <strong className="text-ink mono">{campaign.roasP50.toFixed(2)}× ROAS</strong> · <strong className="text-ink mono">{Math.round(campaign.roiP50 * 100) >= 0 ? '+' : ''}{Math.round(campaign.roiP50 * 100)}% ROI</strong>. The dashboard takes the <em>most pessimistic</em> verdict as the campaign-level verdict so you don't read one strong variant as a green light for the whole campaign.
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-7">
        <div>
          {/* DATA PROVENANCE BANNER — top-of-page honesty about what was measured vs guessed */}
          {result.visual && (
            <Card className={`mb-5 ${result.visual.is_heuristic ? '!bg-warning-soft !border-warning/40' : '!bg-lime-soft !border-lime-deep/30'}`}>
              <div className="flex items-start gap-3">
                <div className="text-2xl">{result.visual.is_heuristic ? '⚠' : '✨'}</div>
                <div className="flex-1">
                  <div className="font-heading font-bold text-[14.5px] mb-1">
                    {result.visual.is_heuristic
                      ? 'Heuristic mode — image not inspected'
                      : `Inspected with ${result.visual.provider} / ${result.visual.model}`}
                  </div>
                  <div className="text-[12.5px] text-ink leading-snug">
                    {result.visual.is_heuristic
                      ? <>The forecast below uses image colour/contrast statistics + copy keywords. Visual claims (the "visual quality" driver in particular) are based on pixel stats, NOT actual creative interpretation. Connect a Gemini key in <Link href="/settings" className="underline text-warning font-semibold">/settings</Link> for true multimodal analysis — that key persists across restarts now.</>
                      : <>Gemini examined your image, scored it against the rubric, and produced the description above. Visual / brand / coherence claims below are based on genuine semantic understanding of the file you uploaded.</>}
                  </div>
                  {result.visual.provider_error && (
                    <div className="text-[12px] text-warning bg-warning-soft/60 border border-warning/30 rounded-md px-2.5 py-1.5 mt-2 font-mono">
                      <strong>Why we fell back:</strong> {result.visual.provider_error}
                    </div>
                  )}
                </div>
              </div>
            </Card>
          )}

          {/* HERO */}
          <div className={clsx(
            'relative text-white rounded-md px-9 py-8 mb-5 flex items-center gap-8 overflow-hidden',
            `bg-gradient-to-br ${verdictGradient}`,
          )} style={{ boxShadow: '0 16px 40px rgba(16,163,74,0.20)' }}>
            <div className="absolute inset-0 mesh-overlay" />
            <div className="absolute -right-20 -top-24 w-80 h-80 rounded-full pointer-events-none" style={{ background: 'radial-gradient(circle, rgba(255,255,255,0.35), transparent 65%)' }} />
            <div className="relative z-10 flex-1">
              <div className="text-[11.5px] font-bold uppercase tracking-[0.14em] opacity-92">{insights.verdict_class.replace('_', ' ')} forecast</div>
              <div className="display-italic text-[96px] leading-none mt-1.5">
                {mc.predicted_roas.p50.toFixed(2)}× <span className="text-[28px] font-sans not-italic align-top opacity-90">ROAS</span>
              </div>
              <div className="text-[15px] mt-3 opacity-95 max-w-md">
                Median return <strong>{(mc.predicted_roi.p50 * 100).toFixed(0)}%</strong>. p10–p90 band <strong>{mc.predicted_roas.p10.toFixed(2)}× → {mc.predicted_roas.p90.toFixed(2)}×</strong>.
              </div>
              {insights.benchmark_note && (
                <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/22 backdrop-blur-md text-[13px] font-semibold mt-3.5">
                  {insights.benchmark_note}
                </div>
              )}
            </div>
            <div className="relative z-10">
              <div className="w-36 h-36 rounded-full bg-white/18 backdrop-blur-md flex flex-col items-center justify-center border-2 border-white/45">
                <div className="text-[10.5px] uppercase tracking-[0.16em] font-bold opacity-88">Verdict</div>
                <div className="display-italic text-[78px] leading-[0.85] mt-1">{grade}</div>
              </div>
            </div>
          </div>

          {/* CONTEXT */}
          <div className="flex flex-wrap gap-2.5 mb-5">
            <div className="bg-surface border border-border rounded-full px-4 py-1.5 text-[13px] flex items-center gap-2.5">
              <span className="text-[11px] text-ink-muted uppercase tracking-[0.06em] font-bold">Platform</span>
              {result.format.platform} · {result.format.name}
            </div>
            <div className="bg-surface border border-border rounded-full px-4 py-1.5 text-[13px] flex items-center gap-2.5">
              <span className="text-[11px] text-ink-muted uppercase tracking-[0.06em] font-bold">Audience</span>
              {result.match.segment} — {mc.audience_size} personas
            </div>
            <div className="bg-surface border border-border rounded-full px-4 py-1.5 text-[13px] flex items-center gap-2.5">
              <span className="text-[11px] text-ink-muted uppercase tracking-[0.06em] font-bold">Budget × days</span>
              ${mc.budget.toLocaleString()} over {mc.sim_days} days
            </div>
            <div className="bg-surface border border-border rounded-full px-4 py-1.5 text-[13px] flex items-center gap-2.5">
              <span className="text-[11px] text-ink-muted uppercase tracking-[0.06em] font-bold">Impressions</span>
              {(mc.total_impressions / 1_000_000).toFixed(2)}M
            </div>
          </div>

          {/* METRICS */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5 mb-5">
            {[
              { label: 'Predicted clicks', value: mc.predicted_clicks.p50.toLocaleString(undefined, { maximumFractionDigits: 0 }), range: `p10 ${mc.predicted_clicks.p10.toLocaleString(undefined, { maximumFractionDigits: 0 })} · p90 ${mc.predicted_clicks.p90.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, bar: 'bg-gradient-sunset' },
              { label: 'Conversions', value: mc.predicted_conversions.p50.toLocaleString(undefined, { maximumFractionDigits: 0 }), range: `p10 ${mc.predicted_conversions.p10.toLocaleString(undefined, { maximumFractionDigits: 0 })} · p90 ${mc.predicted_conversions.p90.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, bar: 'bg-gradient-to-b from-magenta to-violet' },
              { label: 'Revenue', value: `$${(mc.predicted_revenue.p50 / 1000).toFixed(1)}k`, range: `p10 $${(mc.predicted_revenue.p10 / 1000).toFixed(0)}k · p90 $${(mc.predicted_revenue.p90 / 1000).toFixed(0)}k`, bar: 'bg-gradient-fresh' },
              { label: 'Mean AOV', value: `$${mc.mean_aov.toFixed(0)}`, range: 'audience mean', bar: 'bg-gradient-to-b from-sky to-violet' },
            ].map((m) => (
              <Card key={m.label} className="!p-0 relative overflow-hidden">
                <div className={clsx('absolute left-0 top-0 bottom-0 w-1', m.bar)} />
                <div className="pl-5 pr-5 py-4">
                  <div className="text-[11.5px] text-ink-muted uppercase tracking-[0.08em] font-bold">{m.label}</div>
                  <div className="display-italic text-[32px] leading-none mt-1.5">{m.value}</div>
                  <div className="text-[12px] text-ink-muted mt-1.5 font-mono">{m.range}</div>
                </div>
              </Card>
            ))}
          </div>

          {/* CHARTS */}
          <div className="inline-flex bg-bg-deep p-1 rounded-xl mb-3">
            {CHART_TABS.map((t) => (
              <button key={t.key} onClick={() => setTab(t.key)} className={clsx(
                'px-3.5 py-2 rounded-lg text-[13px] font-medium transition-colors',
                tab === t.key ? 'bg-surface text-ink font-semibold shadow-soft' : 'text-ink-muted',
              )}>{t.label}</button>
            ))}
          </div>
          <Card>
            <PlotlyChart figure={(result.figures as any)[tab]} height={320} />
          </Card>

          {/* PLAIN-ENGLISH VERDICT */}
          {result.plain_verdict && (
          <Card className="!p-0 overflow-hidden border-2 !border-coral/30">
            <div className="px-6 py-5 bg-gradient-to-br from-coral-soft to-magenta-soft">
              <div className="text-[11.5px] text-coral font-bold uppercase tracking-[0.14em]">Plain English</div>
              <div className="display-italic text-[26px] mt-1 leading-tight">{result.plain_verdict.headline}</div>
              <div className="text-ink text-[14px] mt-2">
                For every <strong className="text-ink">$1 spent</strong>, you'll get back about{' '}
                <strong className="text-ink">${result.plain_verdict.roas_p50.toFixed(2)}</strong>{' '}
                — that's {result.plain_verdict.ctr_vs_bench_pct >= 0 ? '+' : ''}
                <strong className="text-ink">{Math.round(result.plain_verdict.ctr_vs_bench_pct)}%</strong>{' '}
                {result.plain_verdict.ctr_vs_bench_pct >= 0 ? 'above' : 'below'} the typical {result.format.name} CTR.
              </div>
            </div>
            <div className="px-6 py-4 grid grid-cols-1 sm:grid-cols-3 gap-3 text-[13.5px] bg-surface">
              <div>
                <div className="text-ink-muted text-[11.5px] uppercase tracking-[0.06em] font-bold">Chance of breaking even</div>
                <div className="display-italic text-[28px] mt-1 leading-none">{result.plain_verdict.break_even_chance_pct}%</div>
                <div className="text-[12px] text-ink-muted mt-1">of simulated runs hit ≥ $1 back per $1 spent</div>
              </div>
              <div>
                <div className="text-ink-muted text-[11.5px] uppercase tracking-[0.06em] font-bold">Expected return</div>
                <div className="display-italic text-[28px] mt-1 leading-none">{result.plain_verdict.roi_p50_pct >= 0 ? '+' : ''}{result.plain_verdict.roi_p50_pct}%</div>
                <div className="text-[12px] text-ink-muted mt-1">on your ${mc.budget.toLocaleString()} spend</div>
              </div>
              <div>
                <div className="text-ink-muted text-[11.5px] uppercase tracking-[0.06em] font-bold">vs benchmark CTR</div>
                <div className="display-italic text-[28px] mt-1 leading-none">{result.plain_verdict.ctr_vs_bench_pct >= 0 ? '+' : ''}{result.plain_verdict.ctr_vs_bench_pct}%</div>
                <div className="text-[12px] text-ink-muted mt-1">{result.format.name} industry mid-range</div>
              </div>
            </div>
          </Card>
          )}

          {/* CHANNEL ECONOMICS — the honest break-even math on the user's real
              numbers. Shown alongside the ROAS estimate, not instead of it. */}
          {result.economics && (() => {
            const e = result.economics!;
            const cur = e.currency || 'GBP';
            const tone = e.verdict === 'comfortable' ? 'success'
              : e.verdict === 'marginal' ? 'warning' : 'danger';
            const bg = e.verdict === 'comfortable' ? '!bg-lime-soft !border-lime-deep/30'
              : e.verdict === 'marginal' ? '!bg-warning-soft !border-warning/40'
              : '!bg-danger-soft !border-danger/40';
            const pct = (x: number | null | undefined) =>
              x == null ? '—' : `${(x * 100).toFixed(x < 0.001 ? 4 : 2)}%`;
            const verdictLine = e.verdict === 'comfortable'
              ? 'The maths works with room to spare.'
              : e.verdict === 'marginal'
                ? 'The maths is tight — break-even is plausible but not guaranteed.'
                : e.verdict === 'shortfall'
                  ? 'The maths falls short — the modelled CTR is below what you need to break even.'
                  : 'Not enough economics to judge.';
            return (
              <>
                <h2 className="display-italic text-[28px] mt-7 mb-2">Will the maths work?</h2>
                <p className="text-ink-muted text-[14px] mb-3">
                  The break-even math on <strong>your</strong> economics — not a synthetic guess. This is the number to trust more than the ROAS estimate above.
                </p>
                <Card className={bg}>
                  <div className="flex items-center gap-3 flex-wrap mb-3">
                    <Pill tone={tone as any} dot>{e.verdict}</Pill>
                    <span className="text-[14.5px] font-semibold text-ink">{verdictLine}</span>
                    <span className="ml-auto text-[12px] text-ink-muted">market: {e.geo}</span>
                  </div>
                  <div className="text-[14px] text-ink leading-relaxed mb-4">
                    At your <strong>{cur} {e.avg_order_value.toLocaleString()}</strong> order value
                    {' '}({e.avg_order_value_source}) and <strong>{(e.conversion_rate * 100).toFixed(1)}%</strong> conversion,
                    you need a <strong>{pct(e.break_even_ctr)}</strong> click-through rate to break even.
                    We model your creative at <strong>{pct(e.modelled_ctr)}</strong>
                    {' '}(benchmark {pct(e.benchmark_ctr)}).
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {[
                      { label: 'Break-even CTR', value: pct(e.break_even_ctr), sub: 'what you need' },
                      { label: 'Modelled CTR', value: pct(e.modelled_ctr), sub: 'what we expect' },
                      { label: 'Headroom', value: e.headroom_x != null ? `${e.headroom_x}×` : '—', sub: e.headroom_x != null && e.headroom_x >= 1 ? 'above break-even' : 'below break-even' },
                      { label: 'Order value', value: `${cur} ${e.avg_order_value.toLocaleString()}`, sub: e.avg_order_value_source },
                    ].map((m) => (
                      <div key={m.label} className="bg-surface border border-border rounded-md px-3.5 py-3">
                        <div className="text-[11px] text-ink-muted uppercase tracking-[0.06em] font-bold">{m.label}</div>
                        <div className="display-italic text-[24px] leading-none mt-1">{m.value}</div>
                        <div className="text-[11.5px] text-ink-muted mt-1">{m.sub}</div>
                      </div>
                    ))}
                  </div>
                  {e.avg_order_value_source !== 'your figure' && (
                    <div className="mt-3 text-[12.5px] text-yellow-800">
                      ⚠ This used an <strong>estimated</strong> order value. Set your real figure on the <Link href="/company" className="underline">company profile</Link> for accurate break-even maths.
                    </div>
                  )}
                </Card>
              </>
            );
          })()}

          {/* MARKET & TIMING — grounded culture / seasonality / recent events */}
          {campaign?.marketContext?.context && (() => {
            const mc2 = campaign.marketContext!;
            const c = mc2.context;
            const hasAny = (c.cultural_notes?.length || c.recent_events?.length || c.seasonality?.current_window || c.overall);
            if (!hasAny) return null;
            return (
              <>
                <h2 className="display-italic text-[28px] mt-7 mb-2">Market &amp; timing · {mc2.geo}</h2>
                <p className="text-ink-muted text-[14px] mb-3">
                  Live cultural, seasonal &amp; recent-events read for <strong>{mc2.geo}</strong> as of {mc2.as_of} — grounded on the web, not the synthetic model. This is what a local strategist would tell you.
                </p>
                <Card className="!bg-violet-soft !border-violet/30">
                  {c.overall && <div className="text-[14.5px] text-ink leading-relaxed mb-4 italic">&ldquo;{c.overall}&rdquo;</div>}

                  {c.cultural_notes && c.cultural_notes.length > 0 && (
                    <div className="mb-4">
                      <div className="text-[11.5px] text-violet font-bold uppercase tracking-[0.08em] mb-1.5">Cultural fit · {mc2.geo}</div>
                      <ul className="space-y-1">
                        {c.cultural_notes.map((n, i) => (
                          <li key={i} className="text-[13.5px] text-ink flex gap-2"><span className="text-violet">•</span>{n}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {c.seasonality?.current_window && (
                    <div className="mb-4">
                      <div className="text-[11.5px] text-violet font-bold uppercase tracking-[0.08em] mb-1.5">Seasonality</div>
                      <div className="text-[13.5px] text-ink">
                        <strong>{c.seasonality.current_window}</strong>{c.seasonality.advice ? ` — ${c.seasonality.advice}` : ''}
                      </div>
                    </div>
                  )}

                  {c.recent_events && c.recent_events.length > 0 && (
                    <div>
                      <div className="text-[11.5px] text-violet font-bold uppercase tracking-[0.08em] mb-1.5">Recent events to {''}
                        <span className="text-success">leverage</span> / <span className="text-danger">avoid</span></div>
                      <ul className="space-y-1.5">
                        {c.recent_events.map((e, i) => (
                          <li key={i} className="text-[13.5px] text-ink flex gap-2 items-start">
                            <Pill tone={e.use_as === 'leverage' ? 'success' : 'danger'}>{e.use_as}</Pill>
                            <span><strong>{e.event}</strong>{e.note ? ` — ${e.note}` : ''}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {mc2.sources && mc2.sources.length > 0 && (
                    <div className="text-[11.5px] text-ink-muted mt-3 pt-3 border-t border-violet/20">
                      Sources: {mc2.sources.map((s, i) => (
                        <span key={i}>{i > 0 ? ' · ' : ''}<a className="underline" href={s.uri} target="_blank" rel="noreferrer">{s.title || 'link'}</a></span>
                      ))}
                    </div>
                  )}
                </Card>
              </>
            );
          })()}

          {/* DRIVERS — plain English with bars, no logit */}
          {result.factor_plain && result.factor_plain.length > 0 && (<>
          <h2 className="display-italic text-[28px] mt-7 mb-2">What's driving this</h2>
          <p className="text-ink-muted text-[14px] mb-3">Each factor's share of the predicted impact. Green pushes performance up, red drags it down.</p>
          {result.visual?.is_heuristic && (
            <Card className="!bg-warning-soft !border-warning/30 mb-3 !py-3 !px-4">
              <div className="text-[12.5px] text-ink leading-snug">
                <strong>Visual driver is heuristic.</strong> The "visual" bar below comes from image colour/contrast statistics, NOT actual creative interpretation. Treat it as a placeholder, not a claim about creative quality. Connect a Gemini key for a real visual score.
              </div>
            </Card>
          )}
          <Card>
            <ul className="space-y-3">
              {result.factor_plain.map((f) => {
                const pct = Math.round(f.share * 100);
                const positive = f.direction === '+';
                const isHeuristicVisual = f.name === 'visual' && result.visual?.is_heuristic;
                const displayLabel = isHeuristicVisual
                  ? 'Visual (heuristic — pixel stats only)'
                  : f.label;
                return (
                  <li key={f.name} className={isHeuristicVisual ? 'opacity-70' : ''}>
                    <div className="flex justify-between text-[13.5px] mb-1.5">
                      <span>
                        <strong>{displayLabel}</strong>
                        {isHeuristicVisual && <span className="ml-2 text-[11.5px] text-warning font-semibold">⚠ unverified</span>}
                      </span>
                      <span className={positive ? 'text-success font-mono font-semibold' : 'text-danger font-mono font-semibold'}>
                        {positive ? '+' : '−'}{pct}%
                      </span>
                    </div>
                    <div className="h-2 bg-border-soft rounded-full overflow-hidden">
                      <div
                        className={
                          isHeuristicVisual ? 'h-full bg-border'
                          : positive ? 'h-full bg-gradient-fresh' : 'h-full bg-danger'
                        }
                        style={{ width: `${Math.max(pct, 4)}%` }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          </Card>
          </>)}

          {/* IMAGE READ — proof the LLM actually looked at the upload */}
          {result.visual && result.visual.image_description && !result.visual.is_heuristic && (
            <>
              <h2 className="display-italic text-[28px] mt-7 mb-2">What the AI saw in your image</h2>
              <Card className="!bg-violet-soft !border-violet/30">
                <div className="text-[13px] text-violet mb-1 font-bold uppercase tracking-[0.08em]">{result.visual.provider} · {result.visual.model}</div>
                <div className="text-[14.5px] text-ink leading-relaxed italic">&ldquo;{result.visual.image_description}&rdquo;</div>
                <div className="text-[12px] text-ink-muted mt-2">If this description doesn't match what you uploaded, your image didn't reach the model — re-upload and re-run.</div>
              </Card>
            </>
          )}

          {/* IMAGE ↔ COPY COHERENCE — separate from brand fit */}
          {result.visual && result.visual.image_copy_coherence !== undefined && (
            <>
              <h2 className="display-italic text-[28px] mt-7 mb-2">Does the image match the copy?</h2>
              <Card className={
                (result.visual.image_copy_coherence ?? 0) >= 0.65 ? '!bg-lime-soft !border-lime-deep/30'
                : (result.visual.image_copy_coherence ?? 0) >= 0.45 ? '!bg-warning-soft !border-warning/30'
                : '!bg-danger-soft !border-danger/30'}>
                <div className="flex items-start gap-4">
                  <div className="text-center">
                    <div className="display-italic text-[44px] leading-none">{Math.round((result.visual.image_copy_coherence ?? 0) * 100)}<span className="text-[20px]">%</span></div>
                    <div className="text-[11.5px] text-ink-muted font-bold uppercase tracking-[0.08em] mt-1">coherence</div>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1.5">
                      <Pill tone={result.visual.is_heuristic ? 'warning' : 'success'}>
                        {result.visual.is_heuristic ? '⚠ heuristic — cannot check coherence without LLM' : '✨ LLM image-↔-copy check'}
                      </Pill>
                    </div>
                    <div className="text-[14px] leading-relaxed text-ink">
                      {result.visual.image_copy_coherence_explanation || 'Coherence signal not available.'}
                    </div>
                  </div>
                </div>
              </Card>
            </>
          )}

          {/* ACCOUNT-BAN RISK — could the image get the ad account suspended? */}
          {result.visual?.ban_risk && result.visual.ban_risk.level !== 'unknown' && (
            <>
              <h2 className="display-italic text-[28px] mt-7 mb-2">Could this get your account banned?</h2>
              <Card className={
                result.visual.ban_risk.level === 'high' ? '!bg-danger-soft !border-danger/40'
                : result.visual.ban_risk.level === 'medium' ? '!bg-warning-soft !border-warning/40'
                : result.visual.ban_risk.level === 'low' ? '!bg-warning-soft/50 !border-warning/30'
                : '!bg-lime-soft !border-lime-deep/30'}>
                <div className="flex items-center gap-2.5 mb-2 flex-wrap">
                  <Pill tone={result.visual.ban_risk.level === 'high' ? 'danger'
                    : result.visual.ban_risk.level === 'medium' || result.visual.ban_risk.level === 'low' ? 'warning'
                    : 'success'} dot>
                    Ban risk: {result.visual.ban_risk.level}
                  </Pill>
                  <span className="text-[12px] text-ink-muted">image screened for nudity / shocking / prohibited content</span>
                </div>
                <div className="text-[14px] text-ink leading-relaxed">{result.visual.ban_risk.explanation}</div>
                {result.visual.ban_risk.flags.length > 0 && (
                  <ul className="mt-2.5 space-y-1">
                    {result.visual.ban_risk.flags.map((f, i) => (
                      <li key={i} className="text-[13.5px] text-danger flex gap-2"><span>⚠</span>{f}</li>
                    ))}
                  </ul>
                )}
              </Card>
            </>
          )}

          {/* BRAND RELEVANCE CHECK — does the image fit the brand? */}
          {result.visual && result.visual.brand_relevance !== undefined && (
            <>
              <h2 className="display-italic text-[28px] mt-7 mb-2">Does the image fit your brand?</h2>
              <Card className={result.visual.brand_relevance >= 0.65
                ? '!bg-lime-soft !border-lime-deep/30'
                : result.visual.brand_relevance >= 0.45
                  ? '!bg-warning-soft !border-warning/30'
                  : '!bg-danger-soft !border-danger/30'}>
                <div className="flex items-start gap-4">
                  <div className="text-center">
                    <div className="display-italic text-[44px] leading-none">{Math.round((result.visual.brand_relevance ?? 0) * 100)}<span className="text-[20px]">%</span></div>
                    <div className="text-[11.5px] text-ink-muted font-bold uppercase tracking-[0.08em] mt-1">brand fit</div>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1.5">
                      <Pill tone={result.visual.brand_relevance_source === 'llm' ? 'success' : 'warning'}>
                        {result.visual.brand_relevance_source === 'llm' ? '✨ LLM check' : '⚠ heuristic only — image not inspected'}
                      </Pill>
                    </div>
                    <div className="text-[14px] leading-relaxed text-ink">
                      {result.visual.brand_relevance_explanation || 'Brand-relevance signal not available.'}
                    </div>
                  </div>
                </div>
              </Card>
            </>
          )}

          {/* POLICY COMPLIANCE — live Gemini web grounding against current platform docs */}
          <PolicyCheckSection result={result} />


          {/* COPY CRITIQUE — specific, actionable fixes */}
          {result.copy_critique && result.copy_critique.length > 0 && (
            <>
              <h2 className="display-italic text-[28px] mt-7 mb-2">Copy fixes</h2>
              <p className="text-ink-muted text-[14px] mb-3">Specific things to change in your copy, with the suggested replacement.</p>
              <div className="space-y-2.5">
                {result.copy_critique.map((c, i) => {
                  const tone = c.severity === 'error' ? 'danger' : c.severity === 'warning' ? 'warning' : 'coral';
                  const accent = c.severity === 'error' ? 'border-danger/40 !bg-danger-soft'
                                : c.severity === 'warning' ? 'border-warning/40 !bg-warning-soft'
                                : 'border-coral/30 !bg-coral-soft';
                  return (
                    <Card key={i} className={`!p-4 ${accent}`}>
                      <div className="flex items-start gap-3">
                        <Pill tone={tone as any}>{c.field.replace('_', ' ')}</Pill>
                        <div className="flex-1">
                          <div className="text-[14px] font-semibold text-ink">{c.message}</div>
                          <div className="text-[13.5px] text-ink mt-1.5"><strong className="text-coral">Fix:</strong> {c.fix}</div>
                          {c.lift_pct !== undefined && c.lift_pct !== null && (
                            <div className="text-[12px] mt-2 inline-block px-2 py-0.5 rounded-full bg-surface text-success font-semibold">~+{c.lift_pct}% CTR lift if fixed (directional)</div>
                          )}
                        </div>
                      </div>
                    </Card>
                  );
                })}
              </div>
            </>
          )}

          {/* RECOMMENDATIONS */}
          <h2 className="display-italic text-[28px] mt-7 mb-2">What to try next</h2>
          <ul className="space-y-2">
            {insights.recommendations.map((b, i) => (
              <li key={i} className="bg-surface border border-border rounded-lg pl-10 pr-3.5 py-3 text-[14px] relative">
                <span className="absolute left-3.5 top-3 text-coral font-bold">→</span>
                <span dangerouslySetInnerHTML={{ __html: b.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/_(.+?)_/g, '<em>$1</em>') }} />
              </li>
            ))}
          </ul>

          {/* DATA & CONFIDENCE — the brutally honest panel */}
          {result.confidence && result.data_sources && (<>
          <h2 className="display-italic text-[28px] mt-8 mb-2">How accurate is this?</h2>
          <Card className={
            result.confidence.level === 'low'
              ? '!bg-warning-soft !border-warning/40'
              : result.confidence.level === 'low_medium'
                ? '!bg-coral-soft !border-coral/30'
                : '!bg-lime-soft !border-lime-deep/30'
          }>
            <div className="flex items-center gap-3 mb-3">
              <Pill tone={result.confidence.level === 'low' ? 'warning' : result.confidence.level === 'low_medium' ? 'coral' : 'success'} dot>
                Confidence: {result.confidence.level.replace('_', ' ')}
              </Pill>
              <span className="text-[13px] text-ink">{result.confidence.blurb}</span>
            </div>
            <div className="text-[11.5px] text-ink-muted font-bold uppercase tracking-[0.08em] mt-4 mb-2">What's powering this forecast</div>
            <div className="space-y-2">
              {result.data_sources.map((s) => (
                <div key={s.label} className="bg-surface border border-border rounded-md px-3.5 py-2.5 text-[13px]">
                  <div className="flex items-center justify-between mb-0.5">
                    <strong>{s.label}</strong>
                    <span className="font-mono text-[12px] text-ink-muted">{s.value}</span>
                  </div>
                  <div className="text-ink-muted text-[12.5px]">{s.note}</div>
                </div>
              ))}
            </div>
            <div className="mt-4 text-[12.5px] text-ink-muted leading-relaxed">
              <strong>To improve accuracy:</strong> connect an Anthropic / OpenAI API key (LLM company &amp; audience parsing + multimodal visual analysis), and in v1.1 upload your past campaign performance so the model calibrates on <em>your</em> brand, not synthetic data.
            </div>
          </Card>
          </>)}
        </div>

        {/* RIGHT RAIL */}
        <aside className="bg-surface border border-border rounded-md p-5 sticky top-6 self-start shadow-soft">
          <div className="font-heading font-bold text-[15px] mb-4">Edit &amp; re-run</div>
          <div className="space-y-3">
            <div><label className="label">Budget (USD)</label><input className="input" defaultValue={mc.budget} /></div>
            <div><label className="label">Campaign days</label><input className="input" defaultValue={mc.sim_days} /></div>
            <div><label className="label">Daily reach</label><input className="input" defaultValue="35%" /></div>
            <div><label className="label">Platform · Format</label>
              <select className="input"><option>{result.format.platform} · {result.format.name}</option></select>
            </div>
            <div><label className="label">Audience</label>
              <select className="input"><option>{result.match.segment}</option></select>
            </div>
          </div>
          <Link href="/new"><Button className="w-full mt-3.5">Re-run simulation</Button></Link>

          <hr className="my-5 border-border" />

          <div className="font-heading font-bold text-[15px] mb-3">Compare with</div>
          {comparables.length === 0 ? (
            <div className="text-ink-muted text-[13px]">No other analyses saved yet. Run a second creative to enable comparison.</div>
          ) : (
            comparables.map((c) => (
              <Button
                key={c.id} variant="secondary" size="sm" className="w-full justify-start mb-1.5"
                onClick={() => { setResult(c.result); router.refresh(); }}
              >
                📊 {c.name} — {c.roasP50.toFixed(2)}×
              </Button>
            ))
          )}
          <Link href="/new"><Button variant="ghost" size="sm" className="w-full justify-start mt-2">+ Upload new creative</Button></Link>
        </aside>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Re-run — replays the saved simulate request(s) against the current backend
// so improvements to the app (new LLM, fresher benchmarks, bug fixes) are
// reflected on the same inputs. Saved as a new linked campaign.
// ---------------------------------------------------------------------------

function RerunButton({ campaign }: { campaign: SavedCampaign | null }) {
  const router = useRouter();
  const addCampaign = useApp((s) => s.addCampaign);
  const setResult = useApp((s) => s.setResult);
  const setCurrentCampaign = useApp((s) => s.setCurrentCampaign);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!campaign?.originalRequests || campaign.originalRequests.length === 0) {
    // Campaign saved before the re-run feature shipped — gracefully disable.
    return (
      <Button variant="secondary" size="sm" disabled title="Older campaigns don't have the saved inputs to re-run. Re-runnable from the next campaign you create.">
        ↺ Re-run (n/a)
      </Button>
    );
  }

  async function rerun() {
    if (!campaign?.originalRequests) return;
    setRunning(true); setErr(null);
    try {
      const results = await Promise.all(
        campaign.originalRequests.map((req) => api.simulate(req)),
      );
      const firstResult = results[0];
      const savedVariants: SavedVariantResult[] = results.map((r, i) => ({
        label: campaign.variants?.[i]?.label ?? (i === 0 ? 'A' : String.fromCharCode(65 + i)),
        headline: campaign.originalRequests![i].headline || `Variant ${i + 1}`,
        thumbnailUrl: campaign.variants?.[i]?.thumbnailUrl ?? null,
        result: r,
        roasP50: r.mc.predicted_roas.p50,
        roiP50: r.mc.predicted_roi.p50,
        ctrPct: (r.mc.sample_ctrs.reduce((a, b) => a + b, 0) / Math.max(r.mc.sample_ctrs.length, 1)) * 100,
        verdictClass: r.insights.verdict_class,
      }));
      const avgRoas = savedVariants.reduce((s, v) => s + v.roasP50, 0) / savedVariants.length;
      const avgRoi = savedVariants.reduce((s, v) => s + v.roiP50, 0) / savedVariants.length;
      const avgCtr = savedVariants.reduce((s, v) => s + v.ctrPct, 0) / savedVariants.length;
      const worstVerdict = (
        savedVariants.some((v) => v.verdictClass === 'underperforming') ? 'underperforming'
        : savedVariants.some((v) => v.verdictClass === 'break_even') ? 'break_even'
        : savedVariants.some((v) => v.verdictClass === 'positive') ? 'positive'
        : 'strong'
      ) as SavedCampaign['verdictClass'];

      const newCampaign: SavedCampaign = {
        ...campaign,
        id: `c_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        name: campaign.name.replace(/ \(re-run.*\)$/, '') + ` (re-run ${new Date().toLocaleDateString()})`,
        createdAt: Date.now(),
        result: firstResult,
        variants: savedVariants.length > 1 ? savedVariants : undefined,
        roasP50: avgRoas, roiP50: avgRoi, ctrPct: avgCtr,
        verdictClass: worstVerdict,
        rerunOfId: campaign.id,
      };
      addCampaign(newCampaign);
      setResult(firstResult);
      setCurrentCampaign(newCampaign);
      router.refresh();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <Button
        variant="secondary" size="sm"
        onClick={rerun}
        disabled={running}
        title="Replay this campaign's inputs against the current backend — picks up the latest LLM, benchmarks, scoring fixes. Saved as a new campaign."
      >
        {running ? '↺ Re-running…' : '↺ Re-run with latest engine'}
      </Button>
      {err && <span className="text-[12px] text-danger ml-2">{err}</span>}
    </>
  );
}

// ---------------------------------------------------------------------------
// Duplicate — copy this campaign's settings into the wizard store + go to /new
// ---------------------------------------------------------------------------

function duplicateToWizard(result: any, store: any, router: any) {
  store.setObjective?.(result.brief.objective ?? 'consideration');
  store.setPlatform?.(result.brief.platform_id);
  store.setFormat?.(result.brief.format_id);
  store.setBudget?.(result.brief.budget);
  store.setDays?.(result.brief.days);
  store.setDailyReach?.(result.brief.daily_reach);
  store.setNRuns?.(result.brief.n_runs);
  // Carry forward the creative copy. Image/video paths intentionally NOT
  // copied — the user should re-upload (or pick a new variant).
  if (result.ad?.text) {
    store.setCreativeField?.('headline', result.ad.text.split('\n')[0] || '');
    store.setCreativeField?.('primaryText', result.ad.text);
  }
  store.setResult?.(null);                 // clear previous forecast
  store.setStep?.(4);                       // jump to Creative — user re-uploads
  router.push('/new');
}

// ---------------------------------------------------------------------------
// Policy compliance — Gemini fetches the current platform ad policy via web
// grounding and evaluates the copy against it.
// ---------------------------------------------------------------------------

function PolicyCheckSection({ result }: { result: any }) {
  const [checking, setChecking] = useState(false);
  const [data, setData] = useState<PolicyCheckResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setChecking(true); setErr(null); setData(null);
    try {
      const r = await api.policyCheck({
        platform_id: result.brief.platform_id,
        format_id: result.brief.format_id,
        headline: result.ad?.text || '',
        primary_text: result.ad?.text || '',
        cta: '',
        link: '',
        industry: result.company?.industry,
        geo: result.brief?.geo || result.economics?.geo || 'UK',
      });
      setData(r);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setChecking(false);
    }
  }

  const riskTone = data?.overall_risk === 'high' ? 'danger'
    : data?.overall_risk === 'medium' ? 'warning'
    : data?.overall_risk === 'low' ? 'success' : 'muted';

  return (
    <>
      <h2 className="display-italic text-[28px] mt-7 mb-2">Policy &amp; compliance check</h2>
      {!data && (
        <Card>
          <div className="text-[14px] mb-3">
            Run a live check of your copy against <strong>{result.format.platform}</strong>'s current advertising rules — Gemini fetches the policy doc from the web at request time and flags violations with source URLs.
          </div>
          <div className="text-[12.5px] text-ink-muted mb-4">
            Catches: restricted content (health / financial / alcohol claims), required disclaimers (supplements, gambling), targeting restrictions (housing / employment / credit), and trademark issues.
          </div>
          <Button onClick={run} disabled={checking}>
            {checking ? '🌐 Reading live policy docs…' : `🌐 Check against ${result.format.platform} policy (live)`}
          </Button>
          {err && <div className="mt-3 text-[12.5px] text-danger bg-danger-soft border border-danger/30 rounded-md p-2.5">{err}</div>}
          <div className="text-[11.5px] text-ink-muted mt-3">Needs your Gemini key in /settings.</div>
        </Card>
      )}

      {data && (
        <>
          <Card className={
            data.overall_risk === 'high' ? '!bg-danger-soft !border-danger/40'
            : data.overall_risk === 'medium' ? '!bg-warning-soft !border-warning/40'
            : '!bg-lime-soft !border-lime-deep/30'
          }>
            <div className="flex items-center gap-3 flex-wrap mb-2">
              <Pill tone={riskTone as any} dot>Risk: {data.overall_risk}</Pill>
              <Pill tone="muted">{data.issues.length} issue{data.issues.length === 1 ? '' : 's'}</Pill>
              {data.jurisdiction && <Pill tone="violet">⚖ {data.jurisdiction} law + platform</Pill>}
              <Pill tone="muted">checked against {data.policies_consulted_year} policy</Pill>
              <div className="flex-1" />
              <Button size="sm" variant="ghost" onClick={run} disabled={checking}>
                {checking ? '…' : '↻ Re-check'}
              </Button>
            </div>
            <div className="text-[14px] text-ink">{data.summary}</div>
            {data.regulator && (
              <div className="text-[12px] text-ink-muted mt-1.5">Regulator(s): {data.regulator}</div>
            )}
            {data.policy_source_url && (
              <div className="text-[12px] mt-2">
                Source: <a href={data.policy_source_url} target="_blank" rel="noreferrer" className="underline">{data.policy_source_url}</a>
              </div>
            )}
          </Card>

          {data.issues.length > 0 && (
            <div className="space-y-2.5 mt-3">
              {data.issues.map((iss, i) => (
                <Card key={i} className={
                  iss.severity === 'error' ? '!bg-danger-soft !border-danger/40'
                  : iss.severity === 'warning' ? '!bg-warning-soft !border-warning/40'
                  : '!bg-surface !border-border'}>
                  <div className="flex items-center gap-2 mb-2">
                    <Pill tone={iss.severity === 'error' ? 'danger' : iss.severity === 'warning' ? 'warning' : 'muted'}>
                      {iss.severity}
                    </Pill>
                    <strong className="text-[14px]">{iss.rule}</strong>
                  </div>
                  {iss.violating_text && (
                    <div className="text-[13px] mb-2">
                      <span className="text-ink-muted">Triggered by:</span> <span className="bg-surface px-1.5 rounded font-mono text-[12.5px]">&ldquo;{iss.violating_text}&rdquo;</span>
                    </div>
                  )}
                  <div className="text-[13.5px] mb-2">{iss.explanation}</div>
                  <div className="text-[13.5px]"><strong className="text-coral">Fix:</strong> {iss.fix}</div>
                  {iss.rule_url && (
                    <div className="text-[11.5px] mt-2"><a href={iss.rule_url} target="_blank" rel="noreferrer" className="underline text-ink-muted">read the rule →</a></div>
                  )}
                </Card>
              ))}
            </div>
          )}

          {data.grounding_sources.length > 0 && (
            <div className="text-[11.5px] text-ink-muted mt-3">
              Sources Gemini consulted:{' '}
              {data.grounding_sources.map((s, i) => (
                <span key={i}>{i > 0 ? ' · ' : ''}<a href={s.uri} target="_blank" rel="noreferrer" className="underline">{s.title || s.uri.slice(0, 40)}</a></span>
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}
