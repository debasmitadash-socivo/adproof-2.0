-- AdProof — full database setup. Runs migrations 0001–0008 in order.
-- Safe to re-run. Paste into Supabase SQL editor and Run.


-- ============================================================
-- 0001_init.sql
-- ============================================================
-- AdProof — initial schema.
-- Moves campaigns / companies / audiences out of browser localStorage into
-- Postgres, and adds the tables Path B needs (real ad outcomes + per-account
-- calibrations). Every table is row-level-security locked to the owning user.
--
-- Apply: paste this into the Supabase SQL editor (Dashboard → SQL → New query)
-- and run, OR `supabase db push` if you use the CLI. Safe to re-run.

create extension if not exists "pgcrypto";

-- Shared updated_at trigger ------------------------------------------------
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- ========================================================================
-- companies — the advertiser profile (one or more per user)
-- ========================================================================
create table if not exists public.companies (
  id                       uuid primary key default gen_random_uuid(),
  user_id                  uuid not null references auth.users(id) on delete cascade,
  name                     text,
  raw_description          text,
  industry                 text,
  business_model           text,
  product_category         text,
  value_proposition        text,
  target_customer_summary  text,
  price_position           text,
  brand_tone               text,
  website                  text,
  location                 text,
  currency                 text default 'GBP',
  avg_order_value          numeric,
  product_price            numeric,
  source                   text,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now()
);
create index if not exists companies_user_idx on public.companies(user_id);

-- ========================================================================
-- audiences — saved audience definitions
-- ========================================================================
create table if not exists public.audiences (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  name          text not null,
  description   text,
  segment       text,
  used_in_count integer not null default 0,
  created_at    timestamptz not null default now()
);
create index if not exists audiences_user_idx on public.audiences(user_id);

