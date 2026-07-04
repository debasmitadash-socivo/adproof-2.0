'use client';
// The Ad Library — every real ad synced/uploaded into this workspace,
// browsable like Ads Manager: search, platform + date filters, sortable
// columns, summary analytics, and top/bottom performer callouts. Daily rows
// are pooled per ad (same pooling the accuracy ledger uses, so numbers
// always agree across pages).
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { useApp } from '@/lib/store';
import { listOutcomes } from '@/lib/db';
import type { OutcomeRow } from '@/lib/db';
import { poolOutcomes } from '@/lib/accuracy';
import type { PooledOutcome, PoolLevel } from '@/lib/accuracy';

const PLATFORM_LABEL: Record<string, string> = {
  meta_facebook: 'Facebook', meta_instagram: 'Instagram', linkedin: 'LinkedIn',
  tiktok: 'TikTok', youtube: 'YouTube', google_search: 'Google Search',
  reddit: 'Reddit', x_twitter: 'X (Twitter)', multi: 'FB + IG',
};

type SortKey = 'spend' | 'impressions' | 'clicks' | 'ctr' | 'cpm' | 'roas' | 'name' | 'date' | 'frequency' | 'cvr' | 'cpa';

const cpmOf = (a: PooledOutcome) => (a.impressions > 0 ? (a.spend / a.impressions) * 1000 : 0);
const cpcOf = (a: PooledOutcome) => (a.clicks > 0 ? a.spend / a.clicks : null);
const cvrOf = (a: PooledOutcome) => (a.conversions != null && a.clicks > 0 ? a.conversions / a.clicks : null);
const cpaOf = (a: PooledOutcome) => (a.conversions != null && a.conversions > 0 ? a.spend / a.conversions : null);

function sortVal(a: PooledOutcome, k: SortKey): number | string {
  switch (k) {
    case 'spend': return a.spend;
    case 'impressions': return a.impressions;
    case 'clicks': return a.clicks;
    case 'ctr': return a.realCtr ?? -1;
    case 'cpm': return cpmOf(a);
    case 'roas': return a.realRoas ?? -1;
    case 'name': return a.adName.toLowerCase();
    case 'date': return a.firstDate ?? '';
    case 'frequency': return a.frequency ?? -1;
    case 'cvr': return cvrOf(a) ?? -1;
    case 'cpa': return cpaOf(a) ?? Number.MAX_SAFE_INTEGER;
  }
}

