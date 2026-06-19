'use client';
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/lib/api';
import { saveCalibration, insertOutcomes, getLatestCalibration } from '@/lib/db';
import { useApp } from '@/lib/store';
import type { IngestResult, AccountCalibration, PlatformCalibration } from '@/lib/types';

const CONF_TONE: Record<string, 'success' | 'warning' | 'danger'> = {
  high: 'success', medium: 'warning', low: 'danger',
};
const FAT_TONE: Record<'healthy' | 'warning' | 'urgent' | 'depleted', 'success' | 'warning' | 'danger'> = {
  healthy: 'success', warning: 'warning', urgent: 'danger', depleted: 'danger',
};
const PLATFORM_LABEL: Record<string, string> = {
  meta_facebook: 'Facebook', meta_instagram: 'Instagram', linkedin: 'LinkedIn',
  tiktok: 'TikTok', youtube: 'YouTube', google_search: 'Google Search',
};

function pct(x: number | null | undefined) { return x == null ? '—' : `${(x * 100).toFixed(2)}%`; }
function money(x: number | null | undefined, cur: string) { return x == null ? '—' : `${cur} ${x.toFixed(2)}`; }

// Pillar B+: pretty labels — must match the slugs in outcomes.INTEREST_BUCKETS
// and api/main.py's _INTEREST_LABEL / _SEGMENT_LABEL.
const SEGMENT_LABEL: Record<string, string> = {
  all: 'All', gen_z: 'Gen Z', millennials: 'Millennials', gen_x: 'Gen X',
  boomers: 'Boomers', high_income: 'High income', budget_conscious: 'Budget',
  early_adopters: 'Early adopters', socially_influenced: 'Socially influenced',
};
const INTEREST_LABEL: Record<string, string> = {
  fitness: 'Fitness', fashion: 'Fashion', beauty: 'Beauty', tech: 'Tech',
  travel: 'Travel', food: 'Food / drink', home: 'Home / DIY',
  finance: 'Finance', automotive: 'Auto', entertainment: 'Entertainment',
  business: 'Business', wellness: 'Wellness',
};

