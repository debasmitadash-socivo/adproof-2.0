'use client';
// Owner-only diagnostics page. Surfaces what is actually working under the
// hood so the owner can debug provider/quota/inspection state without
// reading logs — was the image actually read, did Gemini fall back to the
// heuristic, which provider answered the most recent run, etc.
//
// All numbers come from data already on the saved campaigns (the simulate
// response stores provider/model/is_heuristic/provider_error per variant) +
// /api/healthz for what's configured. Nothing new in the DB.
import { useEffect, useMemo, useState } from 'react';
import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { useApp } from '@/lib/store';
import { api } from '@/lib/api';
import type { SavedCampaign } from '@/lib/types';

type Health = Awaited<ReturnType<typeof api.health>>;

type RunRow = {
  ts: number;
  campaignId: string;
  campaignName: string;
  variantLabel: string;
  mediaKind: 'image' | 'video' | 'text';
  provider: string;
  model: string;
  isHeuristic: boolean;
  providerError: string;
  inspectionOk: boolean;
  inspectionLabel: string;       // human one-liner
  banLevel: string;
  imageDesc: string;
  workspaceName: string;
};

// Flatten saved campaigns → one row per variant for the diagnostics table.
function flattenRuns(campaigns: SavedCampaign[], workspaceFor: (id?: string) => string): RunRow[] {
  const rows: RunRow[] = [];
  for (const c of campaigns) {
    const variants = (c.variants && c.variants.length)
      ? c.variants
      : [{ label: 'A', headline: c.name, result: c.result, thumbnailUrl: c.thumbnailUrl } as { label: string; result?: SavedCampaign['result']; thumbnailUrl?: string | null }];
    for (const v of variants) {
      const r = v.result;
      const vis = r?.visual ?? null;
      // The response's compact format block doesn't carry media_type; derive it
      // from the saved formatName / formatId. Text-only formats are the two
      // Google Search RSA and LinkedIn Sponsored Messaging units.
      const fmtId = (r?.format?.id ?? '').toLowerCase();
      const fmtName = (c.formatName ?? '').toLowerCase();
      const isVideo = /reels|video|stories|bumper|in-stream|in_stream|spark|infeed/.test(fmtId + ' ' + fmtName);
      const isText = /search|rsa|messaging|message/.test(fmtId);
      const mediaKind: RunRow['mediaKind'] = isText ? 'text' : isVideo ? 'video' : 'image';
      const provider = vis?.provider ?? 'none';
      const isHeur = !!vis?.is_heuristic;
      const providerError = vis?.provider_error ?? '';
      const banLevel = vis?.ban_risk?.level ?? 'unknown';
      // Inspection is "real" when a non-heuristic provider answered AND
      // there's an image description AND a non-unknown ban-risk read.
      const inspectionOk = !isHeur
        && !!vis
        && (vis.image_description ?? '').trim().length > 0
        && banLevel !== 'unknown';
      const inspectionLabel = mediaKind === 'text'
        ? 'No creative to inspect (text-only format)'
        : isHeur
          ? `Heuristic fallback — vision didn't run (${providerError || 'no key / quota'})`
          : inspectionOk
            ? `${mediaKind === 'video' ? 'Video' : 'Image'} actually read`
            : `Partial — provider answered but description / ban-risk missing`;
      rows.push({
        ts: c.createdAt,
        campaignId: c.id,
        campaignName: c.name,
        variantLabel: v.label,
        mediaKind,
        provider,
        model: vis?.model ?? '',
        isHeuristic: isHeur,
        providerError,
        inspectionOk,
        inspectionLabel,
        banLevel,
        imageDesc: (vis?.image_description ?? '').slice(0, 160),
        workspaceName: workspaceFor(c.companyId),
      });
    }
  }
  return rows.sort((a, b) => b.ts - a.ts);
}

