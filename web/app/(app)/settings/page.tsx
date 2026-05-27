'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/lib/api';
import { useApp } from '@/lib/store';
import { getSupabase } from '@/lib/supabase';

// Provider catalogue — one place to add a new key field. The order here
// matches the auto-fallback order in the backend: paid quality → free
// vision-capable → text-only / niche.
const PROVIDERS = [
  { id: 'gemini',     label: 'Google Gemini',  field: 'gemini_key',     env: 'GEMINI_API_KEY',     placeholder: 'AIza…',     getKeyUrl: 'https://aistudio.google.com/apikey',           free: true,  vision: true,  blurb: '5-model fallback chain. Primary.' },
  { id: 'groq',       label: 'Groq',           field: 'groq_key',       env: 'GROQ_API_KEY',       placeholder: 'gsk_…',     getKeyUrl: 'https://console.groq.com/keys',                free: true,  vision: true,  blurb: 'Llama 4 Scout vision · highest free quota.' },
  { id: 'mistral',    label: 'Mistral',        field: 'mistral_key',    env: 'MISTRAL_API_KEY',    placeholder: '',           getKeyUrl: 'https://console.mistral.ai/api-keys/',         free: true,  vision: true,  blurb: 'Pixtral-12B vision · 500k tok/min free.' },
  { id: 'openrouter', label: 'OpenRouter',     field: 'openrouter_key', env: 'OPENROUTER_API_KEY', placeholder: 'sk-or-v1-…', getKeyUrl: 'https://openrouter.ai/keys',                  free: true,  vision: true,  blurb: 'Gateway to ~50 models, has free tier.' },
  { id: 'xai',        label: 'xAI Grok',       field: 'xai_key',        env: 'XAI_API_KEY',        placeholder: 'xai-…',      getKeyUrl: 'https://console.x.ai/team/default/api-keys',   free: false, vision: true,  blurb: 'Grok-2-Vision. Paid but has free credits.' },
  { id: 'together',   label: 'Together AI',    field: 'together_key',   env: 'TOGETHER_API_KEY',   placeholder: 'tgp_v1_…',   getKeyUrl: 'https://api.together.xyz/settings/api-keys',  free: true,  vision: true,  blurb: 'Llama-Vision-Free · $1 free credit.' },
  { id: 'anthropic',  label: 'Anthropic Claude', field: 'anthropic_key', env: 'ANTHROPIC_API_KEY', placeholder: 'sk-ant-…',   getKeyUrl: 'https://console.anthropic.com/',               free: false, vision: true,  blurb: 'Paid · highest quality.' },
  { id: 'openai',     label: 'OpenAI',         field: 'openai_key',     env: 'OPENAI_API_KEY',     placeholder: 'sk-…',       getKeyUrl: 'https://platform.openai.com/api-keys',         free: false, vision: true,  blurb: 'Paid · GPT-4o vision.' },
] as const;

type ProviderId = typeof PROVIDERS[number]['id'];

