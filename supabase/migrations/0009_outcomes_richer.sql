-- Richer ad_outcomes: keep the structure + delivery fields the platforms
-- already send us but we previously threw away at save time.
--
--   campaign_name / adset_name — Meta's insights carry both on every row;
--     they power the Ad Library's group-by-campaign/ad-set views and let
--     audience tagging read ad-set names ("Gen Z fitness broad").
--   reach / frequency — needed to fit creative-fatigue from STORED history
--     (previously only available in-memory at pull time, so re-calibrating
--     from the database lost the fatigue signal).
--
-- All nullable — old rows and thin CSVs keep working untouched.
-- Apply: paste into the Supabase SQL editor and run. Safe to re-run.

alter table public.ad_outcomes
  add column if not exists campaign_name text,
  add column if not exists adset_name    text,
  add column if not exists reach         bigint,
  add column if not exists frequency     numeric;

create index if not exists outcomes_campaign_idx
  on public.ad_outcomes(company_id, campaign_name);
