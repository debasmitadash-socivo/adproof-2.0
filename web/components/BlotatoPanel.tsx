'use client';
// Pillar E + F UI surface — Blotato MCP integrations.
// Self-hides when BLOTATO_API_KEY is not set on the backend, so a deploy
// without the key has zero visual footprint.
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/lib/api';

type Template = { id: string; description: string };
type VariantResult = {
  status: string;
  visual_id?: string;
  result?: Record<string, unknown>;
  error?: string;
};
type ExtractResult = {
  status: string;
  source_id?: string;
  result?: Record<string, unknown>;
  error?: string;
};

export function BlotatoPanel({ hookSeed }: { hookSeed?: string }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [tab, setTab] = useState<'variant' | 'extract'>('variant');

  // Variant generation state
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templateId, setTemplateId] = useState<string>('');
  const [hook, setHook] = useState(hookSeed ?? '');
  const [count, setCount] = useState(3);
  const [genBusy, setGenBusy] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [variants, setVariants] = useState<VariantResult[]>([]);

  // Source extraction state
  const [url, setUrl] = useState('');
  const [extractBusy, setExtractBusy] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [extracted, setExtracted] = useState<ExtractResult | null>(null);

  useEffect(() => {
    api.blotatoStatus().then((s) => setEnabled(!!s.enabled)).catch(() => setEnabled(false));
  }, []);

  useEffect(() => {
    if (!enabled || tab !== 'variant' || templates.length) return;
    api.blotatoTemplates()
      .then((r) => {
        setTemplates(r.templates ?? []);
        if (r.templates?.[0]?.id) setTemplateId(r.templates[0].id);
      })
      .catch((e) => setGenError(String(e?.message ?? e)));
  }, [enabled, tab, templates.length]);

  if (enabled === null) return null;                       // probing
  if (enabled === false) return null;                      // no key set

  async function generateVariants() {
    setGenBusy(true); setGenError(null); setVariants([]);
    try {
      const r = await api.blotatoGenerateVariants({
        template_id: templateId || undefined,
        variables: hook ? { hook } : {},
        count, wait: true,
      });
      setVariants(r.variants ?? []);
    } catch (e) {
      setGenError(String((e as Error)?.message ?? e));
    } finally {
      setGenBusy(false);
    }
  }

  async function extractSource() {
    if (!url.trim()) return;
    setExtractBusy(true); setExtractError(null); setExtracted(null);
    try {
      const r = await api.blotatoExtractSource({ url: url.trim(), wait: true });
      setExtracted(r);
    } catch (e) {
      setExtractError(String((e as Error)?.message ?? e));
    } finally {
      setExtractBusy(false);
    }
  }

  return (
    <>
      <h2 className="display-italic text-[28px] mt-7 mb-2">Blotato tools</h2>
      <p className="text-ink-muted text-[14px] mb-3">
        Generate visual variants with different hooks (Pillar E) or pull a competitor ad / landing page apart for a head-to-head read (Pillar F). Powered by your Blotato MCP — uses Blotato visual / source credits.
      </p>
      <Card className="!p-0 overflow-hidden border-2 !border-violet/30">
        <div className="flex border-b border-violet/20 bg-violet-soft/40">
          {(['variant', 'extract'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex-1 px-4 py-3 text-[13px] font-semibold ${tab === t ? 'text-violet bg-surface' : 'text-ink-muted hover:text-ink'}`}
            >
              {t === 'variant' ? 'Generate variants' : 'Extract competitor URL'}
            </button>
          ))}
        </div>

        {tab === 'variant' && (
          <div className="p-5 space-y-4">
            <div>
              <label className="block text-[11.5px] uppercase tracking-[0.06em] font-bold text-ink-muted mb-1">Template</label>
              <select
                value={templateId}
                onChange={(e) => setTemplateId(e.target.value)}
                className="w-full px-3 py-2 rounded-md border border-border bg-surface text-[13px]"
                disabled={!templates.length}
              >
                {!templates.length && <option>Loading templates…</option>}
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>{t.description || t.id}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[11.5px] uppercase tracking-[0.06em] font-bold text-ink-muted mb-1">Hook / prompt (template-specific)</label>
              <textarea
                value={hook} onChange={(e) => setHook(e.target.value)}
                rows={3}
                className="w-full px-3 py-2 rounded-md border border-border bg-surface text-[13px]"
                placeholder="A short hook line, brand context, or scene description. Templates differ — empty = use the template's defaults."
              />
            </div>
            <div className="flex items-center gap-4 flex-wrap">
              <label className="text-[12.5px] text-ink-muted">Variants <span className="font-bold text-ink">{count}</span></label>
              <input type="range" min={1} max={3} value={count}
                     onChange={(e) => setCount(Number(e.target.value))} className="flex-1 max-w-[160px]" />
              <Button onClick={generateVariants} disabled={genBusy || !templateId}>
                {genBusy ? 'Generating…' : `Generate ${count} variant${count > 1 ? 's' : ''}`}
              </Button>
            </div>
            {genError && (
              <div className="text-[12.5px] text-danger bg-danger-soft border border-danger/30 rounded-md px-3 py-2">
                <strong>Blotato error:</strong> {genError}
              </div>
            )}
            {variants.length > 0 && (
              <div className="space-y-2">
                <div className="text-[11.5px] uppercase tracking-[0.06em] font-bold text-ink-muted">Results</div>
                {variants.map((v, i) => (
                  <div key={i} className="bg-surface border border-border rounded-md px-3 py-2 text-[12.5px]">
                    <div className="flex items-center gap-2 mb-1">
                      <Pill tone={v.status === 'succeeded' || v.status === 'completed' ? 'success' : v.status === 'error' ? 'danger' : 'warning'}>{v.status || 'unknown'}</Pill>
                      {v.visual_id && <span className="mono text-ink-muted">{v.visual_id}</span>}
                    </div>
                    {v.error && <div className="text-danger">{v.error}</div>}
                    {v.result && (
                      <pre className="text-[11px] font-mono text-ink-muted whitespace-pre-wrap leading-tight max-h-32 overflow-auto">{JSON.stringify(v.result, null, 2)}</pre>
                    )}
                  </div>
                ))}
                <div className="text-[11.5px] text-ink-muted">
                  Re-score any variant by saving its asset URL and uploading it via <a href="/new" className="underline">New analysis</a>.
                </div>
              </div>
            )}
          </div>
        )}

        {tab === 'extract' && (
          <div className="p-5 space-y-4">
            <div>
              <label className="block text-[11.5px] uppercase tracking-[0.06em] font-bold text-ink-muted mb-1">Competitor ad or landing page URL</label>
              <input
                value={url} onChange={(e) => setUrl(e.target.value)}
                placeholder="https://…"
                className="w-full px-3 py-2 rounded-md border border-border bg-surface text-[13px]"
              />
            </div>
            <div className="flex justify-end">
              <Button onClick={extractSource} disabled={extractBusy || !url.trim()}>
                {extractBusy ? 'Extracting…' : 'Extract'}
              </Button>
            </div>
            {extractError && (
              <div className="text-[12.5px] text-danger bg-danger-soft border border-danger/30 rounded-md px-3 py-2">
                <strong>Blotato error:</strong> {extractError}
              </div>
            )}
            {extracted && (
              <div className="bg-surface border border-border rounded-md px-3 py-2 text-[12.5px]">
                <div className="flex items-center gap-2 mb-1">
                  <Pill tone={extracted.status === 'succeeded' || extracted.status === 'completed' ? 'success' : 'warning'}>{extracted.status || 'unknown'}</Pill>
                  {extracted.source_id && <span className="mono text-ink-muted">{extracted.source_id}</span>}
                </div>
                {extracted.error && <div className="text-danger">{extracted.error}</div>}
                {extracted.result && (
                  <pre className="text-[11px] font-mono text-ink-muted whitespace-pre-wrap leading-tight max-h-64 overflow-auto">{JSON.stringify(extracted.result, null, 2)}</pre>
                )}
                <div className="text-[11.5px] text-ink-muted mt-2">
                  Take any media URL above to <a href="/new" className="underline">New analysis</a> to score it through AdProof.
                </div>
              </div>
            )}
          </div>
        )}

        <div className="px-5 py-3 text-[11.5px] text-ink-muted border-t border-violet/20 bg-bg-deep">
          <strong>Cost note:</strong> Each generation / extraction consumes Blotato credits. Variants are capped at 3 per click; extraction is one call per URL. Disable globally by clearing <span className="mono">BLOTATO_API_KEY</span> on the backend.
        </div>
      </Card>
    </>
  );
}
