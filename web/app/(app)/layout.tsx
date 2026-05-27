'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from '@/components/Sidebar';
import { Topbar } from '@/components/Topbar';
import { useApp } from '@/lib/store';
import { getSupabase } from '@/lib/supabase';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const hydrated = useApp((s) => s.hydrated);
  const user = useApp((s) => s.user);
  const profile = useApp((s) => s.companyProfile);
  const setUser = useApp((s) => s.setUser);

  // Mirror the Supabase session into the Zustand store so the existing UI
  // (sidebar avatar, greeting, etc.) keeps working unchanged. Supabase is
  // the source of truth for identity; the local store is just a UI cache.
  useEffect(() => {
    const sb = getSupabase();
    if (!sb) return;

    let alive = true;

    // Initial fetch — populate from current cookie session.
    sb.auth.getUser().then(({ data }) => {
      if (!alive) return;
      const u = data.user;
      if (u) {
        const meta = (u.user_metadata || {}) as { name?: string };
        const existing = useApp.getState().user;
        // Preserve a previously-entered display name; otherwise default to
        // the email prefix so the greeting isn't blank on first sign-in.
        const displayName =
          existing?.name?.trim() ||
          meta.name ||
          (u.email ? u.email.split('@')[0] : 'You');
        setUser({
          name: displayName,
          email: u.email || existing?.email || '',
          createdAt: existing?.createdAt ?? Date.now(),
        });
      } else if (useApp.getState().user) {
        // Session is gone but the store still has a user (stale localStorage)
        // — clear it so we don't show a phantom logged-in state.
        setUser(null);
      }
    });

    // Listen for sign-out / token-refresh events to keep things in sync.
    const { data: sub } = sb.auth.onAuthStateChange((event, session) => {
      if (!alive) return;
      if (event === 'SIGNED_OUT' || !session) {
        setUser(null);
      }
    });
    return () => { alive = false; sub.subscription.unsubscribe(); };
  }, [setUser]);

  // Onboarding redirect — once we know there's a user but no company profile.
  useEffect(() => {
    if (!hydrated) return;
    if (user && !profile) router.replace('/onboarding');
  }, [hydrated, user, profile, router]);

  if (!hydrated) return null;

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar />
        <main className="flex-1 px-10 py-8 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
