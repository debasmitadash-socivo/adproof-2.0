-- Platform connections: persist each workspace's ad-platform credentials
-- (Meta / TikTok / Google / LinkedIn / Reddit / X) so syncing real performance
-- is one click instead of re-pasting tokens every time.
--
-- Requires 0007_team_members.sql first (uses its is_workspace_member helper).
--
-- Security model: credentials are stored per-workspace and RLS-locked to the
-- workspace owner + active members — the same people who could read the ad
-- data those credentials unlock. Supabase encrypts at rest. Tokens here are
-- READ-ONLY ad-performance scopes by design (ads_read etc.), never write.
--
-- Apply: paste into the Supabase SQL editor and run, OR `supabase db push`.
-- Safe to re-run.

create table if not exists public.platform_connections (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  company_id     uuid not null references public.companies(id) on delete cascade,
  provider       text not null,          -- 'meta' | 'tiktok' | 'google' | 'linkedin' | 'reddit' | 'x'
  label          text,                   -- e.g. account name from the test call
  credentials    jsonb not null default '{}'::jsonb,   -- per-provider fields
  account_ref    text,                   -- the platform-side account id (display)
  status         text not null default 'unverified',   -- 'unverified' | 'ok' | 'error'
  status_note    text,                   -- last test/sync message
  last_synced_at timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- One connection per (workspace, provider) — reconnecting replaces it.
create unique index if not exists platform_connections_unique
  on public.platform_connections(company_id, provider);
create index if not exists platform_connections_company_idx
  on public.platform_connections(company_id);

drop trigger if exists platform_connections_set_updated on public.platform_connections;
create trigger platform_connections_set_updated
  before update on public.platform_connections
  for each row execute function public.set_updated_at();

alter table public.platform_connections enable row level security;
drop policy if exists platform_connections_member on public.platform_connections;
create policy platform_connections_member on public.platform_connections
  for all to authenticated
  using (user_id = auth.uid() or public.is_workspace_member(company_id))
  with check (user_id = auth.uid() or public.is_workspace_member(company_id));
