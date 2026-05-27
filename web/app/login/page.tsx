'use client';
import Link from 'next/link';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/Button';
import { useApp } from '@/lib/store';

export default function LoginPage() {
  const router = useRouter();
  const hydrated = useApp((s) => s.hydrated);

  // If you've already onboarded on this browser, go straight to dashboard.
  useEffect(() => {
    if (!hydrated) return;
    const { user, companyProfile } = useApp.getState();
    if (user && companyProfile) router.replace('/dashboard');
  }, [hydrated, router]);

  function signIn() { router.push('/onboarding'); }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      {/* LEFT: gradient brand pitch */}
      <div className="hidden lg:flex relative overflow-hidden bg-gradient-sunset text-white p-16 flex-col">
        <div className="absolute inset-0 mesh-overlay" />
        <div className="absolute -right-48 -bottom-48 w-[500px] h-[500px] rounded-full pointer-events-none" style={{ background: 'radial-gradient(circle, rgba(190,242,100,0.30), transparent 65%)' }} />
        <div className="relative z-10 flex flex-col h-full">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-[9px] bg-white/20 backdrop-blur-md text-white font-display italic font-bold flex items-center justify-center">A</div>
            <div className="font-heading font-bold text-[18px]">AdProof</div>
          </div>
          <h1 className="display-italic text-[72px] mt-16 mb-5 leading-[0.98]">
            Score every ad before
            <br />
            you <span className="bg-lime/45 px-1.5 rounded-md">ship it.</span>
          </h1>
          <p className="text-[17px] opacity-95 max-w-[480px] leading-relaxed">
            Upload a creative, pick your audience and platform, and get a forecast you can defend to a client — backed by real benchmarks and an agent-based audience model.
          </p>
          <ul className="mt-9 mb-auto space-y-3 text-[14.5px] opacity-95">
            {[
              'Forecast CTR, conversions, ROI and ROAS in p10–p90 bands',
              'Compare ad formats across Meta, Google, LinkedIn, TikTok',
              'Save company profiles and audience segments',
              'Iterate on creatives without burning test budget',
            ].map((line) => (
              <li key={line} className="flex gap-3 items-start">
                <span className="text-lime mt-0.5">✦</span>
                {line}
              </li>
            ))}
          </ul>
          <div className="text-[12.5px] opacity-80">
            Built for marketing teams who want to defend creative decisions with data, not gut.
          </div>
        </div>
      </div>

      {/* RIGHT: form */}
      <div className="flex items-center justify-center p-14 bg-bg">
        <div className="w-full max-w-[380px]">
          <div className="flex items-center gap-2.5 mb-9">
            <div className="w-8 h-8 rounded-[9px] bg-gradient-sunset text-white font-display italic font-bold flex items-center justify-center shadow-glow">A</div>
            <div className="font-heading font-bold text-[18px]">AdProof</div>
          </div>
          <div className="display-italic text-[44px] leading-none">
            Get <span className="gradient-text">started.</span>
          </div>
          <p className="text-ink-muted mt-3.5 mb-6 text-[14.5px]">
            v1 keeps auth lightweight — your work persists locally in this browser. Real auth lands in v2.
          </p>

          <button className="w-full flex items-center justify-center gap-2.5 py-2.5 border border-border rounded-full bg-surface text-[14px] font-medium hover:bg-coral-soft hover:border-coral transition-colors opacity-60 cursor-not-allowed">
            <svg width="18" height="18" viewBox="0 0 18 18"><path d="M17.6 9.2c0-.6-.1-1.2-.2-1.8H9v3.4h4.8c-.2 1.1-.8 2-1.8 2.6v2.2h2.9c1.7-1.5 2.7-3.8 2.7-6.4z" fill="#4285F4"/><path d="M9 18c2.4 0 4.5-.8 6-2.2l-2.9-2.2c-.8.5-1.8.9-3.1.9-2.4 0-4.4-1.6-5.2-3.8H.9v2.3C2.4 15.9 5.5 18 9 18z" fill="#34A853"/><path d="M3.8 10.7c-.2-.5-.3-1.1-.3-1.7s.1-1.2.3-1.7V5H.9C.3 6.2 0 7.6 0 9s.3 2.8.9 4l2.9-2.3z" fill="#FBBC05"/><path d="M9 3.6c1.3 0 2.5.5 3.4 1.4l2.6-2.6C13.5.9 11.4 0 9 0 5.5 0 2.4 2.1.9 5l2.9 2.3C4.6 5.1 6.6 3.6 9 3.6z" fill="#EA4335"/></svg>
            Continue with Google · v2
          </button>

          <div className="flex items-center gap-3 text-ink-muted text-[12px] my-5">
            <div className="flex-1 h-px bg-border" />
            v1 — start fresh, no password
            <div className="flex-1 h-px bg-border" />
          </div>

          <Button size="lg" className="w-full" onClick={signIn}>
            Set up my workspace →
          </Button>
          <p className="text-[12.5px] text-center text-ink-muted mt-5">
            Auth is stubbed in v1. Hit the button and you&apos;ll go through a 30-second onboarding (name + company).
          </p>
        </div>
      </div>
    </div>
  );
}