function CrossTabMatrix({ cal }: { cal: AccountCalibration }) {
  const xtab = cal.by_segment_interest;
  if (!xtab || !Object.keys(xtab).length) return null;

  // Collect every segment + interest that appears in any cell, ordered by
  // total n_ads (highest first) so the densest combos sit top-left.
  const segTotals: Record<string, number> = {};
  const intTotals: Record<string, number> = {};
  for (const [seg, cells] of Object.entries(xtab)) {
    for (const [interest, agg] of Object.entries(cells)) {
      segTotals[seg] = (segTotals[seg] ?? 0) + (agg.n_ads ?? 0);
      intTotals[interest] = (intTotals[interest] ?? 0) + (agg.n_ads ?? 0);
    }
  }
  const segments = Object.keys(segTotals).sort((a, b) => segTotals[b] - segTotals[a]);
  const interests = Object.keys(intTotals).sort((a, b) => intTotals[b] - intTotals[a]);

  // Find the best cell by CTR so the UI can highlight where the user's
  // account actually wins — the whole point of this surface.
  let bestKey: string | null = null;
  let bestCtr = 0;
  for (const seg of segments) {
    for (const interest of interests) {
      const c = xtab[seg]?.[interest];
      if (c?.real_ctr && c.real_ctr > bestCtr) {
        bestCtr = c.real_ctr;
        bestKey = `${seg}::${interest}`;
      }
    }
  }

  return (
    <div className="mt-4">
      <div className="flex items-center gap-2 mb-2">
        <div className="font-heading text-[14.5px] font-bold">What&apos;s working — audience × interest</div>
        <Pill tone="violet">cross-tab</Pill>
      </div>
      <div className="text-[12.5px] text-ink-muted mb-2">
        Real CTR for every (audience × interest) cell with enough ads to be trustworthy (≥3 ads + ≥5k impressions). Highlighted cell is your best-performing combo on real data.
      </div>
      <div className="overflow-x-auto">
        <table className="text-[12.5px] border-collapse">
          <thead>
            <tr>
              <th className="text-left px-3 py-2 bg-bg-deep text-[11px] text-ink-muted uppercase tracking-[0.06em] font-bold sticky left-0">Segment ↓ / Interest →</th>
              {interests.map((i) => (
                <th key={i} className="text-right px-3 py-2 bg-bg-deep text-[11px] text-ink-muted uppercase tracking-[0.06em] font-bold">{INTEREST_LABEL[i] ?? i}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {segments.map((seg) => (
              <tr key={seg} className="border-b border-border-soft last:border-b-0">
                <td className="text-left px-3 py-2 font-semibold text-ink bg-bg-deep/50 sticky left-0">{SEGMENT_LABEL[seg] ?? seg}</td>
                {interests.map((interest) => {
                  const cell = xtab[seg]?.[interest];
                  const isBest = bestKey === `${seg}::${interest}`;
                  return (
                    <td key={interest} className={`text-right px-3 py-2 mono whitespace-nowrap ${isBest ? 'bg-lime-soft text-ink font-bold' : ''}`}>
                      {cell?.real_ctr != null
                        ? <>{(cell.real_ctr * 100).toFixed(2)}%<span className="text-ink-faint ml-1">({cell.n_ads}a)</span></>
                        : <span className="text-ink-faint">—</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {cal.by_segment_unknown != null && cal.by_segment_unknown > 0 && (
        <div className="text-[11.5px] text-ink-muted mt-2">
          {cal.by_segment_unknown} ad{cal.by_segment_unknown === 1 ? '' : 's'} couldn&apos;t be classified to an audience segment — name your ad sets clearly (e.g. &quot;Gen Z fitness drop&quot;) to lift coverage.
        </div>
      )}
    </div>
  );
}

function CalTable({ cal }: { cal: AccountCalibration }) {
  const rows = Object.entries(cal.by_platform) as [string, PlatformCalibration][];
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13.5px]">
        <thead className="bg-bg-deep text-[11px] text-ink-muted uppercase tracking-[0.06em] font-bold">
          <tr>
            <th className="text-left px-4 py-2.5">Platform</th>
            <th className="text-right px-3 py-2.5">Ads</th>
            <th className="text-right px-3 py-2.5">Real CTR</th>
            <th className="text-right px-3 py-2.5">Real CPM</th>
            <th className="text-right px-3 py-2.5">Real CPC</th>
            <th className="text-right px-3 py-2.5">Conv. rate</th>
            <th className="text-right px-3 py-2.5">Confidence</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([plat, a]) => (
            <tr key={plat} className="border-b border-border-soft last:border-b-0">
              <td className="text-left px-4 py-2.5 font-semibold text-ink">{PLATFORM_LABEL[plat] ?? plat}</td>
              <td className="text-right px-3 py-2.5 font-mono">{a.n_ads}</td>
              <td className="text-right px-3 py-2.5 font-mono">{pct(a.real_ctr)}</td>
              <td className="text-right px-3 py-2.5 font-mono">{money(a.real_cpm, cal.currency)}</td>
              <td className="text-right px-3 py-2.5 font-mono">{money(a.real_cpc, cal.currency)}</td>
              <td className="text-right px-3 py-2.5 font-mono">{pct(a.real_cvr)}</td>
              <td className="text-right px-3 py-2.5"><Pill tone={CONF_TONE[a.confidence]} dot>{a.confidence}</Pill></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DataPage() {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [existing, setExisting] = useState<AccountCalibration | null>(null);
  // Live ad-account pull (Phase 3, read-only). Token used per-request, not stored.
  const [token, setToken] = useState('');
  const [accountId, setAccountId] = useState('');
  const [since, setSince] = useState(() => new Date(Date.now() - 90 * 864e5).toISOString().slice(0, 10));
  const [until, setUntil] = useState(() => new Date().toISOString().slice(0, 10));
  const [syncing, setSyncing] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  // Per-workspace: calibration belongs to the active workspace, not the user
  // overall. Reload when the workspace changes.
  const currentCompanyId = useApp((s) => s.currentCompanyId);
  const profile = useApp((s) => s.companyProfile);
  // B2B audiences are smaller and fatigue sooner — tag the fatigue thresholds
  // by the workspace's business model so a B2B account and a DTC account
  // aren't judged on the same frequency ceiling.
  const segment: 'general' | 'b2b_saas' =
    (profile?.business_model || '').toLowerCase().includes('b2b') ? 'b2b_saas' : 'general';

  useEffect(() => {
    getLatestCalibration(currentCompanyId ?? undefined).then(setExisting).catch(() => {});
  }, [currentCompanyId]);

  async function analyze() {
    if (!file) return;
    setBusy(true); setError(null); setResult(null); setSaved(null);
    try {
      setResult(await api.ingestOutcomes(file, segment));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to read that file.');
    } finally {
      setBusy(false);
    }
  }

  async function pullLive() {
    if (!token.trim() || !accountId.trim()) return;
    setSyncing(true); setError(null); setResult(null); setSaved(null);
    try {
      setResult(await api.syncConnection({
        provider: 'meta', access_token: token.trim(), account_id: accountId.trim(),
        since, until, segment, currency: existing?.currency || 'GBP',
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not pull from that account.');
    } finally {
      setSyncing(false);
    }
  }

  async function save() {
    if (!result) return;
    setBusy(true); setError(null);
    try {
      const nAds = result.calibration.overall?.n_ads ?? result.report.n_rows_kept;
      await saveCalibration(result.calibration, nAds, result.backtest, file?.name, currentCompanyId ?? undefined);
      const n = await insertOutcomes(result.rows, file?.name, currentCompanyId ?? undefined);
      setExisting(result.calibration);
      setSaved(`Saved. Your forecasts now use your real benchmarks (${n.toLocaleString()} ads stored).`);
      setResult(null); setFile(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save to your account.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-4xl">
      <h1 className="display-italic text-[34px] mb-1">Calibrate to <span className="gradient-text">your data</span></h1>
      <p className="text-ink-muted text-[14.5px] mb-6 max-w-2xl">
        Upload a past ad-performance export (Meta or Google Ads, or our template). We learn <strong>your</strong> real
        click-through and cost rates per platform and use them in every forecast — instead of generic industry averages.
        Your data stays private to your account.
      </p>

      {existing && !result && (
        <Card className="mb-5 !bg-lime-soft !border-lime-deep/40">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xl">✓</span>
            <div className="text-[14px] font-semibold text-ink">Your forecasts are calibrated to your account ({existing.currency}).</div>
          </div>
          <CalTable cal={existing} />
          <CrossTabMatrix cal={existing} />
          <div className="text-[12px] text-ink-faint mt-2">Upload a fresh export below to update it.</div>
        </Card>
      )}

      <Card className="mb-5">
        <div className="flex items-center gap-3 flex-wrap">
          <input
            type="file" accept=".csv,.xlsx,.xls"
            onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); setSaved(null); setError(null); }}
            className="text-[13.5px] file:mr-3 file:rounded-lg file:border-0 file:bg-ink file:text-white file:px-4 file:py-2 file:font-semibold"
          />
          <Button onClick={analyze} disabled={!file || busy}>{busy ? 'Reading…' : 'Analyze'}</Button>
        </div>
        <div className="text-[12px] text-ink-faint mt-2">
          .csv or .xlsx · we auto-detect Meta / Google columns · max 25 MB · for the visual side, see the template&apos;s notes.
        </div>
      </Card>

      {/* LIVE PULL — read-only ad-account connection (Phase 3, first cut). */}
      <Card className="mb-5">
        <div className="flex items-center gap-2 mb-1 relative">
          <div className="font-heading text-[15px] font-bold">Or pull live from your ad account</div>
          <Pill tone="violet">beta · Meta</Pill>
          <button
            type="button"
            onClick={() => setShowHelp((v) => !v)}
            aria-label="How to get a Meta access token"
            aria-expanded={showHelp}
            className="w-5 h-5 rounded-full border border-violet/50 text-violet text-[11px] font-bold leading-none flex items-center justify-center hover:bg-violet/10"
          >i</button>
          {showHelp && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowHelp(false)} />
              <div className="absolute z-50 top-8 left-0 w-[min(440px,92vw)] bg-surface border border-border rounded-lg shadow-soft p-4 text-[12.5px] text-ink leading-snug">
                <div className="flex items-center justify-between mb-2">
                  <strong className="text-[13px]">How to get a Meta access token</strong>
                  <button type="button" onClick={() => setShowHelp(false)} aria-label="Close" className="text-ink-muted hover:text-ink text-[14px]">✕</button>
                </div>
                <ol className="list-decimal pl-4 space-y-1.5">
                  <li>Open <a className="text-violet underline" href="https://developers.facebook.com/tools/explorer/" target="_blank" rel="noreferrer">Graph API Explorer</a>.</li>
                  <li>Top-right, pick your app (or create one — any app works).</li>
                  <li>Click <strong>Generate Access Token</strong> and log in.</li>
                  <li>Under Permissions, add <span className="font-mono">ads_read</span> and <span className="font-mono">read_insights</span>.</li>
                  <li>Copy the token (starts with <span className="font-mono">EAAG…</span>) and paste it above.</li>
                </ol>
                <p className="text-[11.5px] text-ink-muted mt-2">
                  Explorer tokens last ~1-2 hours — fine for a one-off pull. For ongoing use, create a{' '}
                  <a className="text-violet underline" href="https://business.facebook.com/settings/system-users" target="_blank" rel="noreferrer">System User</a> token with <span className="font-mono">ads_read</span>.
                </p>
                <p className="text-[11.5px] text-ink-muted mt-2">
                  <strong>Ad account ID:</strong> in <a className="text-violet underline" href="https://adsmanager.facebook.com/" target="_blank" rel="noreferrer">Ads Manager</a>, open the account dropdown (top-left) — it&apos;s the <span className="font-mono">act_…</span> number, or in the page URL after <span className="font-mono">act=</span>.
                </p>
              </div>
            </>
          )}
        </div>
        <p className="text-[12.5px] text-ink-muted mb-3 leading-snug">
          Read-only. Paste a Meta access token (from Graph API Explorer or a System User) and your
          ad-account ID — we pull your real performance and calibrate, no CSV needed. We only ever
          <strong> read</strong> performance, never change your campaigns. The token is used for this
          request only and isn&apos;t stored yet.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="label">Meta access token</label>
            <input className="input font-mono text-[12px]" type="password" autoComplete="off"
              value={token} onChange={(e) => setToken(e.target.value)} placeholder="EAAG…" />
            <a className="text-[11.5px] text-violet underline mt-1 inline-block"
              href="https://developers.facebook.com/tools/explorer/" target="_blank" rel="noreferrer">
              Get a token in Graph API Explorer →
            </a>
          </div>
          <div>
            <label className="label">Ad account ID</label>
            <input className="input font-mono" value={accountId} onChange={(e) => setAccountId(e.target.value)}
              placeholder="act_1234567890 (or just the digits)" />
            <a className="text-[11.5px] text-violet underline mt-1 inline-block"
              href="https://adsmanager.facebook.com/" target="_blank" rel="noreferrer">
              Find your ad-account ID →
            </a>
          </div>
          <div>
            <label className="label">From</label>
            <input className="input" type="date" value={since} max={until} onChange={(e) => setSince(e.target.value)} />
          </div>
          <div>
            <label className="label">To</label>
            <input className="input" type="date" value={until} min={since} onChange={(e) => setUntil(e.target.value)} />
          </div>
        </div>
        <div className="mt-3">
          <Button onClick={pullLive} disabled={syncing || !token.trim() || !accountId.trim()}>
            {syncing ? 'Pulling…' : 'Pull & calibrate'}
          </Button>
        </div>
      </Card>

      {error && (
        <Card className="mb-5 !bg-danger-soft !border-danger/40">
          <div className="text-[13.5px] text-ink"><strong>Couldn&apos;t read that file.</strong> {error}</div>
        </Card>
      )}
      {saved && (
        <Card className="mb-5 !bg-lime-soft !border-lime-deep/40">
          <div className="text-[14px] text-ink font-semibold">✓ {saved}</div>
        </Card>
      )}

      {result && (
        <>
          <Card className="mb-4">
            <div className="flex items-center gap-3 flex-wrap mb-3">
              <div className="display-italic text-[22px]">Here&apos;s what we learned</div>
              <Pill tone="coral" dot>{result.report.currency}</Pill>
              <span className="text-[13px] text-ink-muted">
                {result.report.n_rows_kept.toLocaleString()} ads read{result.report.sheet ? ` · sheet "${result.report.sheet}"` : ''}
              </span>
              <span className="ml-auto" />
              <Button onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save to my account'}</Button>
            </div>
            <CalTable cal={result.calibration} />
            <CrossTabMatrix cal={result.calibration} />
            {result.report.warnings.length > 0 && (
              <ul className="mt-3 space-y-1">
                {result.report.warnings.map((w, i) => (
                  <li key={i} className="text-[12.5px] text-ink-muted flex gap-2"><span className="text-warning">⚠</span>{w}</li>
                ))}
              </ul>
            )}
          </Card>

          {/* DECAY WARNING — only when there are real per-period dates */}
          {result.calibration.trend && result.calibration.trend.direction !== 'flat' && (
            <Card className={`mb-4 ${result.calibration.trend.direction === 'down' ? '!bg-warning-soft !border-warning/40' : '!bg-lime-soft !border-lime-deep/40'}`}>
              <div className="text-[13.5px] text-ink">
                <strong>{result.calibration.trend.direction === 'down' ? '⚠ Your click-through is trending down.' : '↑ Your click-through is trending up.'}</strong>{' '}
                Older ads averaged {pct(result.calibration.trend.older_ctr)} CTR; recent ones {pct(result.calibration.trend.recent_ctr)}
                {' '}({result.calibration.trend.change_pct >= 0 ? '+' : ''}{Math.round(result.calibration.trend.change_pct * 100)}%).
                We calibrate on your recent data so the forecast tracks where you are now, not where you were.
              </div>
            </Card>
          )}

          {/* ACCURACY BACKTEST — the proof */}
          <Card className="mb-4 !bg-bg-deep !border-border">
            <div className="text-[11.5px] font-bold uppercase tracking-[0.1em] text-ink-muted mb-2">Accuracy check (backtest)</div>
            {result.backtest.usable ? (
              <>
                <div className="text-[14px] text-ink mb-2">
                  Calibrated on your older ads, we predicted the click-through of <strong>{result.backtest.n_test}</strong> held-out
                  ads we hadn&apos;t seen: predicted <strong>{pct(result.backtest.agg_predicted_ctr)}</strong> vs
                  actual <strong>{pct(result.backtest.agg_actual_ctr)}</strong>
                  {result.backtest.agg_abs_pct_error != null && <> — off by <strong>{Math.round(result.backtest.agg_abs_pct_error * 100)}%</strong></>}.
                </div>
                <div className="text-[13px] text-ink-muted">
                  Per-ad: within ±30% on {Math.round((result.backtest.within_30pct ?? 0) * 100)}% of ads
                  (median error {Math.round((result.backtest.median_abs_pct_error ?? 0) * 100)}%).
                </div>
                <div className="text-[11.5px] text-ink-faint mt-2">{result.backtest.note}</div>
              </>
            ) : (
              <div className="text-[13.5px] text-ink-muted">
                <strong>Can&apos;t backtest over time yet.</strong> {result.backtest.reason}
              </div>
            )}
          </Card>

          {/* CREATIVE FATIGUE — segment-tagged, from frequency + CTR-over-time */}
          {result.fatigue && (
            <Card className="mb-4">
              <div className="flex items-center gap-2 flex-wrap mb-2">
                <div className="display-italic text-[20px]">Creative fatigue</div>
                <Pill tone="muted">{result.fatigue.segment === 'b2b_saas' ? 'B2B thresholds' : 'general thresholds'}</Pill>
              </div>
              {result.fatigue.usable ? (
                <>
                  <div className="flex flex-wrap gap-2 mb-3">
                    {(['depleted', 'urgent', 'warning', 'healthy'] as const).map((s) => (
                      <Pill key={s} tone={FAT_TONE[s]} dot>
                        {result.fatigue.counts?.[s] ?? 0} {s}
                      </Pill>
                    ))}
                  </div>
                  {(result.fatigue.needs_attention ?? 0) > 0 ? (
                    <div className="space-y-2">
                      {(result.fatigue.ads ?? []).filter((a) => a.status !== 'healthy').slice(0, 12).map((a, i) => (
                        <div key={i} className="flex items-start gap-2.5 border-b border-border-soft pb-2 last:border-0">
                          <Pill tone={FAT_TONE[a.status]}>{a.status}</Pill>
                          <div className="flex-1 min-w-0">
                            <div className="text-[13.5px] font-semibold text-ink truncate">{a.ad_name}</div>
                            <div className="text-[12px] text-ink-muted">
                              {a.frequency != null && <>freq {a.frequency} · </>}
                              {a.ctr_change_pct != null && <>CTR {a.ctr_change_pct >= 0 ? '+' : ''}{Math.round(a.ctr_change_pct * 100)}% · </>}
                              {a.impressions.toLocaleString()} impressions
                            </div>
                            <div className="text-[12px] text-ink mt-0.5">{a.reasons.join(' · ')}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-[13.5px] text-ink-muted">No fatiguing ads detected — frequencies and click-through look healthy.</div>
                  )}
                  <div className="text-[11.5px] text-ink-faint mt-2">
                    Signals: {result.fatigue.signals_used?.join(', ') || '—'}. {result.fatigue.note}
                  </div>
                </>
              ) : (
                <div className="text-[13.5px] text-ink-muted">
                  <strong>No fatigue signal yet.</strong> {result.fatigue.reason}
                </div>
              )}
            </Card>
          )}

          {result.preview.length > 0 && (
            <Card className="!p-0 overflow-hidden">
              <div className="px-5 py-3 bg-bg-deep text-[11.5px] text-ink-muted uppercase tracking-[0.06em] font-bold">
                Preview — first {result.preview.length} cleaned rows
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[12.5px]">
                  <thead className="text-[11px] text-ink-faint uppercase">
                    <tr>{Object.keys(result.preview[0]).map((k) => (
                      <th key={k} className="text-left px-3 py-2 whitespace-nowrap">{k}</th>
                    ))}</tr>
                  </thead>
                  <tbody>
                    {result.preview.map((row, i) => (
                      <tr key={i} className="border-t border-border-soft">
                        {Object.values(row).map((v, j) => (
                          <td key={j} className="px-3 py-1.5 whitespace-nowrap text-ink">
                            {v == null ? '—' : typeof v === 'number' ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(4)) : String(v).slice(0, 40)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
