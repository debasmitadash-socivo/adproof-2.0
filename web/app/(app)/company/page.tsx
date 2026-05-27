'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/lib/api';
import { useApp } from '@/lib/store';

export default function CompanyPage() {
  const desc = useApp((s) => s.companyDescription);
  const profile = useApp((s) => s.companyProfile);
  const setDesc = useApp((s) => s.setCompanyDescription);
  const setProfile = useApp((s) => s.setCompanyProfile);
  const [text, setText] = useState(desc);
  const [parsing, setParsing] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  async function reparse() {
    setParsing(true);
    try {
      const p = await api.parseCompany(text);
      setProfile(p); setDesc(text); setSavedAt(Date.now());
    } finally { setParsing(false); }
  }

  return (
    <>
      <div className="display-italic text-[38px] leading-[1.05]">
        Your <span className="gradient-text">company profile</span>
      </div>
      <p className="text-ink-muted mt-1.5 text-[14.5px] mb-6">
        This profile drives every campaign analysis — what category we put you in, what audiences we suggest, and the tone we critique your creative against. Edit it any time.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-7">
        <Card>
          <CardTitle>Description</CardTitle>
          <textarea
            className="input min-h-[200px]"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="What does your company do? Who buys from you? What's your price position?"
          />
          <div className="flex items-center gap-3 mt-4">
            <Button onClick={reparse} disabled={parsing || text.trim().length < 10}>
              {parsing ? 'Re-parsing…' : '✨ Re-parse profile'}
            </Button>
            {savedAt && <div className="text-success text-[13px] font-semibold">Saved · {new Date(savedAt).toLocaleTimeString()}</div>}
          </div>
        </Card>

        <Card>
          <CardTitle>Parsed profile</CardTitle>
          {profile ? (
            <div className="space-y-2 text-[13.5px]">
              <div><strong>Name:</strong> {profile.company_name || '—'}</div>
              <div><strong>Industry:</strong> {profile.industry || '—'}</div>
              <div><strong>Business model:</strong> <Pill tone="coral">{profile.business_model.toUpperCase()}</Pill></div>
              <div><strong>Category:</strong> {profile.product_category}</div>
              <div><strong>Price position:</strong> {profile.price_position}</div>
              <div><strong>Brand tone:</strong> {profile.brand_tone}</div>
              {profile.value_proposition && <div><strong>Value prop:</strong> {profile.value_proposition}</div>}
              <div className="pt-2 border-t border-border-soft mt-3">
                <Pill tone={profile.source === 'llm' ? 'coral' : 'muted'}>
                  Parsed via {profile.source === 'llm' ? '✨ LLM' : 'keyword heuristic'}
                </Pill>
              </div>
            </div>
          ) : (
            <div className="text-ink-muted text-[13.5px]">No profile yet — write a description and parse it.</div>
          )}
        </Card>
      </div>
    </>
  );
}