-- ========================================================================
-- campaigns — one per saved run (aggregate metrics as columns for listing)
-- ========================================================================
create table if not exists public.campaigns (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references auth.users(id) on delete cascade,
  name           text,
  platform_name  text,
  format_name    text,
  audience_label text,
  budget         numeric,
  days           integer,
  roas_p50       numeric,
  roi_p50        numeric,
  ctr_pct        numeric,
  verdict_class  text,
  thumbnail_url  text,
  market_context jsonb,
  rerun_of_id    uuid references public.campaigns(id) on delete set null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index if not exists campaigns_user_created_idx on public.campaigns(user_id, created_at desc);

-- ========================================================================
-- campaign_variants — per-variant detail; full SimulateResponse in `result`
-- ========================================================================
create table if not exists public.campaign_variants (
  id               uuid primary key default gen_random_uuid(),
  campaign_id      uuid not null references public.campaigns(id) on delete cascade,
  user_id          uuid not null references auth.users(id) on delete cascade,
  label            text,
  headline         text,
  thumbnail_url    text,
  roas_p50         numeric,
  roi_p50          numeric,
  ctr_pct          numeric,
  verdict_class    text,
  result           jsonb,    -- full SimulateResponse
  original_request jsonb,    -- the SimulateRequest, so a campaign can be re-run
  created_at       timestamptz not null default now()
);
create index if not exists variants_campaign_idx on public.campaign_variants(campaign_id);
create index if not exists variants_user_idx on public.campaign_variants(user_id);

-- ========================================================================
-- ad_outcomes — REAL past ad results from the client (Path B calibration +
-- backtest input). Derived metrics are generated so the truth is consistent.
-- ========================================================================
create table if not exists public.ad_outcomes (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  ad_name         text,
  date_start      date,
  date_end        date,
  platform        text,
  format          text,
  spend           numeric,
  impressions     bigint,
  clicks          bigint,
  conversions     numeric,
  revenue         numeric,
  ad_copy         text,
  audience        text,
  creative_url    text,
  test_group      text,
  conversion_type text,
  objective       text,
  currency        text,
  geo             text,
  product_price   numeric,
  source_file     text,
  -- derived "truth" we calibrate + backtest against
  real_ctr  numeric generated always as
    (case when impressions > 0 then clicks::numeric / impressions else null end) stored,
  real_cvr  numeric generated always as
    (case when clicks > 0 then conversions / clicks else null end) stored,
  real_roas numeric generated always as
    (case when spend > 0 then revenue / spend else null end) stored,
  real_cpm  numeric generated always as
    (case when impressions > 0 then spend / impressions * 1000 else null end) stored,
  created_at timestamptz not null default now()
);
create index if not exists outcomes_user_fmt_idx on public.ad_outcomes(user_id, platform, format);
create index if not exists outcomes_test_group_idx on public.ad_outcomes(user_id, test_group);

-- ========================================================================
-- calibrations — per-account learned parameters (Path B output). Strictly
-- scoped to one user; NEVER a shared/global prior.
-- ========================================================================
create table if not exists public.calibrations (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  scope       text not null,        -- e.g. 'account' | format id
  params      jsonb not null,       -- learned ctr/cvr/cpm + weights
  n_ads       integer,
  window_from date,
  window_to   date,
  backtest    jsonb,                -- predicted-vs-actual error summary
  created_at  timestamptz not null default now()
);
create index if not exists calibrations_user_scope_idx on public.calibrations(user_id, scope, created_at desc);

-- updated_at triggers -----------------------------------------------------
drop trigger if exists companies_set_updated on public.companies;
create trigger companies_set_updated before update on public.companies
  for each row execute function public.set_updated_at();
drop trigger if exists campaigns_set_updated on public.campaigns;
create trigger campaigns_set_updated before update on public.campaigns
  for each row execute function public.set_updated_at();

-- ========================================================================
-- Row-level security — a user can only ever see / change their own rows.
-- ========================================================================
do $$
declare t text;
begin
  foreach t in array array[
    'companies','audiences','campaigns','campaign_variants','ad_outcomes','calibrations'
  ] loop
    execute format('alter table public.%I enable row level security;', t);
    execute format('drop policy if exists %I on public.%I;', t || '_owner', t);
    execute format(
      'create policy %I on public.%I for all to authenticated
         using (user_id = auth.uid()) with check (user_id = auth.uid());',
      t || '_owner', t);
  end loop;
end $$;


-- ============================================================
-- 0002_workspaces.sql
-- ============================================================
-- Multi-workspace support: one user can manage several companies/clients.
-- Each data row now belongs to a company (workspace), not just to a user.
-- Existing rows are backfilled to the user's first company, so nothing is lost.

-- Add company_id (nullable initially so backfill works) ---------------------
alter table public.audiences         add column if not exists company_id uuid;
alter table public.campaigns         add column if not exists company_id uuid;
alter table public.calibrations      add column if not exists company_id uuid;
alter table public.ad_outcomes       add column if not exists company_id uuid;

-- Backfill: for each row, set company_id to the row owner's earliest company
update public.audiences a set company_id = (
  select id from public.companies c where c.user_id = a.user_id
  order by created_at asc limit 1)
where a.company_id is null;

update public.campaigns ca set company_id = (
  select id from public.companies c where c.user_id = ca.user_id
  order by created_at asc limit 1)
where ca.company_id is null;

update public.calibrations cal set company_id = (
  select id from public.companies c where c.user_id = cal.user_id
  order by created_at asc limit 1)
where cal.company_id is null;

update public.ad_outcomes o set company_id = (
  select id from public.companies c where c.user_id = o.user_id
  order by created_at asc limit 1)
where o.company_id is null;

-- Add foreign keys (cascading delete: removing a workspace removes its data)
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'audiences_company_fkey') then
    alter table public.audiences add constraint audiences_company_fkey
      foreign key (company_id) references public.companies(id) on delete cascade;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'campaigns_company_fkey') then
    alter table public.campaigns add constraint campaigns_company_fkey
      foreign key (company_id) references public.companies(id) on delete cascade;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'calibrations_company_fkey') then
    alter table public.calibrations add constraint calibrations_company_fkey
      foreign key (company_id) references public.companies(id) on delete cascade;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'ad_outcomes_company_fkey') then
    alter table public.ad_outcomes add constraint ad_outcomes_company_fkey
      foreign key (company_id) references public.companies(id) on delete cascade;
  end if;
end $$;

