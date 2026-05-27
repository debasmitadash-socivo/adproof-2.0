'use client';
import { useState } from 'react';
import clsx from 'clsx';
import { Button } from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { useApp } from '@/lib/store';
import {
  filtersForPlatform,
  describeFilters,
  type FilterCard as FilterCardType,
} from '@/lib/filters';
import type { SavedAudience } from '@/lib/types';

export default function AudiencesPage() {
  const audiences = useApp((s) => s.savedAudiences);
  const addAudience = useApp((s) => s.addAudience);
  const deleteAudience = useApp((s) => s.deleteAudience);
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
            <AudienceCard key={a.id} audience={a} onDelete={() => deleteAudience(a.id)} />
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

function AudienceCard({ audience, onDelete }: { audience: SavedAudience; onDelete: () => void }) {
  return (
    <Card className="relative">
      <div className="flex items-start justify-between mb-2">
        <div>
          <div className="font-semibold text-[15px]">{audience.name}</div>
          <div className="text-[11.5px] text-ink-muted mt-0.5">Created {new Date(audience.createdAt).toLocaleDateString()}</div>
        </div>
        <Pill tone="coral">{audience.segment}</Pill>
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

  const cards = filtersForPlatform(platformId);
  const selectedIds = Object.keys(selections);
  const description = describeFilters(selectedIds, platformId);

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
      id: `a_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
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

          {selectedIds.length > 0 && (
            <Card className="!bg-coral-soft !border-coral/30">
              <div className="text-[11.5px] text-coral font-bold uppercase tracking-[0.08em] mb-1.5">Audience description</div>
              <div className="text-[13.5px] leading-snug">{description}</div>
            </Card>
          )}
        </div>

        <div className="px-7 py-4 border-t border-border flex items-center justify-between bg-bg-deep rounded-b-lg">
          <div className="text-[12.5px] text-ink-muted">
            <strong>{selectedIds.length}</strong> filter{selectedIds.length === 1 ? '' : 's'} selected
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={save} disabled={!name.trim() || selectedIds.length === 0}>Save audience</Button>
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
