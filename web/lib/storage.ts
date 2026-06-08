// Tier 2 — direct browser-to-Supabase Storage uploads.
//
// Replaces the legacy /api/upload flow (Railway disk, ephemeral, wiped on
// every redeploy). Files now live in the 'ad-creatives' bucket, keyed by
// the user's auth.uid() so RLS keeps every account's files private.
//
// Returns the same UploadResponse shape the wizard already expects, so
// new/page.tsx's upload handler is a one-line swap. The `path` field is a
// durable Supabase URL (signed, 7-day expiry) the backend can fetch.
// `refreshSignedUrl()` regenerates it when an old saved campaign is
// re-run after the signature has expired.

import type { SupabaseClient } from '@supabase/supabase-js';
import { getSupabase } from './supabase';
import type { UploadResponse } from './types';

const BUCKET = 'ad-creatives';
const SIGN_TTL_SECONDS = 60 * 60 * 24 * 7;          // 7 days

const _ALLOWED_MIME = new Set([
  'image/png', 'image/jpeg', 'image/jpg', 'image/webp', 'image/gif',
  'video/mp4', 'video/quicktime', 'video/webm', 'video/x-matroska',
  'video/3gpp', 'video/x-msvideo', 'video/mpeg',
]);

function _extFor(file: File): string {
  const fromName = file.name.match(/\.([a-z0-9]+)$/i)?.[1]?.toLowerCase();
  if (fromName) return fromName;
  const map: Record<string, string> = {
    'image/png': 'png', 'image/jpeg': 'jpg', 'image/jpg': 'jpg',
    'image/webp': 'webp', 'image/gif': 'gif',
    'video/mp4': 'mp4', 'video/quicktime': 'mov', 'video/webm': 'webm',
    'video/x-matroska': 'mkv', 'video/3gpp': '3gp',
    'video/x-msvideo': 'avi', 'video/mpeg': 'mpeg',
  };
  return map[file.type] ?? 'bin';
}

function _uuid(): string {
  // crypto.randomUUID is universally available in modern browsers we ship to.
  return (globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2))
    .replace(/-/g, '');
}

async function _assertSession(sb: SupabaseClient): Promise<string> {
  const { data, error } = await sb.auth.getUser();
  if (error || !data.user) {
    throw new Error('You need to be signed in to upload a creative.');
  }
  return data.user.id;
}

/**
 * Upload a creative file to Supabase Storage and return the same shape the
 * legacy /api/upload endpoint did, so the wizard code is unchanged.
 *
 * The returned `path` is a durable, signed URL the backend will fetch when
 * the simulate pipeline runs. The `url` field is the same value — the
 * wizard's preview already accepts URLs, so the local /uploads/<file>
 * fallback is no longer needed.
 */
export async function uploadCreativeToSupabase(file: File): Promise<UploadResponse> {
  const sb = getSupabase();
  if (!sb) throw new Error('Storage client unavailable — try a hard refresh.');
  if (file.size > 25 * 1024 * 1024) {
    throw new Error('File too large (max 25 MB).');
  }
  if (file.type && !_ALLOWED_MIME.has(file.type)) {
    throw new Error(`Unsupported file type: ${file.type}`);
  }
  const userId = await _assertSession(sb);

  const ext = _extFor(file);
  const objectKey = `${userId}/${_uuid()}.${ext}`;
  const { error: upErr } = await sb.storage.from(BUCKET).upload(objectKey, file, {
    cacheControl: '3600',
    upsert: false,
    contentType: file.type || undefined,
  });
  if (upErr) {
    // Storage RLS denials surface with vague messages — make it actionable.
    throw new Error(`Upload failed: ${upErr.message}`);
  }

  const { data: signed, error: signErr } = await sb.storage
    .from(BUCKET)
    .createSignedUrl(objectKey, SIGN_TTL_SECONDS);
  if (signErr || !signed?.signedUrl) {
    throw new Error(`Couldn't sign the uploaded file: ${signErr?.message ?? 'unknown'}`);
  }

  const kind: 'image' | 'video' = (file.type || '').startsWith('video/') ? 'video' : 'image';
  return {
    path: signed.signedUrl,                  // backend pipeline gets a URL it can fetch
    url:  signed.signedUrl,                  // wizard preview
    filename: file.name,
    size: file.size,
    content_type: file.type || null,
    kind,
  };
}

/**
 * Re-issue a fresh signed URL for an existing Supabase storage object.
 * Used by Re-run on saved campaigns whose original signed URL has expired.
 *
 * The `sourceUrl` can be a previously-signed URL OR the raw object key —
 * we extract the bucket-relative key either way.
 */
export async function refreshSignedUrl(sourceUrl: string): Promise<string | null> {
  if (!sourceUrl.includes('/object/sign/' + BUCKET + '/')
      && !sourceUrl.startsWith(BUCKET + '/')
      && !/^[\w-]+\/[\w.-]+\.(mp4|mov|webm|mkv|avi|3gp|mpeg|png|jpe?g|webp|gif)$/i.test(sourceUrl)) {
    return null;                              // not one of our URLs
  }
  const sb = getSupabase();
  if (!sb) return null;
  // Extract the object key — everything after '/ad-creatives/' or the raw key.
  let key = sourceUrl;
  const m = sourceUrl.match(new RegExp('/object/sign/' + BUCKET + '/([^?]+)'));
  if (m) key = decodeURIComponent(m[1]);
  if (key.startsWith(BUCKET + '/')) key = key.slice(BUCKET.length + 1);
  const { data, error } = await sb.storage.from(BUCKET).createSignedUrl(key, SIGN_TTL_SECONDS);
  if (error || !data?.signedUrl) return null;
  return data.signedUrl;
}