-- Indexes (fast filter-by-current-workspace) --------------------------------
create index if not exists audiences_company_idx    on public.audiences(company_id);
create index if not exists campaigns_company_idx    on public.campaigns(user_id, company_id, created_at desc);
create index if not exists calibrations_company_idx on public.calibrations(company_id, created_at desc);
create index if not exists outcomes_company_idx     on public.ad_outcomes(company_id, platform);

-- Add a `name` constraint and `archived` flag on companies for the switcher.
alter table public.companies add column if not exists archived boolean not null default false;


-- ============================================================
-- 0003_company_richer.sql
-- ============================================================
-- Onboarding overhaul: capture richer company info so the forecast can use it.
-- All new columns are nullable + safely-defaulted so existing rows keep working.

alter table public.companies
  add column if not exists usps            text[],
  add column if not exists conversion_goal text,   -- purchase | lead | demo | signup | awareness
  add column if not exists sales_cycle     text,   -- impulse | considered | long | enterprise
  add column if not exists brand_color     text;   -- hex string, e.g. #FF5A4D


-- ============================================================
-- 0004_creative_scores.sql
-- ============================================================
-- Pillar C: per-creative score history — the training-set seed.
--
-- Every AdProof forecast lands one row here: the creative reference, the
-- vision scores we read off it, the Reel Quality scorecard (when video),
-- the campaign settings (objective + audience segment + platform), and the
-- forecast headline so we can later join against a known real CTR/ROAS
-- (which sits in ad_outcomes) and fit a per-account creative->CTR model.
--
-- Strictly RLS-scoped to the inserting user. NEVER a shared/global prior.

create table if not exists public.creative_scores (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references auth.users(id) on delete cascade,
  company_id         uuid references public.companies(id) on delete set null,
  campaign_id        uuid references public.campaigns(id) on delete cascade,
  -- Creative reference. The asset itself lives in Supabase storage / the
  -- uploads volume; this is just a pointer + label so we can re-fetch + dedupe.
  creative_url       text,                 -- canonical link to the asset
  thumbnail_url      text,                 -- preview for the UI
  creative_kind      text,                 -- 'image' | 'video' | 'carousel'
  ad_name            text,                 -- user-supplied label, helps joins
  -- Campaign settings that change how a creative is interpreted (Pillar A).
  objective          text,                 -- awareness | consideration | conversion
  platform_id        text,
  format_id          text,
  audience_segment   text,                 -- one of AUDIENCE_SEGMENTS or 'unknown'
  -- The scores themselves. jsonb so future fields (e.g. CTA-prominence) don't
  -- need a migration; keep the canonical names stable (see config.py).
  vision_scores      jsonb,                -- { emotional_arousal, visual_clarity, attention_capture, relevance_potential, ban_risk, brand_relevance, image_copy_coherence }
  reel_quality       jsonb,                -- ReelQualityResult.to_dict() — null for images / heuristic runs
  -- Forecast headline at the time of scoring (useful for later analysis +
  -- so we can later compute predicted-vs-actual without re-running the engine).
  forecast_ctr_p50   numeric,
  forecast_roas_p50  numeric,
  forecast_cpm_p50   numeric,
  verdict_class      text,
  -- Provenance.
  visual_provider    text,                 -- 'gemini' | 'claude' | 'openai' | 'heuristic' | 'none'
  visual_model       text,
  is_heuristic       boolean default false,
  created_at         timestamptz not null default now()
);

create index if not exists creative_scores_user_idx
  on public.creative_scores(user_id, created_at desc);
create index if not exists creative_scores_campaign_idx
  on public.creative_scores(campaign_id);
-- For the future per-account predicted-vs-actual join:
create index if not exists creative_scores_user_creative_idx
  on public.creative_scores(user_id, creative_url);

-- RLS — same pattern as the other per-user tables.
alter table public.creative_scores enable row level security;
drop policy if exists creative_scores_owner on public.creative_scores;
create policy creative_scores_owner on public.creative_scores
  for all to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());


