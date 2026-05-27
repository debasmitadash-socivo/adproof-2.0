'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import clsx from 'clsx';
import { Button } from '@/components/ui/Button';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/lib/api';
import { useApp } from '@/lib/store';
import type { CompanyProfile } from '@/lib/types';

export default function OnboardingPage() {
  const router = useRouter();
  const hydrated = useApp((s) => s.hydrated);
  const setUser = useApp((s) => s.setUser);
  const setCompanyDescription = useApp((s) => s.setCompanyDescription);
  const setCompanyProfile = useApp((s) => s.setCompanyProfile);

  const [step, setStep] = useState<1 | 2>(1);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [desc, setDesc] = useState('');
  const [profile, setProfile] = useState<CompanyProfile | null>(null);
  const [parsing, setParsing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Skip onboarding if it's already been completed.
  useEffect(() => {
    if (!hydrated) return;
    const u = useApp.getState().user;
    const p = useApp.getState().companyProfile;
    if (u && p) router.replace('/dashboard');
  }, [hydrated, router]);

  async function parse() {
    if (desc.trim().length < 10) return;
    setParsing(true); setErr(null);
    try {
      setProfile(await api.parseCompany(desc));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setParsing(false);
    }
  }

  function finish() {
    if (!name.trim() || !profile) return;
    setUser({
      name: name.trim(),
      email: email.trim() || `${name.trim().toLowerCase().replace(/\s+/g, '.')}@local`,
      createdAt: Date.now(),
    });
    setCompanyDescription(desc);
    setCompanyProfile(profile);
    router.push('/dashboard');
  }

  if (!hydrated) return null;

  return (
    <div className="min-h-screen flex flex-col bg-bg">
      {/* topbar */}
      <header className="bg-bg border-b border-border px-9 py-4 flex items-center gap-4">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-[9px] bg-gradient-sunset text-white font-display italic font-bold flex items-center justify-center shadow-glow">A</div>
          <div className="font-heading font-bold text-[18px]">AdProof</div>
        </div>
        <div className="flex gap-1.5 ml-7">
          {(['You', 'Company'] as const).map((label, i) => {
            const n = i + 1;
            return n === step
              ? <span key={label} className="px-3.5 py-1.5 rounded-full bg-gradient-sunset text-white text-[12.5px] font-semibold shadow-glow">{n} · {label}</span>
              : n < step
                ? <Pill key={label} tone="success">✓ {label}</Pill>
                : <Pill key={label} tone="muted">{n} · {label}</Pill>;
          })}
        </div>
      </header>

      {/* body */}
      <div className="flex-1 flex justify-center items-start py-14 px-6 relative overflow-hidden">
        <div className="absolute -left-40 -top-48 w-[600px] h-[600px] rounded-full pointer-events-none" style={{ background: 'radial-gradient(circle, rgba(255,94,26,0.16), transparent 65%)' }} />
        <div className="absolute -right-48 -bottom-48 w-[500px] h-[500px] rounded-full pointer-events-none" style={{ background: 'radial-gradient(circle, rgba(124,58,237,0.18), transparent 65%)' }} />

        <div className="relative z-10 w-full max-w-[760px] bg-surface border border-border rounded-lg p-11 shadow-lift">

          {step === 1 && (
            <>
              <div className="text-[11.5px] text-coral font-bold uppercase tracking-[0.14em]">Step 1 of 2</div>
              <h1 className="display-italic text-[44px] mt-2.5 mb-3 leading-[1.05]">
                Let&apos;s set up <span className="gradient-text">your account.</span>
              </h1>
              <p className="text-ink-muted text-[15px] mb-7 leading-relaxed">
                Just your name and an email — auth is intentionally lightweight for v1, but your work persists locally between sessions.
              </p>
              <div className="space-y-4">
                <div>
                  <label className="label">Your name</label>
                  <input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Jane Doe" />
                </div>
                <div>
                  <label className="label">Email <span className="text-ink-muted font-normal">· optional</span></label>
                  <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
                </div>
              </div>
              <div className="flex justify-end mt-8 pt-5 border-t border-border-soft">
                <Button onClick={() => setStep(2)} disabled={!name.trim()}>Continue → describe your company</Button>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <div className="text-[11.5px] text-coral font-bold uppercase tracking-[0.14em]">Step 2 of 2</div>
              <h1 className="display-italic text-[44px] mt-2.5 mb-3 leading-[1.05]">
                Tell us about <span className="gradient-text">your company.</span>
              </h1>
              <p className="text-ink-muted text-[15px] mb-7 leading-relaxed">
                A few sentences is enough. We&apos;ll parse it into a structured profile that powers every campaign analysis — edit it later from Company profile.
              </p>

              <div className="mb-4">
                <label className="label">Company description</label>
                <textarea
                  className="input min-h-[140px]"
                  rows={5}
                  value={desc}
                  onChange={(e) => setDesc(e.target.value)}
                  placeholder="What does your company do? Who buys from you? What's your price position? e.g. 'Acme is a B2B SaaS for HR teams managing distributed payroll across 5+ countries…'"
                />
                <div className="help mt-2">Tip: include who buys, what they pay, and what makes you different.</div>
              </div>

              <Button variant="secondary" size="sm" onClick={parse} disabled={parsing || desc.trim().length < 10}>
                {parsing ? 'Parsing…' : '✨ Understand my company'}
              </Button>

              {err && <div className="mt-4 text-[13px] text-danger bg-danger-soft border border-danger/30 rounded-md p-3">{err}</div>}

              {profile && (
                <div className="mt-5 bg-gradient-to-br from-coral-soft to-magenta-soft border border-coral/30 rounded-md p-5 relative overflow-hidden">
                  <div className="text-[11.5px] text-coral font-bold uppercase tracking-[0.08em] mb-3 flex items-center gap-2">
                    AI-parsed profile
                    <Pill tone="coral">{profile.source === 'llm' ? '✨ Claude' : 'heuristic'}</Pill>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-[13.5px]">
                    <span><strong className="mr-1.5">Name</strong>{profile.company_name || '—'}</span>
                    <span><strong className="mr-1.5">Industry</strong>{profile.industry || '—'}</span>
                    <span><strong className="mr-1.5">Model</strong>{profile.business_model.toUpperCase()}</span>
                    <span><strong className="mr-1.5">Category</strong>{profile.product_category}</span>
                    <span><strong className="mr-1.5">Price tier</strong>{profile.price_position}</span>
                    <span><strong className="mr-1.5">Tone</strong>{profile.brand_tone}</span>
                    {profile.value_proposition && (
                      <span className="sm:col-span-2"><strong className="mr-1.5">Value prop</strong>{profile.value_proposition}</span>
                    )}
                  </div>
                </div>
              )}

              <div className="flex justify-between mt-8 pt-5 border-t border-border-soft">
                <Button variant="ghost" onClick={() => setStep(1)}>← Back</Button>
                <Button onClick={finish} disabled={!profile}>Finish &amp; go to dashboard →</Button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
