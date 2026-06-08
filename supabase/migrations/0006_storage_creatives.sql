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
