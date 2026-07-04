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