-- ============================================================
-- 0005_creative_scores_interests.sql
-- ============================================================
-- Pillar B+: add interest dimension to the creative-scores training set.
--
-- ``interests`` is the deduped list of canonical interest buckets the wizard
-- inferred for the campaign (from filter chips, free-text description, or
-- the company's product category). ``dominant_interest`` is the single
-- top bucket, kept denormalised so the future per-account model can use it
-- as a categorical feature without re-parsing the array.
--
-- Both columns are nullable so older rows (and runs without interest data)
-- continue to land cleanly. No backfill needed.

alter table public.creative_scores
  add column if not exists interests          jsonb,
  add column if not exists dominant_interest  text;


-- ============================================================
-- 0006_storage_creatives.sql
-- ============================================================
-- Tier 2: Supabase Storage for creative uploads.
--
-- Replaces the Railway-ephemeral /api/upload flow (files in /app/data/raw/
-- uploads vanish on every redeploy). The wizard now uploads directly
-- through the user's authenticated supabase-js client; the backend
-- receives durable signed URLs and downloads them to a per-request temp
-- file before vision analysis. Re-analysis of saved campaigns works
-- forever because the file lives in Supabase, not on the Railway worker.
--
-- The bucket is created via the Storage REST API (separate call from this
-- file) — Postgres can't create buckets directly. This migration sets up
-- the storage.objects RLS policies that gate access per-user.
--
-- Per-user isolation: a file's path MUST start with the uploader's
-- auth.uid() (e.g. '<uuid>/ad-1234.mp4'). The policy enforces that on
-- INSERT, SELECT, UPDATE, and DELETE so a user can never reach another
-- user's files even if they guess the path.

-- Drop any prior versions (idempotent).
drop policy if exists "ad_creatives_own_select"   on storage.objects;
drop policy if exists "ad_creatives_own_insert"   on storage.objects;
drop policy if exists "ad_creatives_own_update"   on storage.objects;
drop policy if exists "ad_creatives_own_delete"   on storage.objects;

create policy "ad_creatives_own_select"
  on storage.objects for select to authenticated
  using (bucket_id = 'ad-creatives'
         and (storage.foldername(name))[1] = auth.uid()::text);

create policy "ad_creatives_own_insert"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'ad-creatives'
              and (storage.foldername(name))[1] = auth.uid()::text);

create policy "ad_creatives_own_update"
  on storage.objects for update to authenticated
  using (bucket_id = 'ad-creatives'
         and (storage.foldername(name))[1] = auth.uid()::text);

create policy "ad_creatives_own_delete"
  on storage.objects for delete to authenticated
  using (bucket_id = 'ad-creatives'
         and (storage.foldername(name))[1] = auth.uid()::text);


-- ============================================================
-- 0007_team_members.sql
-- ============================================================
-- Team invites: share a workspace (company) with teammates.
--
-- Model: the workspace owner (companies.user_id) invites a teammate by email.
-- The invite is just a row here — no email is sent. When someone signs in to
-- AdProof with that email, the app claims the row (user_id + status='active')
-- and the shared workspace appears in their switcher. RLS is rewritten so
-- active members can see the shared company and read/write its campaigns,
-- audiences, calibrations, outcomes and creative scores. Only the owner can
-- edit the company profile, invite, or remove members.
--
-- Apply: paste into the Supabase SQL editor and run, OR `supabase db push`.
-- Safe to re-run.

-- ========================================================================
-- company_members — one row per (workspace, invited person)
-- ========================================================================
create table if not exists public.company_members (
  id            uuid primary key default gen_random_uuid(),
  company_id    uuid not null references public.companies(id) on delete cascade,
  user_id       uuid references auth.users(id) on delete cascade,  -- null until claimed
  invited_email text not null,                                     -- stored lowercase
  role          text not null default 'editor',    -- reserved: 'editor' | 'viewer'
  status        text not null default 'invited',   -- 'invited' | 'active'
  invited_by    uuid references auth.users(id) on delete set null,
  created_at    timestamptz not null default now(),
  accepted_at   timestamptz
);
create unique index if not exists company_members_unique_invite
  on public.company_members(company_id, lower(invited_email));
create index if not exists company_members_user_idx
  on public.company_members(user_id) where user_id is not null;
create index if not exists company_members_email_idx
  on public.company_members(lower(invited_email));