export default function AdminDiagnosticsPage() {
  const companies = useApp((s) => s.companies);
  const campaigns = useApp((s) => s.savedCampaigns);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthErr, setHealthErr] = useState<string | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);

  async function refreshHealth() {
    setHealthLoading(true); setHealthErr(null);
    try { setHealth(await api.health()); }
    catch (e) { setHealthErr((e as Error).message); }
    finally { setHealthLoading(false); }
  }
  useEffect(() => { refreshHealth(); }, []);

  const workspaceFor = (id?: string) =>
    companies.find((c) => c.id === id)?.company_name || 'Unknown workspace';

  const rows = useMemo(() => flattenRuns(campaigns, workspaceFor),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [campaigns, companies]);

  // Aggregate counts per provider (for the summary chips).
  const byProvider = useMemo(() => {
    const m: Record<string, { real: number; heuristic: number }> = {};
    for (const r of rows) {
      const p = r.provider || 'none';
      m[p] = m[p] || { real: 0, heuristic: 0 };
      if (r.mediaKind === 'text') continue;
      r.isHeuristic ? m[p].heuristic++ : m[p].real++;
    }
    return m;
  }, [rows]);

  // Quick win/loss counts for the headline strip.
  const visualRuns = rows.filter((r) => r.mediaKind !== 'text');
  const realCount = visualRuns.filter((r) => r.inspectionOk).length;
  const heurCount = visualRuns.filter((r) => r.isHeuristic).length;
  const partialCount = visualRuns.length - realCount - heurCount;

  return (
    <>
      <div className="text-[12.5px] text-ink-muted mb-2">Workspace · Admin · Diagnostics</div>
      <div className="display-italic text-[38px] leading-[1.05]">
        Diagnostics <span className="gradient-text">— what's actually working</span>
      </div>
      <p className="text-ink-muted text-[14px] mt-2 mb-7 max-w-[760px]">
        Owner-only. Shows provider availability, quota state and per-run inspection
        status (was the image / video actually read, or did the heuristic fallback
        fire). All data is pulled from saved runs and <code className="font-mono text-[12px]">/api/healthz</code> —
        no extra logging on the analysis pages.
      </p>

      {/* ─── Provider availability ──────────────────────────────────────── */}
      <Card className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-heading text-[16px] font-bold tracking-tight">Provider availability</h2>
          <button onClick={refreshHealth} disabled={healthLoading}
            className="text-coral font-semibold text-[12.5px] disabled:opacity-50">
            {healthLoading ? 'Checking…' : '↻ Refresh'}
          </button>
        </div>
        {healthErr && (
          <div className="text-[12.5px] text-danger bg-danger-soft border border-danger/30 rounded-md p-2.5 mb-3">
            Couldn't reach the backend: {healthErr}
          </div>
        )}
        {health && (
          <>
            <div className="flex flex-wrap gap-2 mb-2">
              {([
                ['Anthropic (Claude)', health.anthropic],
                ['OpenAI (GPT-4o)',    health.openai],
                ['Gemini (video too)', health.gemini],
                ['Groq',               health.groq],
                ['Mistral',            health.mistral],
                ['OpenRouter',         health.openrouter],
                ['xAI (Grok)',         health.xai],
                ['Together',           health.together],
              ] as const).map(([label, ok]) => (
                <Pill key={label} tone={ok ? 'success' : 'muted'} dot>
                  {ok ? '✓' : '✗'} {label}
                </Pill>
              ))}
            </div>
            <div className="text-[12.5px] text-ink-muted">
              Backend <span className="font-mono">{health.version}</span>. {health.llm
                ? 'At least one LLM key is configured.'
                : '⚠ No LLM key configured — vision will run on heuristic fallback only.'}
            </div>
          </>
        )}
      </Card>

      {/* ─── Headline KPI strip ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
        <Card>
          <div className="text-[11.5px] text-success font-bold uppercase tracking-[0.09em]">Real inspections</div>
          <div className="display-italic text-[34px] leading-none mt-1.5">{realCount}</div>
          <div className="text-[12.5px] text-ink-muted mt-1">Provider answered + description + ban-risk read.</div>
        </Card>
        <Card>
          <div className="text-[11.5px] text-warning font-bold uppercase tracking-[0.09em]">Heuristic fallbacks</div>
          <div className="display-italic text-[34px] leading-none mt-1.5">{heurCount}</div>
          <div className="text-[12.5px] text-ink-muted mt-1">Vision didn't run — no key, quota, or error.</div>
        </Card>
        <Card>
          <div className="text-[11.5px] text-coral font-bold uppercase tracking-[0.09em]">Partial</div>
          <div className="display-italic text-[34px] leading-none mt-1.5">{partialCount}</div>
          <div className="text-[12.5px] text-ink-muted mt-1">Provider replied but missing description / ban screen.</div>
        </Card>
      </div>

      {/* ─── Per-provider breakdown ─────────────────────────────────────── */}
      {Object.keys(byProvider).length > 0 && (
        <Card className="mb-6">
          <h2 className="font-heading text-[16px] font-bold tracking-tight mb-3">Per-provider usage</h2>
          <div className="flex flex-wrap gap-2">
            {Object.entries(byProvider).sort((a, b) => (b[1].real + b[1].heuristic) - (a[1].real + a[1].heuristic)).map(([p, { real, heuristic }]) => (
              <Pill key={p} tone={real > 0 ? 'lime' : 'warning'}>
                <span className="font-semibold">{p}</span>
                <span className="text-[11px] opacity-80 ml-1.5">{real} real · {heuristic} fallback</span>
              </Pill>
            ))}
          </div>
        </Card>
      )}

      {/* ─── Per-run table ──────────────────────────────────────────────── */}
      <Card>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-heading text-[16px] font-bold tracking-tight">Recent runs ({rows.length})</h2>
          <span className="text-[12.5px] text-ink-muted">{campaigns.length} campaigns · {rows.length} variant runs</span>
        </div>
        {rows.length === 0 ? (
          <div className="text-ink-muted text-[14px] py-10 text-center">
            No saved runs yet. Score an ad to populate this page.
          </div>
        ) : (
          <div className="overflow-x-auto -mx-5 px-5">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-[11px] text-ink-muted uppercase tracking-[0.07em] font-bold text-left">
                  <th className="py-2 pr-3 font-bold">When</th>
                  <th className="py-2 pr-3 font-bold">Workspace</th>
                  <th className="py-2 pr-3 font-bold">Campaign · Variant</th>
                  <th className="py-2 pr-3 font-bold">Creative</th>
                  <th className="py-2 pr-3 font-bold">Provider · Model</th>
                  <th className="py-2 pr-3 font-bold">Inspection</th>
                  <th className="py-2 pr-3 font-bold">Ban screen</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 100).map((r, i) => (
                  <tr key={`${r.campaignId}_${r.variantLabel}_${i}`} className="border-t border-border-soft align-top">
                    <td className="py-2.5 pr-3 text-ink-muted whitespace-nowrap font-mono text-[11.5px]">
                      {new Date(r.ts).toLocaleString('en-GB', { year: '2-digit', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                    </td>
                    <td className="py-2.5 pr-3 truncate max-w-[140px]" title={r.workspaceName}>{r.workspaceName}</td>
                    <td className="py-2.5 pr-3">
                      <div className="truncate max-w-[220px]" title={r.campaignName}>{r.campaignName}</div>
                      <div className="text-[11.5px] text-ink-muted">Variant {r.variantLabel}</div>
                    </td>
                    <td className="py-2.5 pr-3">
                      <Pill tone={r.mediaKind === 'video' ? 'violet' : r.mediaKind === 'text' ? 'muted' : 'magenta'}>{r.mediaKind}</Pill>
                    </td>
                    <td className="py-2.5 pr-3">
                      <div className="font-semibold">{r.provider}</div>
                      <div className="text-[11.5px] text-ink-muted truncate max-w-[200px]" title={r.model}>{r.model}</div>
                    </td>
                    <td className="py-2.5 pr-3">
                      <Pill tone={r.mediaKind === 'text' ? 'muted' : r.inspectionOk ? 'success' : r.isHeuristic ? 'warning' : 'coral'} dot>
                        {r.inspectionOk ? '✓' : r.isHeuristic ? '⚠' : '~'}
                        {' '}
                        {r.inspectionLabel}
                      </Pill>
                      {r.providerError && (
                        <div className="text-[11px] text-danger mt-1 truncate max-w-[300px]" title={r.providerError}>
                          {r.providerError}
                        </div>
                      )}
                      {r.imageDesc && !r.isHeuristic && (
                        <div className="text-[11px] text-ink-muted mt-1 italic truncate max-w-[300px]" title={r.imageDesc}>
                          "{r.imageDesc}"
                        </div>
                      )}
                    </td>
                    <td className="py-2.5 pr-3">
                      <Pill tone={
                        r.banLevel === 'high' ? 'danger'
                        : r.banLevel === 'medium' ? 'warning'
                        : r.banLevel === 'unknown' ? 'muted'
                        : 'success'
                      }>{r.banLevel}</Pill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length > 100 && (
              <div className="mt-3 text-[12.5px] text-ink-muted text-center">
                Showing the latest 100 of {rows.length} runs.
              </div>
            )}
          </div>
        )}
      </Card>
    </>
  );
}
