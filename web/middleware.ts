// Route-level auth gate.
//
// Runs on every request. Reads the Supabase session cookie:
//   - If on a protected route (dashboard, new, result, audiences, creatives,
//     campaigns, company, settings, onboarding) WITHOUT a session → /login
//   - If on /login WITH a session → /dashboard (skip the form, already in)
//   - Everything else passes through untouched.
//
// We also refresh the session here so server components further down the
// request lifecycle see a fresh, non-expired auth state.

import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';

const PROTECTED_PATHS = [
  '/dashboard', '/new', '/result',
  '/audiences', '/creatives', '/campaigns',
  '/company', '/settings', '/onboarding',
  '/admin', '/accuracy', '/ads',
];

function isProtected(pathname: string): boolean {
  return PROTECTED_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export async function middleware(req: NextRequest) {
  // Start with a response we'll mutate cookies on. Supabase needs to
  // potentially set refreshed-token cookies; we attach those here so the
  // browser keeps the session warm.
  let res = NextResponse.next({ request: { headers: req.headers } });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anon) {
    // Env vars missing — don't crash, just let everything through. The
    // browser client will surface a console warning. This prevents a broken
    // local dev where someone clones without .env.local from getting an
    // infinite redirect loop.
    return res;
  }

  const supabase = createServerClient(url, anon, {
    cookies: {
      get(name: string) { return req.cookies.get(name)?.value; },
      set(name: string, value: string, options: CookieOptions) {
        req.cookies.set({ name, value, ...options });
        res = NextResponse.next({ request: { headers: req.headers } });
        res.cookies.set({ name, value, ...options });
      },
      remove(name: string, options: CookieOptions) {
        req.cookies.set({ name, value: '', ...options });
        res = NextResponse.next({ request: { headers: req.headers } });
        res.cookies.set({ name, value: '', ...options });
      },
    },
  });

  const { data: { user } } = await supabase.auth.getUser();
  const path = req.nextUrl.pathname;

  if (isProtected(path) && !user) {
    const loginUrl = new URL('/login', req.url);
    // Remember both path AND query string — otherwise a session expiring on the
    // way to /onboarding?new=1 drops the new-workspace flag and the user lands
    // back on /dashboard with no idea why their click went nowhere.
    const nextWithQuery = req.nextUrl.search
      ? `${path}${req.nextUrl.search}`
      : path;
    loginUrl.searchParams.set('next', nextWithQuery);
    return NextResponse.redirect(loginUrl);
  }
  if (path === '/login' && user) {
    return NextResponse.redirect(new URL('/dashboard', req.url));
  }
  return res;
}

// Skip middleware for static assets, image-optimisation, and our own /api
// rewrites (those go straight to Railway). Run on everything else.
export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|api/|uploads/).*)',
  ],
};