export default function AdLibraryPage() {
  const currentCompanyId = useApp((s) => s.currentCompanyId);
  const profile = useApp((s) => s.companyProfile);
  const cur = profile?.currency || 'GBP';

  const [rows, setRows] = useState<OutcomeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [platform, setPlatform] = useState<string>('all');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('spend');
  const [sortDesc, setSortDesc] = useState(true);
  const [shown, setShown] = useState(50);
  const [level, setLevel] = useState<PoolLevel>('ad');

  useEffect(() => {
    let alive = true;
    setLoading(true);
    listOutcomes(currentCompanyId ?? undefined)
      .then((r) => { if (alive) { setRows(r); setLoading(false); } })
      .catch(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [currentCompanyId]);

  const pooled = useMemo(() => poolOutcomes(rows, level), [rows, level]);
  const platforms = useMemo(
    () => [...new Set(pooled.map((a) => a.platform).filter(Boolean))] as string[],
    [pooled]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let out = pooled;
    if (platform !== 'all') out = out.filter((a) => a.platform === platform);
    if (q) out = out.filter((a) => a.adName.toLowerCase().includes(q)
      || (a.campaignName ?? '').toLowerCase().includes(q));
    if (from) out = out.filter((a) => (a.firstDate ?? '') >= from);
    if (to) out = out.filter((a) => (a.firstDate ?? '9999') <= to);
    const dir = sortDesc ? -1 : 1;
    return [...out].sort((a, b) => {
      const va = sortVal(a, sortKey); const vb = sortVal(b, sortKey);
      return va < vb ? -dir : va > vb ? dir : 0;
    });
  }, [pooled, platform, search, from, to, sortKey, sortDesc]);

  // Summary analytics over the FILTERED set — the tiles answer for exactly
  // what's on screen, so filtering IS the analysis.
  const sum = useMemo(() => {
    const t = { ads: filtered.length, spend: 0, impressions: 0, clicks: 0, conversions: 0, revenue: 0, hasRevenue: false, hasConv: false };
    for (const a of filtered) {
      t.spend += a.spend; t.impressions += a.impressions; t.clicks += a.clicks;
      if (a.conversions != null) { t.conversions += a.conversions; t.hasConv = true; }
      if (a.revenue != null) { t.revenue += a.revenue; t.hasRevenue = true; }
    }
    return t;
  }, [filtered]);
  const aggCtr = sum.impressions > 0 ? sum.clicks / sum.impressions : null;
  const aggCpm = sum.impressions > 0 ? (sum.spend / sum.impressions) * 1000 : null;
  const aggRoas = sum.hasRevenue && sum.spend > 0 ? sum.revenue / sum.spend : null;

  // Top / bottom by CTR with a volume gate — small ads produce noise, not insight.
  const gated = filtered.filter((a) => a.impressions >= 500 && a.realCtr != null);
  const byCtr = [...gated].sort((a, b) => (b.realCtr ?? 0) - (a.realCtr ?? 0));
  const top = byCtr.slice(0, 5);
  const bottom = byCtr.length > 5 ? byCtr.slice(-5).reverse() : [];

  const header = (label: string, key: SortKey, align = 'text-right') => (
    <th className={`${align} px-3 py-2.5 cursor-pointer select-none whitespace-nowrap hover:text-ink`}
      onClick={() => { if (sortKey === key) setSortDesc((d) => !d); else { setSortKey(key); setSortDesc(true); } }}>
      {label}{sortKey === key ? (sortDesc ? ' ↓' : ' ↑') : ''}
    </th>
  );

  return (
    <div className="max-w-6xl">
      <h1 className="display-italic text-[34px] mb-1">Your <span className="gradient-text">ad library</span></h1>
      <p className="text-ink-muted text-[14.5px] mb-5 max-w-2xl">
        Every real ad synced or uploaded into this workspace — searchable and filterable, with the
        analytics recomputed live for whatever slice you're looking at.
      </p>

      {/* SUMMARY TILES — for the current filter */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
        {[
          { label: 'Ads', value: sum.ads.toLocaleString() },
          { label: 'Spend', value: `${cur} ${Math.round(sum.spend).toLocaleString()}` },
          { label: 'Impressions', value: sum.impressions.toLocaleString() },
          { label: 'CTR', value: aggCtr != null ? `${(aggCtr * 100).toFixed(2)}%` : '—' },
          { label: 'CPM', value: aggCpm != null ? `${cur} ${aggCpm.toFixed(2)}` : '—' },
          { label: 'ROAS', value: aggRoas != null ? `${aggRoas.toFixed(2)}×` : '—' },
          { label: 'Conversions', value: sum.hasConv ? Math.round(sum.conversions).toLocaleString() : '—' },
          { label: 'Cost / conversion', value: sum.hasConv && sum.conversions > 0 ? `${cur} ${(sum.spend / sum.conversions).toFixed(2)}` : '—' },
        ].map((m) => (
          <Card key={m.label} className="!p-3">
            <div className="text-[10.5px] text-ink-muted uppercase tracking-[0.08em] font-bold">{m.label}</div>
            <div className="font-heading font-bold text-[19px] mt-0.5 font-mono">{m.value}</div>
          </Card>
        ))}
      </div>

      {/* FILTERS */}
      <Card className="!p-3.5 mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[220px]">
            <label className="label">Search ads</label>
            <input className="input" value={search} onChange={(e) => { setSearch(e.target.value); setShown(50); }}
              placeholder="Type any part of an ad name…" />
          </div>
          <div>
            <label className="label">Group by</label>
            <div className="inline-flex bg-bg-deep p-1 rounded-lg">
              {(['ad', 'adset', 'campaign'] as const).map((l) => (
                <button key={l} type="button"
                  onClick={() => { setLevel(l); setShown(50); }}
                  className={`px-3 py-1.5 rounded-md text-[12.5px] font-semibold transition-colors ${level === l ? 'bg-surface shadow-soft text-ink' : 'text-ink-muted'}`}>
                  {l === 'ad' ? 'Ad' : l === 'adset' ? 'Ad set' : 'Campaign'}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="label">Platform</label>
            <select className="input !w-auto" value={platform} onChange={(e) => { setPlatform(e.target.value); setShown(50); }}>
              <option value="all">All platforms</option>
              {platforms.map((p) => <option key={p} value={p}>{PLATFORM_LABEL[p] ?? p}</option>)}
            </select>
          </div>
          <div>
            <label className="label">From</label>
            <input className="input !w-auto" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </div>
          <div>
            <label className="label">To</label>
            <input className="input !w-auto" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </div>
          {(search || platform !== 'all' || from || to) && (
            <button type="button" className="text-[12.5px] text-ink-muted underline pb-2.5"
              onClick={() => { setSearch(''); setPlatform('all'); setFrom(''); setTo(''); }}>
              Clear filters
            </button>
          )}
        </div>
      </Card>

      {/* TOP / BOTTOM PERFORMERS */}
      {(top.length >= 3) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-5">
          <Card className="!p-4">
            <div className="text-[11px] text-ink-muted uppercase tracking-[0.08em] font-bold mb-2">🏆 Highest CTR (≥500 impressions)</div>
            <div className="space-y-1.5">
              {top.map((a) => (
                <div key={a.key} className="flex items-center gap-2 text-[13px]">
                  <span className="flex-1 truncate">{a.adName}</span>
                  <span className="font-mono font-bold">{((a.realCtr ?? 0) * 100).toFixed(2)}%</span>
                  <span className="text-ink-faint text-[11.5px] font-mono w-20 text-right">{cur} {Math.round(a.spend).toLocaleString()}</span>
                </div>
              ))}
            </div>
          </Card>
          {bottom.length > 0 && (
            <Card className="!p-4">
              <div className="text-[11px] text-ink-muted uppercase tracking-[0.08em] font-bold mb-2">🐌 Lowest CTR (≥500 impressions)</div>
              <div className="space-y-1.5">
                {bottom.map((a) => (
                  <div key={a.key} className="flex items-center gap-2 text-[13px]">
                    <span className="flex-1 truncate">{a.adName}</span>
                    <span className="font-mono font-bold">{((a.realCtr ?? 0) * 100).toFixed(2)}%</span>
                    <span className="text-ink-faint text-[11.5px] font-mono w-20 text-right">{cur} {Math.round(a.spend).toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}

      {/* TABLE */}
      {loading ? (
        <Card className="text-center py-12 text-ink-muted text-[14px]">Loading your ads…</Card>
      ) : pooled.length === 0 ? (
        <Card className="text-center py-12">
          <div className="text-[15px] font-semibold mb-1">No ad data yet</div>
          <div className="text-ink-muted text-[13.5px]">
            Connect a platform or upload a results CSV on the{' '}
            <Link href="/data" className="text-violet underline font-semibold">Data page</Link> — every synced ad lands here.
          </div>
        </Card>
      ) : (
        <Card className="!p-0 overflow-hidden">
          <div className="px-5 py-3 bg-bg-deep text-[11.5px] text-ink-muted uppercase tracking-[0.06em] font-bold">
            {filtered.length.toLocaleString()} {level === 'ad' ? 'ad' : level === 'adset' ? 'ad set' : 'campaign'}{filtered.length === 1 ? '' : 's'}
            {filtered.length !== pooled.length && <> (of {pooled.length.toLocaleString()})</>}
            {' '}· pooled from {rows.length.toLocaleString()} daily rows · click a column to sort
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]">
              <thead className="text-[10.5px] text-ink-faint uppercase tracking-[0.06em]">
                <tr>
                  {header(level === 'ad' ? 'Ad' : level === 'adset' ? 'Ad set' : 'Campaign', 'name', 'text-left px-4')}
                  {level === 'ad' && <th className="text-left px-3 py-2.5">Campaign</th>}
                  <th className="text-left px-3 py-2.5">Platform</th>
                  {header('First seen', 'date')}
                  {header('Impressions', 'impressions')}
                  {header('Clicks', 'clicks')}
                  {header('CTR', 'ctr')}
                  {header('Spend', 'spend')}
                  {header('CPM', 'cpm')}
                  <th className="text-right px-3 py-2.5">CPC</th>
                  {header('Freq', 'frequency')}
                  <th className="text-right px-3 py-2.5">Conv.</th>
                  {header('CVR', 'cvr')}
                  {header('CPA', 'cpa')}
                  {header('ROAS', 'roas')}
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0, shown).map((a) => {
                  const cpc = cpcOf(a);
                  return (
                    <tr key={a.key} className="border-t border-border-soft hover:bg-bg-deep/40">
                      <td className="px-4 py-2 max-w-[260px] truncate font-semibold" title={a.adName}>{a.adName}</td>
                      {level === 'ad' && (
                        <td className="px-3 py-2 max-w-[170px] truncate text-ink-muted" title={a.campaignName ?? undefined}>{a.campaignName ?? '—'}</td>
                      )}
                      <td className="px-3 py-2 whitespace-nowrap">
                        <Pill tone="muted">{PLATFORM_LABEL[a.platform ?? ''] ?? a.platform ?? '—'}</Pill>
                      </td>
                      <td className="text-right px-3 py-2 font-mono whitespace-nowrap">{a.firstDate ?? '—'}</td>
                      <td className="text-right px-3 py-2 font-mono">{a.impressions.toLocaleString()}</td>
                      <td className="text-right px-3 py-2 font-mono">{a.clicks.toLocaleString()}</td>
                      <td className="text-right px-3 py-2 font-mono">{a.realCtr != null ? `${(a.realCtr * 100).toFixed(2)}%` : '—'}</td>
                      <td className="text-right px-3 py-2 font-mono">{Math.round(a.spend).toLocaleString()}</td>
                      <td className="text-right px-3 py-2 font-mono">{a.impressions > 0 ? cpmOf(a).toFixed(2) : '—'}</td>
                      <td className="text-right px-3 py-2 font-mono">{cpc != null ? cpc.toFixed(2) : '—'}</td>
                      <td className="text-right px-3 py-2 font-mono">{a.frequency != null ? a.frequency.toFixed(1) : '—'}</td>
                      <td className="text-right px-3 py-2 font-mono">{a.conversions != null ? Math.round(a.conversions).toLocaleString() : '—'}</td>
                      <td className="text-right px-3 py-2 font-mono">{cvrOf(a) != null ? `${((cvrOf(a) ?? 0) * 100).toFixed(1)}%` : '—'}</td>
                      <td className="text-right px-3 py-2 font-mono">{cpaOf(a) != null ? (cpaOf(a) ?? 0).toFixed(2) : '—'}</td>
                      <td className="text-right px-3 py-2 font-mono">{a.realRoas != null ? `${a.realRoas.toFixed(2)}×` : '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {filtered.length > shown && (
            <div className="px-5 py-3 border-t border-border-soft text-center">
              <button type="button" onClick={() => setShown((s) => s + 100)}
                className="text-[13px] font-semibold text-coral">
                Show 100 more ({(filtered.length - shown).toLocaleString()} remaining)
              </button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
