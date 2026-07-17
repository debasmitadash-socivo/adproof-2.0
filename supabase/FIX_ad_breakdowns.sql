-- One-time fix for: ERROR 42703 "column user_id does not exist", thrown while
-- running SETUP_ALL.sql at the ad_breakdowns row-level-security policy.
--
-- CAUSE: this project has a LEFTOVER `ad_breakdowns` table from an earlier run
-- that predates the `user_id` column. Because SETUP_ALL.sql uses
-- `create table if not exists`, it skips the stale table instead of fixing it,
-- so the policy that references `user_id` fails. The Supabase SQL editor runs
-- the whole file in ONE transaction, so that single failure rolls the entire
-- script back — which is why previous runs never actually stuck.
--
-- SAFE TO DROP: `ad_breakdowns` holds only derived audience-breakdown rows
-- pulled from the ad platforms (Meta/TikTok). It contains no user-authored
-- data and is rebuilt automatically on the next sync.

-- (optional) confirm it's empty first — returns 0, or errors if already gone:
--   select count(*) from public.ad_breakdowns;

-- STEP 1 — run this file once:
drop table if exists public.ad_breakdowns cascade;

-- STEP 2 — then re-run supabase/SETUP_ALL.sql in full. It now completes
-- cleanly and recreates ad_breakdowns with the correct columns and policy.
