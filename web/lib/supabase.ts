// Browser-side Supabase client.
//
// Uses @supabase/ssr's createBrowserClient so the session lives in cookies
// (not localStorage) — the same cookies our middleware reads. That means
// server + client always agree on who's logged in.
import { createBrowserClient } from '@supabase/ssr';
import type { SupabaseClient } from '@supabase/supabase-js';

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  if (typeof window !== 'undefined' && process.env.NODE_ENV !== 'production') {
    // eslint-disable-next-line no-console
    console.warn(
      '[supabase] NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY missing — ' +
      'auth disabled. See web/.env.local',
    );
  }
}

let _client: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient | null {
  if (_client) return _client;
  if (!url || !anonKey) return null;
  _client = createBrowserClient(url, anonKey);
  return _client;
}

/** True if Supabase env vars are configured. UI uses this to decide whether
 *  to show "Sign in" buttons vs. an env-misconfigured error state. */
export function supabaseAvailable(): boolean {
  return !!(url && anonKey);
}
