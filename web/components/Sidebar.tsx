'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import clsx from 'clsx';
import { useApp, userInitials, workspaceLabel } from '@/lib/store';

const Icon = {
  Grid: (<svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>),
  Bolt: (<svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" /></svg>),
  Clock: (<svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><polyline points="12,6 12,12 16,14" /></svg>),
  Users: (<svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>),
  Sq: (<svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M9 9h6v6H9z" /></svg>),
  Home: (<svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 21h18" /><path d="M5 21V7l8-4 8 4v14" /></svg>),
  Cog: (<svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33" /></svg>),
  Chart: (<svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 3v18h18" /><rect x="7" y="11" width="3" height="6" /><rect x="12" y="7" width="3" height="10" /><rect x="17" y="13" width="3" height="4" /></svg>),
  Pulse: (<svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>),
};

export function Sidebar() {
  const pathname = usePathname();
  const user = useApp((s) => s.user);
  const profile = useApp((s) => s.companyProfile);
  const companies = useApp((s) => s.companies);
  const currentCompanyId = useApp((s) => s.currentCompanyId);
  const setCurrentCompany = useApp((s) => s.setCurrentCompany);
  const campaignCount = useApp((s) => s.savedCampaigns.length);
  const audienceCount = useApp((s) => s.savedAudiences.length);

  const wsName = workspaceLabel(profile);
  const wsInitial = wsName[0]?.toUpperCase() ?? 'M';

  // Workspace switcher: closed by default; click outside to close.
  const [wsOpen, setWsOpen] = useState(false);
  const wsRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!wsOpen) return;
    function onClick(e: MouseEvent) {
      if (wsRef.current && !wsRef.current.contains(e.target as Node)) setWsOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [wsOpen]);

  const otherWorkspaces = companies.filter((c) => c.id !== currentCompanyId);
  const userName = user?.name?.trim() || 'You';
  const userEmail = user?.email || 'Set up your profile';
  const initials = userInitials(user?.name ?? '');

  const links = [
    { href: '/dashboard', label: 'Dashboard', icon: Icon.Grid },
    { href: '/new', label: 'New analysis', icon: Icon.Bolt },
    { href: '/campaigns', label: 'Campaigns', icon: Icon.Clock,
      badge: campaignCount > 0 ? String(campaignCount) : undefined },
    { href: '/audiences', label: 'Audiences', icon: Icon.Users,
      badge: audienceCount > 0 ? String(audienceCount) : undefined },
    { href: '/creatives', label: 'Creatives', icon: Icon.Sq },
    { href: '/data', label: 'Your data', icon: Icon.Chart },
  ];
  const workspaceLinks = [
    { href: '/company', label: 'Company profile', icon: Icon.Home },
    { href: '/settings', label: 'Settings', icon: Icon.Cog },
    { href: '/admin', label: 'Diagnostics', icon: Icon.Pulse },
  ];

  return (
    <aside className="w-[252px] bg-bg border-r border-border px-3.5 py-4 flex flex-col relative">
      <div
        className="absolute inset-0 pointer-events-none"
        style={{ background: 'radial-gradient(at 0% 0%, rgba(255,94,26,0.10), transparent 70%)', height: '220px' }}
      />
      <div className="relative z-10 flex items-center gap-3 px-2.5 pb-4">
        <div className="w-8 h-8 rounded-[9px] bg-gradient-sunset text-white font-display italic font-bold text-[16px] flex items-center justify-center shadow-glow">A</div>
        <div className="font-heading font-bold text-[18px] tracking-tight">AdProof</div>
      </div>
      <div ref={wsRef} className="relative z-20 mb-4">
        <button type="button"
          onClick={() => setWsOpen((v) => !v)}
          className="w-full flex items-center gap-2.5 px-2.5 py-2 border border-border rounded-lg bg-surface cursor-pointer hover:border-coral transition-colors text-left">
          <div className="w-[22px] h-[22px] rounded-md bg-gradient-aurora text-white font-bold text-[12px] flex items-center justify-center">{wsInitial}</div>
          <div className="text-[13.5px] font-semibold flex-1 truncate">{wsName}</div>
          <div className="text-ink-muted text-[11px]">▾</div>
        </button>
        {wsOpen && (
          <div className="absolute left-0 right-0 mt-1 rounded-lg border border-border bg-surface shadow-lg overflow-hidden">
            {otherWorkspaces.length > 0 && (
              <>
                <div className="px-3 py-1.5 text-[10.5px] text-ink-faint uppercase tracking-[0.12em] font-bold">Switch to</div>
                {otherWorkspaces.map((c) => (
                  <button key={c.id} type="button"
                    onClick={() => { if (c.id) { setCurrentCompany(c.id); setWsOpen(false); } }}
                    className="w-full flex items-center gap-2.5 px-3 py-2 text-[13px] hover:bg-bg-deep text-left">
                    <div className="w-5 h-5 rounded bg-gradient-aurora text-white font-bold text-[10.5px] flex items-center justify-center">
                      {(c.company_name || '?')[0]?.toUpperCase()}
                    </div>
                    <span className="truncate">{c.company_name || 'Untitled workspace'}</span>
                  </button>
                ))}
                <div className="h-px bg-border" />
              </>
            )}
            <Link href="/onboarding?new=1" onClick={() => setWsOpen(false)}
              className="w-full flex items-center gap-2.5 px-3 py-2.5 text-[13px] font-semibold hover:bg-bg-deep text-left text-coral">
              <span className="text-[16px] leading-none">+</span>
              <span>Create new workspace</span>
            </Link>
            <Link href="/company" onClick={() => setWsOpen(false)}
              className="w-full flex items-center gap-2.5 px-3 py-2 text-[12.5px] text-ink-muted hover:bg-bg-deep">
              Edit current workspace →
            </Link>
          </div>
        )}
      </div>
      <nav className="relative z-10 flex flex-col gap-px">
        {links.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={clsx('nav-item', pathname?.startsWith(l.href) && 'active')}
          >
            {l.icon}
            <span>{l.label}</span>
            {l.badge && (
              <span
                className={clsx(
                  'ml-auto px-2 py-0.5 rounded-full text-[11px] font-bold',
                  pathname?.startsWith(l.href) ? 'bg-coral text-white' : 'bg-border text-ink-muted',
                )}
              >{l.badge}</span>
            )}
          </Link>
        ))}
        <div className="mt-5 text-[11px] text-ink-faint uppercase tracking-[0.11em] font-bold px-3 pb-1.5">
          Workspace
        </div>
        {workspaceLinks.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={clsx('nav-item', pathname?.startsWith(l.href) && 'active')}
          >
            {l.icon}
            <span>{l.label}</span>
          </Link>
        ))}
      </nav>
      <Link href="/settings"
        className="relative z-10 mt-auto pt-3.5 border-t border-border flex items-center gap-2.5 px-2.5 hover:bg-coral-soft -mx-3.5 px-3.5 py-3 transition-colors">
        <div className="w-8 h-8 rounded-[10px] bg-gradient-aurora text-white font-heading font-bold text-[12px] flex items-center justify-center">{initials}</div>
        <div className="min-w-0">
          <div className="text-[13px] font-semibold truncate">{userName}</div>
          <div className="text-[11.5px] text-ink-muted truncate">{userEmail}</div>
        </div>
      </Link>
    </aside>
  );
}
