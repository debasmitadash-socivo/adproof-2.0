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
