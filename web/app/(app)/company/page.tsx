'use client';
import { useState } from 'react';
import clsx from 'clsx';
import { Button } from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/lib/api';
import { useApp } from '@/lib/store';
import { WorkspaceTeam } from '@/components/WorkspaceTeam';
import type { CompanyProfile, CompanyIntel, SmartAudience } from '@/lib/types';

const CURRENCIES = ['GBP', 'USD', 'EUR', 'CAD', 'AUD'];
const MARKETS = ['UK', 'US', 'EU', 'Canada', 'Australia', 'Global'];

// The form below copies profile fields into local state ONCE at mount — so a
// workspace switch must remount it, or the previous company's values linger
// in the inputs (the "MTC data showing on FCC" bug). Keying by workspace id
// forces a clean remount with the new workspace's data.
export default function CompanyPage() {
  const currentCompanyId = useApp((s) => s.currentCompanyId);
  return <CompanyPageInner key={currentCompanyId ?? 'none'} />;
}

function CompanyPageInner() {
  const desc = useApp((s) => s.companyDescription);
  const profile = useApp((s) => s.companyProfile);
  const setDesc = useApp((s) => s.setCompanyDescription);
  const setProfile = useApp((s) => s.setCompanyProfile);
  const savedAudiences = useApp((s) => s.savedAudiences);
  const addAudience = useApp((s) => s.addAudience);
  const deleteWorkspace = useApp((s) => s.deleteWorkspace);

  const [text, setText] = useState(desc);
  const [parsing, setParsing] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // Economics + market fields (local mirror of the profile's optional fields).
  const [website, setWebsite] = useState(profile?.website ?? '');
  const [location, setLocation] = useState(profile?.location ?? 'UK');
  const [currency, setCurrency] = useState(profile?.currency ?? 'GBP');
  const [aov, setAov] = useState<string>(profile?.avg_order_value != null ? String(profile.avg_order_value) : '');
  const [price, setPrice] = useState<string>(profile?.product_price != null ? String(profile.product_price) : '');
  // Onboarding-overhaul fields — also editable here.
  const [goal, setGoal] = useState<NonNullable<CompanyProfile['conversion_goal']> | ''>(profile?.conversion_goal ?? '');
  const [salesCycle, setSalesCycle] = useState<NonNullable<CompanyProfile['sales_cycle']> | ''>(profile?.sales_cycle ?? '');
  const [usps, setUsps] = useState<string[]>(profile?.usps ?? []);
  const [brandColor, setBrandColor] = useState<string>(profile?.brand_color ?? '#FF5A4D');
  function toggleUsp(u: string) {
    setUsps((cur) => cur.includes(u) ? cur.filter((x) => x !== u) : cur.length >= 3 ? cur : [...cur, u]);
  }
  function saveBrandGoals() {
    persist({
      conversion_goal: goal || undefined, sales_cycle: salesCycle || undefined,
      usps: usps.length ? usps : undefined, brand_color: brandColor || undefined,
    });
  }
  const GOAL_OPTIONS: { v: NonNullable<CompanyProfile['conversion_goal']>; label: string }[] = [
    { v: 'purchase', label: '🛒 Sales' }, { v: 'lead', label: '✉️ Leads' },
    { v: 'demo', label: '📅 Demo / Call' }, { v: 'signup', label: '✨ Sign-up' },
    { v: 'awareness', label: '👁 Awareness' },
  ];
  const CYCLE_OPTIONS: { v: NonNullable<CompanyProfile['sales_cycle']>; label: string }[] = [
    { v: 'impulse', label: 'Impulse' }, { v: 'considered', label: 'Considered' },
    { v: 'long', label: 'Long' }, { v: 'enterprise', label: 'Enterprise' },
  ];
  const USP_OPTIONS = [
    'Quality', 'Speed', 'Price', 'Expertise', 'Customer service', 'Local',
    'Trust / reputation', 'Personalisation', 'Sustainability', 'Innovation',
    'Convenience', 'Selection',
  ];

  const [researching, setResearching] = useState(false);
  const [researchMsg, setResearchMsg] = useState<string | null>(null);
  const [researchSources, setResearchSources] = useState<{ title: string; uri: string }[]>([]);

  // Inline editing of the AI-parsed fields. The AI proposes; you correct; your
  // correction is final. Snapshot the profile when editing STARTS (not at
  // mount) so an async profile load can't leave the form stale.
  const [editing, setEditing] = useState(false);
  const [edit, setEdit] = useState<Record<string, string>>({});
  function startEditing() {
    setEdit({
      company_name: profile?.company_name ?? '',
      industry: profile?.industry ?? '',
      business_model: profile?.business_model ?? 'b2c',
      product_category: profile?.product_category ?? '',
      price_position: profile?.price_position ?? 'mid',
      brand_tone: profile?.brand_tone ?? '',
      value_proposition: profile?.value_proposition ?? '',
    });
    setEditing(true);
  }
  function saveDetails() {
    persist({
      company_name: edit.company_name.trim(),
      industry: edit.industry.trim(),
      business_model: edit.business_model,
      product_category: edit.product_category.trim(),
      price_position: edit.price_position,
      brand_tone: edit.brand_tone.trim(),
      value_proposition: edit.value_proposition.trim(),
    });
    setEditing(false);
  }
  const eField = (k: string) => ({
    value: edit[k] ?? '',
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setEdit((cur) => ({ ...cur, [k]: e.target.value })),
  });

  function persist(patch: Partial<CompanyProfile>) {
    const base: CompanyProfile = profile ?? {
      raw_description: text, company_name: '', industry: '', business_model: 'b2c',
      product_category: 'general', value_proposition: '', target_customer_summary: '',
      price_position: 'mid', brand_tone: 'neutral', source: 'heuristic',
    };
    setProfile({ ...base, ...patch });
    setSavedAt(Date.now());
  }

  async function reparse() {
    setParsing(true);
    try {
      const p = await api.parseCompany(text);
      // Preserve the economics fields the user already set.
      setProfile({ ...p, website, location, currency,
        avg_order_value: aov ? Number(aov) : undefined,
        product_price: price ? Number(price) : undefined });
      setDesc(text);
      setSavedAt(Date.now());
    } finally { setParsing(false); }
  }

  // Deep one-shot intake: /api/company-intel fetches their actual homepage
  // (brand color, logo, copy) + web-researches economics with competitor
  // prices + proposes smart audiences on the simulator's real taxonomy.
  const [intel, setIntel] = useState<CompanyIntel | null>(null);
  const [audiencesSaved, setAudiencesSaved] = useState(false);

  async function analyzeWebsite() {
    setResearching(true); setResearchMsg(null); setResearchSources([]);
    setIntel(null); setAudiencesSaved(false);
    try {
      const r = await api.companyIntel({
        url: website.trim() || undefined,
        description: text.trim() || undefined,
        geo: location,
      });
      setIntel(r);
      const eco = r.economics || {};
      const p = r.profile || {};
      // Pre-fill economics — user confirms/edits. Never silently authoritative.
      if (eco.estimated_avg_order_value != null) setAov(String(eco.estimated_avg_order_value));
      if (eco.currency) setCurrency(eco.currency);
      if (eco.location) setLocation(eco.location);
      if (r.brand?.brand_color_hex) setBrandColor(r.brand.brand_color_hex);
      // Merge researched profile fields onto the workspace profile (only
      // non-empty values, so a thin research result never wipes real data).
      const patch: Partial<CompanyProfile> = {};
      for (const k of ['company_name', 'industry', 'business_model', 'product_category',
        'value_proposition', 'target_customer_summary', 'price_position', 'brand_tone'] as const) {
        const v = (p as Record<string, unknown>)[k];
        if (typeof v === 'string' && v.trim()) (patch as Record<string, unknown>)[k] = v.trim();
      }
      if (eco.estimated_avg_order_value != null) patch.avg_order_value = eco.estimated_avg_order_value;
      if (eco.currency) patch.currency = eco.currency;
      if (eco.location) patch.location = eco.location;
      if (r.brand?.brand_color_hex) patch.brand_color = r.brand.brand_color_hex;
      if (website.trim()) patch.website = website.trim();
      if (Object.keys(patch).length) persist(patch);

      setResearchSources(r.sources || []);
      const comp = (eco.competitor_context || [])
        .map((c) => `${c.name} (${c.price_note})`).join(', ');
      setResearchMsg(
        `${eco.confidence ? eco.confidence.toUpperCase() + ' confidence — ' : ''}` +
        `${eco.reasoning || 'Estimated from public data.'}` +
        `${comp ? ` Competitor prices: ${comp}.` : ''}` +
        `${eco.price_range_low != null && eco.price_range_high != null
          ? ` Typical market range: ${eco.currency || currency} ${eco.price_range_low}–${eco.price_range_high}.` : ''}` +
        ` Confirm or correct below — your figures drive the forecast, not ours.`,
      );
    } catch (e) {
      setResearchMsg(`Couldn't auto-research: ${(e as Error).message}. Enter your numbers manually below.`);
    } finally { setResearching(false); }
  }

  function saveSmartAudiences() {
    if (!intel?.audiences?.length) return;
    const existing = new Set(savedAudiences.map((a) => a.name));
    for (const a of intel.audiences) {
      const name = `✨ ${a.name}`;
      if (existing.has(name)) continue;
      addAudience({
        id: (typeof crypto !== 'undefined' && crypto.randomUUID)
          ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        name,
        description: a.description,
        segment: a.segment,
        createdAt: Date.now(),
        usedInCount: 0,
      });
    }
    setAudiencesSaved(true);
  }

  function saveEconomics() {
    persist({
      website: website.trim(),
      location, currency,
      avg_order_value: aov ? Number(aov) : undefined,
      product_price: price ? Number(price) : undefined,
    });
  }

  return (
    <>
      <div className="display-italic text-[38px] leading-[1.05]">
        Your <span className="gradient-text">company profile</span>
      </div>
      <p className="text-ink-muted mt-1.5 text-[14.5px] mb-6">
        This drives every analysis — your category, the audiences we suggest, the market we score for, and the economics that make the forecast real instead of synthetic.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-7">
        <div className="space-y-5">
          <Card>
            <CardTitle>What you do</CardTitle>
            <textarea
              className="input min-h-[160px]"
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
            <CardTitle>Economics &amp; market</CardTitle>
            <p className="text-[13px] text-ink-muted mb-4">
              The single biggest driver of forecast accuracy. A £5 product and a £5,000 course need wildly different math — so we use <strong>your</strong> real numbers, not a guess. Paste your site and let the AI propose figures, then correct them.
            </p>

            <div className="space-y-3.5">
              <div>
                <label className="label">Website</label>
                <div className="flex gap-2">
                  <input
                    className="input flex-1 font-mono text-[13px]"
                    value={website}
                    onChange={(e) => setWebsite(e.target.value)}
                    placeholder="https://yourcompany.com"
                  />
                  <Button variant="secondary" onClick={analyzeWebsite} disabled={researching || (!website.trim() && text.trim().length < 10)}>
                    {researching ? 'Researching…' : '✨ Analyze'}
                  </Button>
                </div>
                <div className="help">AI reads your site/description and proposes economics for you to confirm.</div>
              </div>

              {researchMsg && (
                <div className="text-[12.5px] bg-violet-soft border border-violet/30 rounded-md p-3 text-ink leading-snug">
                  <strong className="text-violet">AI estimate:</strong> {researchMsg}
                  {researchSources.length > 0 && (
                    <div className="mt-1.5 text-ink-muted">
                      Sources: {researchSources.map((s, i) => (
                        <span key={i}>{i > 0 ? ' · ' : ''}<a className="underline" href={s.uri} target="_blank" rel="noreferrer">{s.title || 'link'}</a></span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* SMART AUDIENCES — researched, mapped to the simulator's real
                  taxonomy, saved per workspace so the wizard can use them. */}
              {intel && intel.audiences.length > 0 && (
                <div className="border border-coral/30 bg-coral-soft/40 rounded-md p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <div className="font-heading text-[14px] font-bold">✨ Smart audiences for you</div>
                    <Pill tone="coral">{intel.audiences.length} researched</Pill>
                  </div>
                  <p className="text-[12px] text-ink-muted mb-3">
                    Built from what your business actually sells and who buys it — each maps to a real
                    simulator segment, so picking one genuinely changes the forecast.
                  </p>
                  <div className="space-y-2.5">
                    {intel.audiences.map((a: SmartAudience, i: number) => (
                      <div key={i} className="bg-surface border border-border rounded-md p-3">
                        <div className="flex items-center gap-2 flex-wrap">
                          <strong className="text-[13.5px]">{a.name}</strong>
                          <Pill tone="violet">{a.segment.replace(/_/g, ' ')}</Pill>
                          {a.age_range && <Pill tone="muted">{a.age_range}</Pill>}
                          {a.gender !== 'all' && <Pill tone="muted">{a.gender}</Pill>}
                          {a.interests.map((it) => <Pill key={it} tone="lime">{it}</Pill>)}
                        </div>
                        <div className="text-[12.5px] text-ink mt-1">{a.description}</div>
                        {a.rationale && <div className="text-[11.5px] text-ink-muted mt-0.5">{a.rationale}</div>}
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 flex items-center gap-3">
                    <Button size="sm" onClick={saveSmartAudiences} disabled={audiencesSaved}>
                      {audiencesSaved ? '✓ Saved to your audiences' : 'Save all to my audiences'}
                    </Button>
                    <span className="text-[11.5px] text-ink-muted">
                      They&apos;ll appear in the New-analysis wizard under saved audiences.
                    </span>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Primary market</label>
                  <select className="input" value={location} onChange={(e) => setLocation(e.target.value)}>
                    {MARKETS.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Currency</label>
                  <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                    {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Avg order / customer value</label>
                  <input
                    className="input font-mono"
                    type="number" min="0" inputMode="decimal"
                    value={aov}
                    onChange={(e) => setAov(e.target.value)}
                    placeholder="e.g. 250"
                  />
                  <div className="help">What one converted customer is worth ({currency}).</div>
                </div>
                <div>
                  <label className="label">Product price <span className="text-ink-faint font-normal">(optional)</span></label>
                  <input
                    className="input font-mono"
                    type="number" min="0" inputMode="decimal"
                    value={price}
                    onChange={(e) => setPrice(e.target.value)}
                    placeholder="e.g. 250"
                  />
                  <div className="help">Sticker price, if different from AOV.</div>
                </div>
              </div>

              <Button onClick={saveEconomics} disabled={!aov}>Save economics</Button>
            </div>
          </Card>

          <Card>
            <CardTitle>Brand & goals</CardTitle>
            <p className="text-ink-muted text-[13.5px] -mt-2 mb-4">
              Four quick picks. Each one actually changes the forecast.
            </p>
            <div className="space-y-5">
              <div>
                <div className="flex items-baseline gap-2 mb-2">
                  <label className="label !mb-0">Main goal</label>
                  <span className="text-[11.5px] text-ink-faint">sets the default conversion rate</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {GOAL_OPTIONS.map((o) => (
                    <button key={o.v} type="button" onClick={() => setGoal(o.v)}
                      className={clsx('px-3 py-1.5 rounded-full text-[13px] border transition-colors',
                        goal === o.v ? 'bg-ink text-white border-ink' : 'bg-surface border-border hover:border-coral')}>
                      {o.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <div className="flex items-baseline gap-2 mb-2">
                  <label className="label !mb-0">Sales cycle</label>
                  <span className="text-[11.5px] text-ink-faint">drives expected conversion + retention</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {CYCLE_OPTIONS.map((o) => (
                    <button key={o.v} type="button" onClick={() => setSalesCycle(o.v)}
                      className={clsx('px-3 py-1.5 rounded-full text-[13px] border transition-colors',
                        salesCycle === o.v ? 'bg-ink text-white border-ink' : 'bg-surface border-border hover:border-coral')}>
                      {o.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <div className="flex items-baseline gap-2 mb-2">
                  <label className="label !mb-0">Top 3 things you&apos;re known for</label>
                  <span className="text-[11.5px] text-ink-faint">{usps.length}/3 — informs copy + brand-fit</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {USP_OPTIONS.map((u) => {
                    const sel = usps.includes(u); const cap = usps.length >= 3 && !sel;
                    return (
                      <button key={u} type="button" onClick={() => toggleUsp(u)} disabled={cap}
                        className={clsx('px-3 py-1.5 rounded-full text-[13px] border transition-colors',
                          sel ? 'bg-ink text-white border-ink' : 'bg-surface border-border hover:border-coral',
                          cap && 'opacity-40 cursor-not-allowed')}>
                        {u}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <div className="flex items-baseline gap-2 mb-2">
                  <label className="label !mb-0">Brand colour</label>
                  <span className="text-[11.5px] text-ink-faint">used in &quot;is this on-brand?&quot; checks</span>
                </div>
                <div className="flex items-center gap-3">
                  <input type="color" value={brandColor} onChange={(e) => setBrandColor(e.target.value)}
                    className="w-12 h-12 rounded-md border border-border cursor-pointer" />
                  <input type="text" value={brandColor} onChange={(e) => setBrandColor(e.target.value)}
                    className="input font-mono w-32" maxLength={7} />
                </div>
              </div>

              <Button onClick={saveBrandGoals}>Save brand & goals</Button>
            </div>
          </Card>
        </div>

        <div className="space-y-5 self-start">
        <Card>
          <div className="flex items-center justify-between">
            <CardTitle>Parsed profile</CardTitle>
            {profile && !editing && (
              <button type="button" onClick={startEditing}
                className="text-[12px] text-violet underline -mt-2">Edit details</button>
            )}
          </div>
          {profile && editing ? (
            <div className="space-y-2.5 text-[13px]">
              <div>
                <label className="label">Name</label>
                <input className="input" {...eField('company_name')} />
              </div>
              <div>
                <label className="label">Industry</label>
                <input className="input" {...eField('industry')} placeholder="e.g. apparel e-commerce" />
              </div>
              <div className="grid grid-cols-2 gap-2.5">
                <div>
                  <label className="label">Business model</label>
                  <select className="input" {...eField('business_model')}>
                    {['b2c', 'b2b', 'dtc', 'marketplace', 'saas'].map((m) => (
                      <option key={m} value={m}>{m.toUpperCase()}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">Price position</label>
                  <select className="input" {...eField('price_position')}>
                    {['budget', 'mid', 'premium', 'luxury'].map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="label">Category</label>
                <input className="input" {...eField('product_category')} placeholder="e.g. apparel" />
              </div>
              <div>
                <label className="label">Brand tone</label>
                <input className="input" {...eField('brand_tone')} placeholder="e.g. bold, playful" />
              </div>
              <div>
                <label className="label">Value proposition</label>
                <textarea className="input min-h-[70px]" rows={3} {...eField('value_proposition')} />
              </div>
              <div className="flex gap-2 pt-1">
                <Button size="sm" onClick={saveDetails}>Save details</Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
              </div>
            </div>
          ) : profile ? (
            <div className="space-y-2 text-[13.5px]">
              <div><strong>Name:</strong> {profile.company_name || '—'}</div>
              <div><strong>Industry:</strong> {profile.industry || '—'}</div>
              <div><strong>Business model:</strong> <Pill tone="coral">{profile.business_model.toUpperCase()}</Pill></div>
              <div><strong>Category:</strong> {profile.product_category}</div>
              <div><strong>Price position:</strong> {profile.price_position}</div>
              <div><strong>Brand tone:</strong> {profile.brand_tone}</div>
              <div className="pt-2 mt-1 border-t border-border-soft" />
              <div><strong>Market:</strong> {profile.location || location}</div>
              <div><strong>Avg order value:</strong> {profile.avg_order_value != null ? `${profile.currency || currency} ${profile.avg_order_value.toLocaleString()}` : <span className="text-warning">not set — forecast will estimate</span>}</div>
              {profile.value_proposition && <div className="pt-2 border-t border-border-soft mt-2"><strong>Value prop:</strong> {profile.value_proposition}</div>}
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

        <WorkspaceTeam workspaceId={profile?.id} isOwner={!profile?.shared} />

        {/* DANGER ZONE — delete this workspace outright. Owner-only (RLS
            enforces it; the UI hides it for shared members). Cascades take
            campaigns, audiences, synced results and connections with it. */}
        {profile?.id && !profile.shared && (
          <Card className="!border-danger/40">
            <CardTitle>Danger zone</CardTitle>
            <p className="text-[13px] text-ink-muted -mt-1 mb-3">
              Deleting this workspace permanently removes its campaigns, audiences,
              synced results and platform connections. This cannot be undone.
            </p>
            <Button
              variant="ghost"
              className="!text-danger"
              onClick={async () => {
                const name = profile.company_name || 'this workspace';
                const typed = window.prompt(
                  `This permanently deletes "${name}" and ALL its data.\n\nType DELETE to confirm:`);
                if (typed !== 'DELETE') return;
                try {
                  await deleteWorkspace(profile.id!);
                  window.location.href = '/dashboard';
                } catch (e) {
                  window.alert((e as Error).message);
                }
              }}
            >
              Delete this workspace…
            </Button>
          </Card>
        )}
        </div>
      </div>
    </>
  );
}
