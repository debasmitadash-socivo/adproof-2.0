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
