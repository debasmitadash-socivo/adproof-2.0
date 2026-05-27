'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { Pill } from './ui/Pill';

interface HealthStatus {
  llm: boolean;
  anthropic: boolean;
  openai: boolean;
  gemini: boolean;
  groq: boolean;
  mistral: boolean;
  openrouter: boolean;
  xai: boolean;
  together: boolean;
}

// Display priority — first connected provider becomes the visible label.
const PRIORITY: Array<[keyof HealthStatus, string]> = [
  ['anthropic',  'Claude'],
  ['openai',     'GPT-4o'],
  ['gemini',     'Gemini'],
  ['groq',       'Groq'],
  ['mistral',    'Mistral'],
  ['openrouter', 'OpenRouter'],
  ['xai',        'Grok'],
  ['together',   'Together'],
];

export function Topbar() {
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const h = (await api.health()) as HealthStatus;
        if (!cancelled) setHealth(h);
      } catch {/* ignore */}
    }
    load();
    const onFocus = () => load();
    window.addEventListener('focus', onFocus);
    return () => { cancelled = true; window.removeEventListener('focus', onFocus); };
  }, []);

  const llmAvailable = !!health?.llm;
  const primary = health
    ? PRIORITY.find(([k]) => health[k])?.[1] ?? null
    : null;
  const connectedCount = health
    ? PRIORITY.filter(([k]) => health[k]).length
    : 0;

  const label = !llmAvailable ? 'Heuristic mode'
    : connectedCount === 1 ? `${primary} ready`
    : `${primary} + ${connectedCount - 1} fallback${connectedCount > 2 ? 's' : ''}`;
  const title = !llmAvailable
    ? 'No LLM key configured — running on heuristics. Click to connect a key.'
    : `Active: ${primary}. ${connectedCount} provider${connectedCount === 1 ? '' : 's'} in fallback chain.`;

  return (
    <header className="bg-bg border-b border-border px-8 py-3.5 flex items-center gap-4">
      <div className="flex items-center gap-2 bg-surface border border-border px-3.5 py-2 rounded-full w-[380px] text-[13.5px] text-ink-muted cursor-text hover:border-coral transition-colors">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <span>Search campaigns, creatives, audiences…</span>
        <span className="ml-auto px-1.5 py-px text-[11px] font-mono text-ink-faint border border-border rounded bg-bg-deep">⌘K</span>
      </div>
      <div className="ml-auto flex items-center gap-2.5">
        <Link href="/settings" title={title}>
          <Pill tone={llmAvailable ? 'success' : 'muted'} dot>
            {label}
          </Pill>
        </Link>
      </div>
    </header>
  );
}
