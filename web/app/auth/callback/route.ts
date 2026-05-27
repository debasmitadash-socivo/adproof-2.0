// Magic-link callback. Supabase sends users here after they click the email
// link: /auth/callback?code=<one-time-code>&next=/dashboard
//
// We exchange the code for a session (Supabase sets the auth cookies on the
// response), then redirect to wherever they were trying to go before sign-in.

import { NextResponse, type NextRequest } from 'next/server';
import { getServerSupabase } from '@/lib/supabase-server';

export async function GET(req: NextRequest) {
  const { searchParams, origin } = new URL(req.url);
  const code = searchParams.get('code');
  const next = searchParams.get('next') || '/dashboard';

  if (!code) {
    // Nothing to exchange — back to login with a hint.
    return NextResponse.redirect(
      new URL('/login?error=missing_code', origin),
    );
  }

  const supabase = getServerSupabase();
  const { error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    // Bad/expired link — bounce back to login with the message in the URL.
    const u = new URL('/login', origin);
    u.searchParams.set('error', error.message);
    return NextResponse.redirect(u);
  }

  // Success — go where the user originally wanted (or /dashboard).
  return NextResponse.redirect(new URL(next, origin));
}
