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
