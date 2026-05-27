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
                We&apos;ll email you a one-time sign-in link. No password to remember.
              </p>

              {!supaOk && (
                <div className="mb-5 p-3 rounded-md bg-warning-soft border border-warning/30 text-[12.5px] text-yellow-800">
                  <strong>Auth not configured.</strong> NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY missing. Set them in <code className="font-mono">web/.env.local</code> (dev) or Vercel env vars (prod).
                </div>
              )}

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
