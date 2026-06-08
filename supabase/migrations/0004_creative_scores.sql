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
