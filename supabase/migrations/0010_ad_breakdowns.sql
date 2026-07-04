-- Audience breakdowns: WHO the ads actually reached and who responded,
-- by age band × gender (per ad, aggregated over the sync window).
--
-- Deliberately a SEPARATE table from ad_outcomes: breakdown rows re-slice
-- the same spend/impressions, so mixing them into ad_outcomes would
-- double-count every pooled number (calibration, ad library, ledger).
-- This table answers "which audience responds for me"; ad_outcomes stays
-- the single source of truth for totals.
--
-- Feeds: the Ad Library's By-audience analytics, segment-level calibration
-- (age bands map onto the simulator's gen_z/millennials/gen_x/boomers
-- segments), and P3c population conditioning.
--
-- Requires 0007 (is_workspace_member). Apply after it. Safe to re-run.

create table if not exists public.ad_breakdowns (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  company_id    uuid references public.companies(id) on delete cascade,
  provider      text,                 -- 'meta' | 'tiktok' | ...
  ad_name       text,
  campaign_name text,
  adset_name    text,
  platform      text,                 -- meta_facebook | meta_instagram | ...
  window_start  date,
  window_end    date,
  age           text,                 -- platform's band, e.g. '25-34'
  gender        text,                 -- 'male' | 'female' | 'unknown'
  impressions   bigint,
  clicks        bigint,
  spend         numeric,
  conversions   numeric,
  revenue       numeric,
  created_at    timestamptz not null default now()
);

create index if not exists breakdowns_company_idx
  on public.ad_breakdowns(company_id, age, gender);
create index if not exists breakdowns_ad_idx
  on public.ad_breakdowns(company_id, ad_name);

alter table public.ad_breakdowns enable row level security;
drop policy if exists ad_breakdowns_member on public.ad_breakdowns;
create policy ad_breakdowns_member on public.ad_breakdowns
  for all to authenticated
  using (user_id = auth.uid()
         or (company_id is not null and public.is_workspace_member(company_id)))
  with check (user_id = auth.uid()
         or (company_id is not null and public.is_workspace_member(company_id)));
