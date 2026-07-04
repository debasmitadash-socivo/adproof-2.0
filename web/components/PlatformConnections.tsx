'use client';
// Multi-platform ad-account connections. Renders one connect card per
// provider straight from the backend registry (/api/connections/providers),
// so adding a platform server-side needs no frontend change.
//
// Per provider: credential fields → "Connect & verify" (read-only test call)
// → saved to the RLS-scoped platform_connections table → "Pull & calibrate"
// runs the live sync through the same ingest pipeline as CSV uploads.
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/lib/api';
import {
  listConnections, saveConnection, deleteConnection, markConnectionSynced,
} from '@/lib/db';
import type { ConnectorProvider, PlatformConnection, IngestResult } from '@/lib/types';

const PROVIDER_ICON: Record<string, string> = {
  meta: '📘', tiktok: '🎵', google: '🔍', linkedin: '💼', reddit: '👽', x: '𝕏',
};

function ago(ts: number | null): string {
  if (!ts) return 'never';
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function ProviderCard({
  provider, connection, workspaceId, onSaved, onDeleted, onResult, segment, currency,
}: {
  provider: ConnectorProvider;
  connection: PlatformConnection | null;
  workspaceId: string;
  onSaved: (c: PlatformConnection) => void;
  onDeleted: (id: string) => void;
  onResult: (r: IngestResult, provider: string) => void;
  segment: 'general' | 'b2b_saas';
  currency: string;
}) {
  const [open, setOpen] = useState(false);
  const [showHow, setShowHow] = useState(false);
  const [creds, setCreds] = useState<Record<string, string>>(connection?.credentials ?? {});
  const [busy, setBusy] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [since, setSince] = useState(() => new Date(Date.now() - 90 * 864e5).toISOString().slice(0, 10));
  const [until, setUntil] = useState(() => new Date().toISOString().slice(0, 10));

  const requiredFilled = provider.fields
    .filter((f) => !f.optional)
    .every((f) => (creds[f.key] ?? '').trim().length > 0);

  async function connectAndVerify() {
    setBusy(true); setErr(null); setMsg(null);
    const cleaned = Object.fromEntries(
      Object.entries(creds).map(([k, v]) => [k, (v ?? '').trim()]).filter(([, v]) => v),
    ) as Record<string, string>;
    try {
      // Verify first (read-only), then persist with the verified status +
      // the account name the platform reported.
      const t = await api.testConnection({ provider: provider.id, credentials: cleaned });
      const saved = await saveConnection({
        companyId: workspaceId, provider: provider.id, credentials: cleaned,
        label: t.account_name ?? null,
        accountRef: cleaned.account_id ?? cleaned.advertiser_id ?? cleaned.customer_id ?? null,
        status: 'ok', statusNote: t.detail,
      });
      onSaved(saved);
      setMsg(t.detail);
      setOpen(false);
    } catch (e) {
      const detail = (e as Error).message;
      setErr(detail);
      // Save as errored anyway so the credentials aren't lost — unless the
      // save itself is what's impossible (missing table etc.).
      try {
        const saved = await saveConnection({
          companyId: workspaceId, provider: provider.id, credentials: cleaned,
          status: 'error', statusNote: detail.slice(0, 300),
        });
        onSaved(saved);
      } catch { /* surfaced above already */ }
    } finally { setBusy(false); }
  }

  async function pull() {
    if (!connection) return;
    setSyncing(true); setErr(null); setMsg(null);
    try {
      const result = await api.syncConnection({
        provider: provider.id, credentials: connection.credentials,
        since, until, segment, currency,
      });
      await markConnectionSynced(connection.id, `Pulled ${result.report.n_rows_kept} ads (${since} → ${until})`);
      onResult(result, provider.id);
      setMsg(`Pulled ${result.report.n_rows_kept.toLocaleString()} ads — review below, then save to calibrate.`);
    } catch (e) {
      setErr((e as Error).message);
    } finally { setSyncing(false); }
  }

  async function disconnect() {
    if (!connection) return;
    setErr(null);
    try { await deleteConnection(connection.id); onDeleted(connection.id); setCreds({}); }
    catch (e) { setErr((e as Error).message); }
  }

  const connected = connection?.status === 'ok';

  return (
    <Card className="!p-4">
      <div className="flex items-center gap-2.5 flex-wrap">
        <span className="text-[18px] leading-none w-6 text-center">{PROVIDER_ICON[provider.id] ?? '🔌'}</span>
        <div className="font-heading text-[14.5px] font-bold">{provider.label}</div>
        {provider.access === 'gated' && <Pill tone="warning">approval needed</Pill>}
        {!provider.sync && <Pill tone="muted">verify only</Pill>}
        {connected && <Pill tone="success" dot>connected</Pill>}
        {connection?.status === 'error' && <Pill tone="danger" dot>error</Pill>}
        <span className="ml-auto" />
        {connection && (
          <span className="text-[11.5px] text-ink-muted">synced {ago(connection.lastSyncedAt)}</span>
        )}
        <Button variant="secondary" size="sm" onClick={() => { setOpen((v) => !v); setErr(null); setMsg(null); }}>
          {open ? 'Close' : connection ? 'Manage' : 'Connect'}
        </Button>
      </div>

      {connected && connection?.label && !open && (
        <div className="text-[12.5px] text-ink-muted mt-1.5">“{connection.label}”{connection.statusNote && !connection.label.includes('Pulled') ? '' : ''}</div>
      )}

      {open && (
        <div className="mt-3 space-y-3">
          <div className="text-[12.5px] text-ink-muted leading-snug">
            {provider.access_note} Read-only — we never change your campaigns.
            {' '}
            <button type="button" className="text-violet underline" onClick={() => setShowHow((v) => !v)}>
              {showHow ? 'Hide setup steps' : 'How do I get these?'}
            </button>
          </div>
          {showHow && (
            <ol className="list-decimal pl-5 space-y-1 text-[12.5px] text-ink bg-bg-deep rounded-md p-3">
              {provider.how_to.map((s, i) => <li key={i}>{s}</li>)}
            </ol>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {provider.fields.map((f) => (
              <div key={f.key}>
                <label className="label">
                  {f.label}{f.optional && <span className="text-ink-faint font-normal"> · optional</span>}
                </label>
                <input
                  className="input font-mono text-[12px]"
                  type={f.secret ? 'password' : 'text'}
                  autoComplete="off"
                  value={creds[f.key] ?? ''}
                  onChange={(e) => setCreds((c) => ({ ...c, [f.key]: e.target.value }))}
                  placeholder={f.placeholder}
                />
                {f.help_url && (
                  <a className="text-[11px] text-violet underline mt-0.5 inline-block"
                    href={f.help_url} target="_blank" rel="noreferrer">Where to find this →</a>
                )}
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2.5 flex-wrap">
            <Button size="sm" onClick={connectAndVerify} disabled={busy || !requiredFilled}>
              {busy ? 'Verifying…' : connection ? 'Re-verify & save' : 'Connect & verify'}
            </Button>
            {connection && (
              <button type="button" onClick={disconnect}
                className="text-[12px] text-ink-muted hover:text-danger transition-colors">
                Disconnect
              </button>
            )}
          </div>
        </div>
      )}

      {connected && provider.sync && (
        <div className="mt-3 flex items-end gap-2.5 flex-wrap">
          <div>
            <label className="label">From</label>
            <input className="input !w-auto" type="date" value={since} max={until}
              onChange={(e) => setSince(e.target.value)} />
          </div>
          <div>
            <label className="label">To</label>
            <input className="input !w-auto" type="date" value={until} min={since}
              onChange={(e) => setUntil(e.target.value)} />
          </div>
          <Button size="sm" onClick={pull} disabled={syncing}>
            {syncing ? 'Pulling…' : 'Pull & calibrate'}
          </Button>
        </div>
      )}

      {err && (
        <div className="mt-2.5 text-[12.5px] text-danger bg-danger-soft border border-danger/30 rounded-md p-2.5">{err}</div>
      )}
      {msg && !err && (
        <div className="mt-2.5 text-[12.5px] bg-lime-soft border border-lime-deep/30 rounded-md p-2.5">✓ {msg}</div>
      )}
    </Card>
  );
}

export function PlatformConnections({
  workspaceId, segment, currency, onResult,
}: {
  workspaceId?: string;
  segment: 'general' | 'b2b_saas';
  currency: string;
  onResult: (r: IngestResult, provider: string) => void;
}) {
  const [providers, setProviders] = useState<ConnectorProvider[]>([]);
  const [connections, setConnections] = useState<PlatformConnection[]>([]);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.connectionProviders()
      .then((r) => { if (alive) setProviders(r.providers); })
      .catch((e) => { if (alive) setLoadErr((e as Error).message); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!workspaceId) { setConnections([]); return; }
    let alive = true;
    listConnections(workspaceId)
      .then((c) => { if (alive) setConnections(c); })
      .catch((e) => { if (alive) setLoadErr((e as Error).message); });
    return () => { alive = false; };
  }, [workspaceId]);

  if (!workspaceId) return null;

  const ready = providers.filter((p) => p.access === 'ready');
  const gated = providers.filter((p) => p.access === 'gated');
  const byProvider = new Map(connections.map((c) => [c.provider, c]));
  const upsert = (c: PlatformConnection) =>
    setConnections((cur) => [...cur.filter((x) => x.provider !== c.provider), c]);
  const remove = (id: string) =>
    setConnections((cur) => cur.filter((x) => x.id !== id));

  return (
    <div className="mb-5">
      <div className="flex items-center gap-2 mb-1">
        <div className="font-heading text-[15px] font-bold">Connect your ad platforms</div>
        <Pill tone="violet">live pull</Pill>
      </div>
      <p className="text-[12.5px] text-ink-muted mb-3 leading-snug max-w-2xl">
        Every platform follows the same pattern Meta set: an access credential + your
        account ID. Connect once per workspace — credentials are stored privately to this
        workspace, used read-only, and every pull calibrates the forecasts to <strong>your</strong> real numbers.
      </p>
      {loadErr && (
        <div className="mb-3 text-[12.5px] text-danger bg-danger-soft border border-danger/30 rounded-md p-2.5">{loadErr}</div>
      )}
      <div className="space-y-2.5">
        {ready.map((p) => (
          <ProviderCard key={p.id} provider={p} connection={byProvider.get(p.id) ?? null}
            workspaceId={workspaceId} onSaved={upsert} onDeleted={remove}
            onResult={onResult} segment={segment} currency={currency} />
        ))}
        {gated.length > 0 && (
          <div className="text-[11px] text-ink-faint uppercase tracking-[0.1em] font-bold pt-2">
            Needs platform approval first — apply early, connect when granted
          </div>
        )}
        {gated.map((p) => (
          <ProviderCard key={p.id} provider={p} connection={byProvider.get(p.id) ?? null}
            workspaceId={workspaceId} onSaved={upsert} onDeleted={remove}
            onResult={onResult} segment={segment} currency={currency} />
        ))}
      </div>
    </div>
  );
}