export default function SettingsPage() {
  const router = useRouter();
  const user = useApp((s) => s.user);
  const setUser = useApp((s) => s.setUser);
  const reset = useApp((s) => s.resetAccount);
  const [name, setName] = useState(user?.name ?? '');
  const [email, setEmail] = useState(user?.email ?? '');
  const [confirmingReset, setConfirmingReset] = useState(false);

  // status[providerId] = true if a key is connected
  const [status, setStatus] = useState<Record<ProviderId, boolean> | null>(null);
  const [inputs, setInputs] = useState<Record<ProviderId, string>>(() =>
    Object.fromEntries(PROVIDERS.map((p) => [p.id, ''])) as Record<ProviderId, string>,
  );
  const [savingKeys, setSavingKeys] = useState(false);
  const [keysMsg, setKeysMsg] = useState<string | null>(null);

  async function refreshStatus() {
    try {
      const h = (await api.health()) as any;
      const s: Record<ProviderId, boolean> = {} as any;
      for (const p of PROVIDERS) s[p.id] = !!h[p.id];
      setStatus(s);
    } catch {/* ignore — left as null, UI shows 'checking…' */}
  }
  useEffect(() => { refreshStatus(); }, []);

  async function saveKeys() {
    setSavingKeys(true); setKeysMsg(null);
    try {
      const payload: Record<string, string> = {};
      for (const p of PROVIDERS) {
        if (inputs[p.id]) payload[p.field] = inputs[p.id];
      }
      const r = await api.setApiKeys(payload as any) as any;
      const connectedNames = PROVIDERS.filter((p) => r[p.id]).map((p) => p.label);
      setKeysMsg(`Saved & persisted to disk. Connected: ${connectedNames.join(' · ') || 'none'}.`);
      setInputs(Object.fromEntries(PROVIDERS.map((p) => [p.id, ''])) as Record<ProviderId, string>);
      refreshStatus();
    } catch (e) {
      setKeysMsg(`Failed: ${(e as Error).message}`);
    } finally {
      setSavingKeys(false);
    }
  }

  async function clearAll() {
    const empty: Record<string, string> = {};
    for (const p of PROVIDERS) empty[p.field] = '';
    await api.setApiKeys(empty as any);
    refreshStatus();
    setKeysMsg('Cleared all keys.');
  }

  async function signOut() {
    const sb = getSupabase();
    if (sb) await sb.auth.signOut();
    setUser(null);
    router.replace('/login');
  }

  const connectedCount = status ? PROVIDERS.filter((p) => status[p.id]).length : 0;

  return (
    <>
      <div className="display-italic text-[38px] leading-[1.05]">
        <span className="gradient-text">Settings</span>
      </div>
      <p className="text-ink-muted mt-1.5 text-[14.5px] mb-6">
        v1 keeps everything local. Real auth, teams, and billing land in v2.
      </p>

      {/* Profile */}
      <Card className="mb-5">
        <CardTitle>Your profile</CardTitle>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div><label className="label">Name</label><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div><label className="label">Email</label><input className="input" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        </div>
        <div className="mt-4 flex items-center gap-3 flex-wrap">
          <Button onClick={() => setUser({ name: name.trim() || 'You', email: email.trim(), createdAt: user?.createdAt ?? Date.now() })}>
            Save profile
          </Button>
          <Button variant="ghost" onClick={signOut}>
            Sign out
          </Button>
          {user?.email && (
            <span className="text-[12.5px] text-ink-muted ml-auto">
              Signed in as <code className="font-mono">{user.email}</code>
            </span>
          )}
        </div>
      </Card>

      {/* API keys */}
      <Card className="mb-5">
        <CardTitle>LLM integrations</CardTitle>
        <p className="text-[13.5px] text-ink-muted mb-3">
          Paste a key once — saved to <code className="font-mono text-[11.5px] bg-bg-deep px-1 rounded">data/.secrets.json</code> (chmod 600, gitignored) and re-loaded automatically every uvicorn start. No need to retest after restart.
        </p>
        <div className="text-[12.5px] text-ink-muted bg-lime-soft border border-lime-deep/30 rounded-md p-3 mb-4">
          <strong>How the fallback chain works:</strong> the backend tries providers in order, skipping any without a key. When one returns a 429 quota error, it falls forward to the next automatically. With 4+ providers connected, you effectively cannot run out of free quota.
        </div>

        {/* Connection summary — replaces the "Test connection" friction */}
        <div className="flex items-center gap-2 mb-4 flex-wrap">
          {PROVIDERS.map((p) => (
            <Pill key={p.id} tone={status?.[p.id] ? 'success' : 'muted'} dot>
              {p.label} · {status === null ? '…' : status[p.id] ? 'connected' : 'not set'}
            </Pill>
          ))}
          <div className="flex-1" />
          <span className="text-[12.5px] text-ink-muted">
            {status === null ? 'Checking…' : `${connectedCount}/${PROVIDERS.length} providers active`}
          </span>
        </div>

        {/* Per-provider key inputs */}
        <div className="space-y-3.5">
          {PROVIDERS.map((p) => (
            <div key={p.id} className="grid grid-cols-1 sm:grid-cols-[180px_1fr_auto] gap-3 items-center bg-bg-deep border border-border-soft rounded-md p-3">
              <div>
                <div className="font-semibold text-[14px]">{p.label}</div>
                <div className="text-[11.5px] text-ink-muted leading-tight">
                  {p.free ? <span className="text-success font-semibold">free</span> : <span className="text-warning font-semibold">paid</span>}
                  {p.vision && ' · vision'}
                </div>
                <div className="text-[11px] text-ink-muted mt-0.5">{p.blurb}</div>
              </div>
              <input
                className="input font-mono text-[12.5px]"
                type="password"
                value={inputs[p.id]}
                onChange={(e) => setInputs({ ...inputs, [p.id]: e.target.value })}
                placeholder={status?.[p.id] ? '••••••••  (key on file)' : p.placeholder || 'paste key here'}
              />
              <a href={p.getKeyUrl} target="_blank" rel="noreferrer" className="text-[12.5px] text-coral font-semibold underline whitespace-nowrap">
                Get key →
              </a>
            </div>
          ))}
        </div>

        <div className="flex gap-2 mt-5">
          <Button onClick={saveKeys} disabled={savingKeys || Object.values(inputs).every((v) => !v)}>
            {savingKeys ? 'Saving…' : 'Save keys'}
          </Button>
          <Button variant="ghost" onClick={clearAll}>Clear all keys</Button>
        </div>
        {keysMsg && <div className="mt-3 text-[13px] text-ink bg-success-soft border border-success/30 rounded-md px-3 py-2">{keysMsg}</div>}

        <div className="mt-4 p-3 rounded-md bg-warning-soft border border-warning/30 text-[12px] text-yellow-800">
          <strong>v1 note:</strong> keys are stored as plaintext JSON in <code className="font-mono text-[11px]">data/.secrets.json</code> on this machine. v2 ships per-user encrypted secret storage.
        </div>
      </Card>

      {/* Danger zone */}
      <Card className="!bg-danger-soft !border-danger/30">
        <CardTitle>Reset workspace</CardTitle>
        <p className="text-[13.5px] mb-3">Clears your profile, company, campaigns and audiences from this browser. Cannot be undone.</p>
        {!confirmingReset ? (
          <Button variant="secondary" onClick={() => setConfirmingReset(true)}>Reset everything…</Button>
        ) : (
          <div className="flex gap-2">
            <Button onClick={() => { reset(); router.push('/login'); }} className="!bg-danger !bg-none">Yes, reset</Button>
            <Button variant="ghost" onClick={() => setConfirmingReset(false)}>Cancel</Button>
          </div>
        )}
      </Card>
    </>
  );
}
