-- Onboarding overhaul: capture richer company info so the forecast can use it.
-- All new columns are nullable + safely-defaulted so existing rows keep working.

alter table public.companies
  add column if not exists usps            text[],
  add column if not exists conversion_goal text,   -- purchase | lead | demo | signup | awareness
  add column if not exists sales_cycle     text,   -- impulse | considered | long | enterprise
  add column if not exists brand_color     text;   -- hex string, e.g. #FF5A4D
