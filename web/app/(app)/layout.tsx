'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from '@/components/Sidebar';
import { Topbar } from '@/components/Topbar';
import { useApp } from '@/lib/store';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const hydrated = useApp((s) => s.hydrated);
  const user = useApp((s) => s.user);
  const profile = useApp((s) => s.companyProfile);

  useEffect(() => {
    if (!hydrated) return;
    if (!user || !profile) {
      router.replace('/onboarding');
    }
  }, [hydrated, user, profile, router]);

  // While the persisted store is rehydrating from localStorage, render
  // nothing rather than the empty fallback (avoids a flash of "no name").
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
