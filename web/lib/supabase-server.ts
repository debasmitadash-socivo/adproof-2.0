// Server-side Supabase client — used by middleware, server components, and
// route handlers. Reads/writes the session via cookies (NOT localStorage),
// which is what Next.js SSR needs to know who's logged in on every request.
//
// Use `getServerSupabase()` in route handlers + middleware. Use the browser
// client (lib/supabase.ts) inside client components.
import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { cookies } from 'next/headers';

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

/** Server-component / route-handler Supabase client. */
export function getServerSupabase() {
  if (!url || !anonKey) {
    throw new Error(
      '[supabase-server] NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY missing. ' +
      'Set these in .env.local (dev) or your hosting env vars (production).',
    );
  }
  const cookieStore = cookies();
  return createServerClient(url, anonKey, {
    cookies: {
      get(name: string) {
        return cookieStore.get(name)?.value;
      },
      set(name: string, value: string, options: CookieOptions) {
        try {
          cookieStore.set({ name, value, ...options });
        } catch {
          // .set() throws when called from a Server Component (read-only
          // context). It works inside Route Handlers + Server Actions, which
          // is where session writes actually happen. Silently ignore the
          // read-only case so server-component reads don't crash.
        }
      },
      remove(name: string, options: CookieOptions) {
        try {
          cookieStore.set({ name, value: '', ...options });
        } catch {
          // Same as above.
        }
      },
    },
  });
}
