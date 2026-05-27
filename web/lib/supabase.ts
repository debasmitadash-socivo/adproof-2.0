// Browser-side Supabase client.
//
// For now we use the anon key directly — auth + database access happen through
// Row-Level Security policies. The service_role key NEVER touches the browser;
// it lives on the FastAPI backend (Railway env var) for server-only operations.
//
// Helper for SSR / server components / route handlers: import from
// `@supabase/ssr` once we start using server components that need auth state.
import { createClient } from '@supabase/supabase-js';

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  // Fail loudly in dev — quiet console.warn in prod so the rest of the app
  // (which still uses localStorage for v1) keeps rendering.
  if (typeof window !== 'undefined' && process.env.NODE_ENV !== 'production') {
    // eslint-disable-next-line no-console
    console.warn(
      '[supabase] NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY missing — ' +
      'auth + DB features will be disabled. See web/.env.local',
    );
  }
}

// Lazy singleton — created on first use so a missing env var doesn't crash
// the whole bundle at import time.
let _client: ReturnType<typeof createClient> | null = null;

export function getSupabase() {
  if (_client) return _client;
  if (!url || !anonKey) return null;
  _client = createClient(url, anonKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      // Local-storage based session is fine for v1. Once we wire SSR auth
      // (middleware-protected routes), swap this for a cookie-based session
      // via @supabase/ssr's createBrowserClient.
      storageKey: 'adproof-supabase-session',
    },
  });
  return _client;
}

/** True if Supabase env vars are configured. UI uses this to decide whether
 *  to show "Sign in" buttons vs. the v1 stub flow. */
export function supabaseAvailable(): boolean {
  return !!(url && anonKey);
}
