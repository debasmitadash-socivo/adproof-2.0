'use client';
import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Button } from '@/components/ui/Button';
import { getSupabase, supabaseAvailable } from '@/lib/supabase';

export default function LoginPage() {
  // Wrap the inner form in Suspense so useSearchParams() doesn't break
  // static prerender on Vercel. Next.js requires this since 14.x.
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get('next') || '/dashboard';

  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // If session exists (e.g. came back via /auth/callback), bounce to dashboard.
  useEffect(() => {
    const sb = getSupabase();
    if (!sb) return;
    sb.auth.getSession().then(({ data }) => {
      if (data.session) router.replace(nextPath);
    });
  }, [nextPath, router]);

  async function signInWithGoogle() {
    setErr(null);
    setGoogleLoading(true);
    try {
      const sb = getSupabase();
      if (!sb) {
        setErr('Supabase not configured. See web/.env.local.');
        return;
      }
      const origin = typeof window !== 'undefined' ? window.location.origin : '';
      const { error } = await sb.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: `${origin}/auth/callback?next=${encodeURIComponent(nextPath)}`,
        },
      });
      if (error) {
        setErr(error.message);
        setGoogleLoading(false);
      }
      // On success the browser is redirected to Google — no need to clear state.
    } catch (e) {
      setErr((e as Error).message);
      setGoogleLoading(false);
    }
  }

  async function signInWithMagicLink(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setSubmitting(true);
    try {
      const sb = getSupabase();
      if (!sb) {
        setErr('Supabase not configured. See web/.env.local.');
        return;
      }
      const origin = typeof window !== 'undefined' ? window.location.origin : '';
      const { error } = await sb.auth.signInWithOtp({
        email: email.trim(),
        options: {
          emailRedirectTo: `${origin}/auth/callback?next=${encodeURIComponent(nextPath)}`,
        },
      });
      if (error) {
        setErr(error.message);
        return;
      }
      setSent(true);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  const supaOk = supabaseAvailable();

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      {/* LEFT: gradient brand pitch */}
      <div className="hidden lg:flex relative overflow-hidden bg-gradient-sunset text-white p-16 flex-col">
        <div className="absolute inset-0 mesh-overlay" />
        <div
          className="absolute -right-48 -bottom-48 w-[500px] h-[500px] rounded-full pointer-events-none"
          style={{ background: 'radial-gradient(circle, rgba(190,242,100,0.30), transparent 65%)' }}
        />
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
        <div className="w-full max-w-[400px]">
          <div className="flex items-center gap-2.5 mb-9">
            <div className="w-8 h-8 rounded-[9px] bg-gradient-sunset text-white font-display italic font-bold flex items-center justify-center shadow-glow">A</div>
            <div className="font-heading font-bold text-[18px]">AdProof</div>
          </div>

          {!sent ? (
            <>
              <div className="display-italic text-[44px] leading-none">
                Sign in <span className="gradient-text">to AdProof.</span>
              </div>
              <p className="text-ink-muted mt-3.5 mb-6 text-[14.5px]">
                Continue with Google in one click, or get a one-time email link.
              </p>

              {!supaOk && (
                <div className="mb-5 p-3 rounded-md bg-warning-soft border border-warning/30 text-[12.5px] text-yellow-800">
                  <strong>Auth not configured.</strong> NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY missing. Set them in <code className="font-mono">web/.env.local</code> (dev) or Vercel env vars (prod).
                </div>
              )}

              <button
                type="button"
                onClick={signInWithGoogle}
                disabled={googleLoading || submitting || !supaOk}
                className="w-full flex items-center justify-center gap-3 px-4 py-3 rounded-lg border border-border bg-surface hover:bg-bg-deep text-ink font-semibold text-[14.5px] transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {/* Google G logo */}
                <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
                  <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.91c1.7-1.56 2.69-3.87 2.69-6.62z"/>
                  <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.26c-.81.54-1.84.86-3.05.86-2.34 0-4.33-1.58-5.04-3.71H.96v2.33A9 9 0 0 0 9 18z"/>
                  <path fill="#FBBC05" d="M3.96 10.71A5.41 5.41 0 0 1 3.68 9c0-.59.1-1.17.28-1.71V4.96H.96A9 9 0 0 0 0 9c0 1.45.35 2.82.96 4.04l3-2.33z"/>
                  <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.96l3 2.33C4.67 5.16 6.66 3.58 9 3.58z"/>
                </svg>
                {googleLoading ? 'Opening Google…' : 'Continue with Google'}
              </button>

              <div className="flex items-center gap-3 my-5 text-[11.5px] text-ink-faint uppercase tracking-[0.12em]">
                <div className="flex-1 h-px bg-border" />
                <span>or use email</span>
                <div className="flex-1 h-px bg-border" />
              </div>

              <form onSubmit={signInWithMagicLink} className="space-y-3">
                <div>
                  <label htmlFor="email" className="label">Email</label>
                  <input
                    id="email"
                    type="email"
                    required
                    autoComplete="email"
                    autoFocus
                    placeholder="you@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="input"
                  />
                </div>
                <Button
                  size="lg"
                  className="w-full"
                  disabled={submitting || !email.trim() || !supaOk}
                  type="submit"
                >
                  {submitting ? 'Sending magic link…' : 'Email me a sign-in link →'}
                </Button>
              </form>

              {err && (
                <div className="mt-4 p-3 rounded-md bg-danger-soft border border-danger/30 text-[12.5px] text-red-800">
                  {err}
                </div>
              )}

              <p className="text-[12.5px] text-center text-ink-muted mt-7 leading-relaxed">
                By signing in you agree to AdProof storing your email so we can identify your workspace. We don&apos;t share it with anyone.
              </p>
            </>
          ) : (
            <>
              <div className="display-italic text-[40px] leading-tight">
                Check your <span className="gradient-text">inbox.</span>
              </div>
              <p className="text-ink-muted mt-3.5 mb-6 text-[15px] leading-relaxed">
                We sent a one-time sign-in link to <strong className="text-ink">{email}</strong>. Click it and you&apos;ll be signed in here automatically.
              </p>
              <div className="p-4 rounded-md bg-coral-soft border border-coral/30 text-[13px] text-ink leading-snug mb-5">
                Didn&apos;t get the email? Check spam, or wait ~60 seconds — Supabase sometimes takes a moment to dispatch the first email.
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => { setSent(false); setEmail(''); }}
              >
                ← Use a different email
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
