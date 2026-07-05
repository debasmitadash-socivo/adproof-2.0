'use client';
import { useEffect, useRef, useState } from 'react';
import clsx from 'clsx';
import { Button } from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { useApp } from '@/lib/store';
import { api } from '@/lib/api';
import { listConnections } from '@/lib/db';
import {
  filtersForPlatform,
  describeFilters,
  type FilterCard as FilterCardType,
} from '@/lib/filters';
import type { SavedAudience, MetaInterest, PlatformConnection } from '@/lib/types';

// "12,400,000" → "12.4M" for interest audience-size chips.
function compactCount(n: number | null | undefined): string {
  if (!n || n <= 0) return '';
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}K`;
  return String(n);
}

export default function AudiencesPage() {
  const audiences = useApp((s) => s.savedAudiences);
  const addAudience = useApp((s) => s.addAudience);
  const deleteAudience = useApp((s) => s.deleteAudience);
  const moveAudience = useApp((s) => s.moveAudience);
  const companies = useApp((s) => s.companies);
  const currentCompanyId = useApp((s) => s.currentCompanyId);
  const otherWorkspaces = companies.filter((c) => c.id && c.id !== currentCompanyId);
  const [creating, setCreating] = useState(false);

  return (
    <>
      <div className="flex items-end gap-6 mb-6">
        <div>
          <div className="display-italic text-[38px] leading-[1.05]">
            Your <span className="gradient-text">audiences</span>
          </div>
          <p className="text-ink-muted mt-1.5 text-[14.5px]">
            Save a filter set as a reusable audience. Pick from these in the wizard&apos;s Step 3.
          </p>
        </div>
        <div className="flex-1" />
        <Button onClick={() => setCreating(true)}>+ New audience</Button>
      </div>

      {audiences.length === 0 && !creating ? (
        <Card className="text-center py-14">
          <div className="text-5xl mb-3">👥</div>
          <div className="font-heading text-[17px] font-bold mb-1">No audiences yet</div>
          <p className="text-ink-muted text-[14px] max-w-md mx-auto mb-5">
            Save a set of filters — age range, interests, behaviours, B2B signals — and reuse it across analyses.
          </p>
          <Button onClick={() => setCreating(true)}>+ Create your first audience</Button>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {audiences.map((a) => (
            <AudienceCard key={a.id} audience={a} onDelete={() => deleteAudience(a.id)}
              moveTargets={otherWorkspaces.map((w) => ({ id: w.id!, name: w.company_name || 'Untitled' }))}
              onMove={(target) => moveAudience(a.id, target).catch((e) => window.alert((e as Error).message))} />
          ))}
        </div>
      )}

      {creating && (
        <CreateAudienceModal
          onClose={() => setCreating(false)}
          onSave={(audience) => { addAudience(audience); setCreating(false); }}
        />
      )}
    </>
  );
}

function AudienceCard({ audience, onDelete, moveTargets, onMove }: {
  audience: SavedAudience; onDelete: () => void;
  moveTargets: { id: string; name: string }[];
  onMove: (targetCompanyId: string) => void;
}) {
  return (
    <Card className="relative">
      <div className="flex items-start justify-between mb-2">
        <div>
          <div className="font-semibold text-[15px]">{audience.name}</div>
          <div className="text-[11.5px] text-ink-muted mt-0.5">Created {new Date(audience.createdAt).toLocaleDateString()}</div>
        </div>
        <div className="flex items-center gap-1.5">
          {moveTargets.length > 0 && (
            <select value="" title="Move this audience to another workspace"
              onChange={(e) => {
                const t = e.target.value; e.target.value = '';
                if (!t) return;
                const name = moveTargets.find((w) => w.id === t)?.name ?? 'that workspace';
                if (window.confirm(`Move "${audience.name}" to ${name}?`)) onMove(t);
              }}
              className="text-[11px] text-ink-muted bg-transparent border border-border rounded-md px-1 py-0.5 cursor-pointer max-w-[80px]">
              <option value="">Move…</option>
              {moveTargets.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          )}
          <Pill tone="coral">{audience.segment}</Pill>
        </div>
      </div>
      <div className="text-[13px] text-ink leading-snug mb-3">{audience.description || <em className="text-ink-muted">No description</em>}</div>
      <div className="flex items-center gap-2">
        <span className="text-[12.5px] text-ink-muted">Used in <strong className="text-ink">{audience.usedInCount}</strong> campaign{audience.usedInCount === 1 ? '' : 's'}</span>
        <div className="flex-1" />
        <Button size="sm" variant="ghost" onClick={onDelete}>Delete</Button>
      </div>
    </Card>
  );
}

function CreateAudienceModal({
  onClose,
  onSave,
}: {
  onClose: () => void;
  onSave: (a: SavedAudience) => void;
}) {
  const [name, setName] = useState('');
  const [platformId, setPlatformId] = useState('meta_instagram');
  const [selections, setSelections] = useState<Record<string, true>>({});

  // ---- Live Meta interest search — the same targeting options Ads Manager
  // shows, pulled straight from the connected account's Graph API token.
  const currentCompanyId = useApp((s) => s.currentCompanyId);
  const [metaConn, setMetaConn] = useState<PlatformConnection | null>(null);
  const [interestQ, setInterestQ] = useState('');
  const [interestResults, setInterestResults] = useState<MetaInterest[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchErr, setSearchErr] = useState('');
  const [picked, setPicked] = useState<MetaInterest[]>([]);
  const searchSeq = useRef(0);

  useEffect(() => {
    if (!currentCompanyId) return;
    listConnections(currentCompanyId)
      .then((conns) => setMetaConn(conns.find((c) => c.provider === 'meta' && c.status === 'ok') ?? null))
      .catch(() => setMetaConn(null));
  }, [currentCompanyId]);

  const isMetaPlatform = platformId.startsWith('meta_');

  useEffect(() => {
    const q = interestQ.trim();
    if (!metaConn || !isMetaPlatform || q.length < 2) {
      setInterestResults([]); setSearching(false); setSearchErr('');
      return;
    }
    setSearching(true); setSearchErr('');
    const seq = ++searchSeq.current;
    const t = setTimeout(() => {
      api.searchInterests({ provider: 'meta', credentials: metaConn.credentials, q })
        .then((r) => { if (seq === searchSeq.current) { setInterestResults(r.interests); setSearching(false); } })
        .catch((e) => { if (seq === searchSeq.current) { setSearchErr((e as Error).message); setSearching(false); } });
    }, 400);
    return () => clearTimeout(t);
  }, [interestQ, metaConn, isMetaPlatform]);

  function pickInterest(it: MetaInterest) {
    setPicked((prev) => prev.some((p) => p.id === it.id) ? prev : [...prev, it]);
    setInterestQ(''); setInterestResults([]);
  }

  const cards = filtersForPlatform(platformId);
  const selectedIds = Object.keys(selections);
  const baseDescription = describeFilters(selectedIds, platformId);
  const description = picked.length
    ? `${baseDescription ? `${baseDescription} ` : ''}Meta interests: ${picked.map((p) => p.name).join(', ')}.`
    : baseDescription;

  function toggle(id: string) {
    setSelections((prev) => {
      const next = { ...prev };
      if (next[id]) delete next[id]; else next[id] = true;
      return next;
    });
  }

  function save() {
    if (!name.trim()) return;
    const audience: SavedAudience = {
      id: (typeof crypto !== 'undefined' && crypto.randomUUID)
        ? crypto.randomUUID()
        : `a_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      name: name.trim(),
      description,
      segment: 'all', // matcher will pick best fit at simulate time
      createdAt: Date.now(),
      usedInCount: 0,
    };
    onSave(audience);
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-start justify-center overflow-y-auto p-6" onClick={onClose}>
      <div
        className="w-full max-w-[860px] bg-surface rounded-lg shadow-lift my-8"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-7 py-5 border-b border-border flex items-center justify-between">
          <div>
            <div className="display-italic text-[28px] leading-tight">New audience</div>
            <div className="text-[13px] text-ink-muted mt-0.5">Name it, pick a platform, choose your filters.</div>
          </div>
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </div>

        <div className="px-7 py-6 space-y-5">
          <div className="grid grid-cols-1 sm:grid-cols-[2fr_1fr] gap-4">
            <div>
              <label className="label">Name</label>
              <input className="input" placeholder="e.g. UK marketing decision-makers" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            </div>
            <div>
              <label className="label">Platform</label>
              <select className="input" value={platformId} onChange={(e) => { setPlatformId(e.target.value); setSelections({}); }}>
                <option value="meta_instagram">Meta — Instagram</option>
                <option value="meta_facebook">Meta — Facebook</option>
                <option value="linkedin">LinkedIn</option>
                <option value="google_search">Google Search</option>
                <option value="google_display">Google Display</option>
              </select>
            </div>
          </div>

          {isMetaPlatform && (
            <Card className={clsx(!metaConn && 'opacity-90')}>
              <div className="font-semibold text-[14px] mb-1 flex items-center gap-2">
                <span>🎯</span>Detailed targeting — live from Meta
                {metaConn && <Pill tone="success">connected</Pill>}
              </div>
              {metaConn ? (
                <>
                  <div className="text-[12.5px] text-ink-muted mb-3">
                    Search the exact same interest options Ads Manager offers, with real audience sizes — pulled from your connected Meta account{metaConn.label ? ` (${metaConn.label})` : ''}.
                  </div>
                  <div className="relative">
                    <input className="input" placeholder="e.g. streetwear, CrossFit, sustainable fashion…"
                      value={interestQ} onChange={(e) => setInterestQ(e.target.value)} />
                    {(searching || interestResults.length > 0 || searchErr) && interestQ.trim().length >= 2 && (
                      <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-10 bg-surface border border-border rounded-lg shadow-lift max-h-[260px] overflow-y-auto">
                        {searching && <div className="px-4 py-3 text-[13px] text-ink-muted">Searching Meta…</div>}
                        {!searching && searchErr && <div className="px-4 py-3 text-[13px] text-coral">{searchErr}</div>}
                        {!searching && !searchErr && interestResults.length === 0 && (
                          <div className="px-4 py-3 text-[13px] text-ink-muted">No matching interests.</div>
                        )}
                        {!searching && interestResults.map((it) => (
                          <button key={it.id} type="button" onClick={() => pickInterest(it)}
                            className="w-full text-left px-4 py-2.5 hover:bg-coral-soft transition-colors border-b border-border last:border-b-0">
                            <div className="flex items-baseline gap-2">
                              <span className="text-[13.5px] font-medium">{it.name}</span>
                              {it.audience_size_lower ? (
                                <span className="text-[11.5px] text-ink-muted">
                                  {compactCount(it.audience_size_lower)}–{compactCount(it.audience_size_upper)} people
                                </span>
                              ) : null}
                            </div>
                            {it.path && <div className="text-[11px] text-ink-muted mt-0.5">{it.path}</div>}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  {picked.length > 0 && (
                    <div className="flex flex-wrap gap-2 mt-3">
                      {picked.map((it) => (
                        <span key={it.id}
                          onClick={() => setPicked((prev) => prev.filter((p) => p.id !== it.id))}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-[13px] font-semibold cursor-pointer bg-coral-soft border-coral text-coral"
                          title={it.path || it.name}>
                          {it.name}
                          {it.audience_size_lower ? (
                            <span className="font-normal opacity-75">{compactCount(it.audience_size_lower)}+</span>
                          ) : null}
                          <span className="font-bold">×</span>
                        </span>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className="text-[12.5px] text-ink-muted">
                  Connect your Meta ad account on the <strong>Data</strong> page to search Meta&apos;s real interest
                  options here (with audience sizes) — until then, use the filter chips below.
                </div>
              )}
            </Card>
          )}

          <div className="space-y-3">
            {cards.map((card) => (
              <ModalFilterPanel
                key={card.id}
                card={card}
                selections={selections}
                onToggle={toggle}
              />
            ))}
          </div>

          {(selectedIds.length > 0 || picked.length > 0) && (
            <Card className="!bg-coral-soft !border-coral/30">
              <div className="text-[11.5px] text-coral font-bold uppercase tracking-[0.08em] mb-1.5">Audience description</div>
              <div className="text-[13.5px] leading-snug">{description}</div>
            </Card>
          )}
        </div>

        <div className="px-7 py-4 border-t border-border flex items-center justify-between bg-bg-deep rounded-b-lg">
          <div className="text-[12.5px] text-ink-muted">
            <strong>{selectedIds.length}</strong> filter{selectedIds.length === 1 ? '' : 's'}
            {picked.length > 0 && <> + <strong>{picked.length}</strong> Meta interest{picked.length === 1 ? '' : 's'}</>} selected
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={save} disabled={!name.trim() || (selectedIds.length === 0 && picked.length === 0)}>Save audience</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ModalFilterPanel({
  card,
  selections,
  onToggle,
}: {
  card: FilterCardType;
  selections: Record<string, true>;
  onToggle: (id: string) => void;
}) {
  return (
    <Card>
      <div className="font-semibold text-[14px] mb-3 flex items-center gap-2">
        <span>{card.glyph}</span>{card.title}
      </div>
      {card.groups.map((g) => (
        <div key={g.id} className="mb-3 last:mb-0">
          {g.title && (
            <div className="text-[11.5px] text-ink-muted font-bold uppercase tracking-[0.07em] mb-2">{g.title}</div>
          )}
          <div className="flex flex-wrap gap-2">
            {g.chips.map((ch) => {
              const on = selections[ch.id] === true;
              return (
                <span
                  key={ch.id}
                  onClick={() => onToggle(ch.id)}
                  className={clsx(
                    'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-[13px] font-medium cursor-pointer transition-colors',
                    on
                      ? 'bg-coral-soft border-coral text-coral font-semibold'
                      : 'bg-surface border-border hover:border-coral',
                  )}
                >
                  {ch.label}{on && <span className="text-coral font-bold">×</span>}
                </span>
              );
            })}
          </div>
        </div>
      ))}
    </Card>
  );
}