-- ========================================================================
-- Membership helpers. SECURITY DEFINER so they read companies /
-- company_members without re-triggering RLS (which would recurse: the
-- companies policy calls is_workspace_member, which reads company_members,
-- whose policy reads companies, ...).
-- ========================================================================
create or replace function public.is_workspace_owner(cid uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from companies c where c.id = cid and c.user_id = auth.uid()
  );
$$;

create or replace function public.is_workspace_member(cid uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from companies c where c.id = cid and c.user_id = auth.uid()
  ) or exists (
    select 1 from company_members m
    where m.company_id = cid and m.user_id = auth.uid() and m.status = 'active'
  );
$$;

-- ========================================================================
-- company_members policies
-- ========================================================================
alter table public.company_members enable row level security;

drop policy if exists company_members_select on public.company_members;
create policy company_members_select on public.company_members
  for select to authenticated
  using (
    public.is_workspace_member(company_id)                                -- owner + active members see the roster
    or user_id = auth.uid()                                               -- your own membership rows
    or lower(invited_email) = lower(coalesce(auth.jwt()->>'email',''))    -- invites addressed to you
  );

drop policy if exists company_members_insert on public.company_members;
create policy company_members_insert on public.company_members
  for insert to authenticated
  with check (public.is_workspace_owner(company_id));

drop policy if exists company_members_update on public.company_members;
create policy company_members_update on public.company_members
  for update to authenticated
  using (
    public.is_workspace_owner(company_id)
    or lower(invited_email) = lower(coalesce(auth.jwt()->>'email',''))    -- invitee claiming their invite
  )
  with check (
    public.is_workspace_owner(company_id)
    or user_id = auth.uid()                                               -- a claim may only assign YOUR user_id
  );

drop policy if exists company_members_delete on public.company_members;
create policy company_members_delete on public.company_members
  for delete to authenticated
  using (public.is_workspace_owner(company_id) or user_id = auth.uid()); -- owner removes; member leaves

-- ========================================================================
-- companies: split the owner-only FOR ALL policy so members can SELECT the
-- shared workspace, while profile edits / deletion stay owner-only. (Edits
-- also stamp user_id with the caller's uid — owner-only update prevents a
-- member from hijacking ownership that way.)
-- ========================================================================
drop policy if exists companies_owner on public.companies;

drop policy if exists companies_select on public.companies;
create policy companies_select on public.companies
  for select to authenticated
  using (user_id = auth.uid() or public.is_workspace_member(id));

drop policy if exists companies_insert on public.companies;
create policy companies_insert on public.companies
  for insert to authenticated
  with check (user_id = auth.uid());

drop policy if exists companies_update on public.companies;
create policy companies_update on public.companies
  for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists companies_delete on public.companies;
create policy companies_delete on public.companies
  for delete to authenticated
  using (user_id = auth.uid());

-- ========================================================================
-- Workspace data tables: owner OR active member of the row's workspace.
-- Rows with no company_id stay visible to their creator only.
-- ========================================================================
do $$
declare t text;
begin
  foreach t in array array[
    'audiences','campaigns','calibrations','ad_outcomes','creative_scores'
  ] loop
    execute format('drop policy if exists %I on public.%I;', t || '_owner', t);
    execute format('drop policy if exists %I on public.%I;', t || '_member', t);
    execute format(
      'create policy %I on public.%I for all to authenticated
         using (user_id = auth.uid()
                or (company_id is not null and public.is_workspace_member(company_id)))
         with check (user_id = auth.uid()
                or (company_id is not null and public.is_workspace_member(company_id)));',
      t || '_member', t);
  end loop;
end $$;

-- campaign_variants has no company_id — scope through its campaign.
drop policy if exists campaign_variants_owner on public.campaign_variants;
drop policy if exists campaign_variants_member on public.campaign_variants;
create policy campaign_variants_member on public.campaign_variants
  for all to authenticated
  using (
    user_id = auth.uid()
    or exists (
      select 1 from public.campaigns c
      where c.id = campaign_id
        and c.company_id is not null
        and public.is_workspace_member(c.company_id))
  )
  with check (
    user_id = auth.uid()
    or exists (
      select 1 from public.campaigns c
      where c.id = campaign_id
        and c.company_id is not null
        and public.is_workspace_member(c.company_id))
  );


-- ============================================================
-- 0008_platform_connections.sql
-- ============================================================
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

