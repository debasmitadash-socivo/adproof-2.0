// Supabase data-access layer. CRUD for the persisted entities, RLS-scoped to
// the logged-in user (the browser client carries the auth cookie, so
// `user_id = auth.uid()` is enforced server-side — we still set user_id on
// insert so the WITH CHECK policy passes).
//
// Every function returns null/[] gracefully if Supabase isn't configured, so
// the app keeps working (localStorage) when the DB layer is unavailable.
import { getSupabase } from './supabase';
import type {
  SavedCampaign, SavedVariantResult, SavedAudience, CompanyProfile,
  SimulateResponse, SimulateRequest, AccountCalibration, Backtest,
} from './types';

async function uid(): Promise<string | null> {
  const sb = getSupabase();
  if (!sb) return null;
  const { data } = await sb.auth.getUser();
  return data.user?.id ?? null;
}

// ---------------------------------------------------------------- companies
export async function saveCompany(p: CompanyProfile): Promise<void> {
  const sb = getSupabase(); const user_id = await uid();
  if (!sb || !user_id) return;
  const row = {
    user_id,
    name: p.company_name, raw_description: p.raw_description,
    industry: p.industry, business_model: p.business_model,
    product_category: p.product_category, value_proposition: p.value_proposition,
    target_customer_summary: p.target_customer_summary,
    price_position: p.price_position, brand_tone: p.brand_tone,
    website: p.website ?? null, location: p.location ?? null,
    currency: p.currency ?? 'GBP', avg_order_value: p.avg_order_value ?? null,
    product_price: p.product_price ?? null, source: p.source,
  };
  const { data: existing } = await sb.from('companies')
    .select('id').eq('user_id', user_id).order('created_at', { ascending: false }).limit(1);
  if (existing && existing.length) {
    await sb.from('companies').update(row).eq('id', existing[0].id);
  } else {
    await sb.from('companies').insert(row);
  }
}

export async function getCompany(): Promise<CompanyProfile | null> {
  const sb = getSupabase(); if (!sb) return null;
  const { data } = await sb.from('companies')
    .select('*').order('created_at', { ascending: false }).limit(1).maybeSingle();
  if (!data) return null;
  return {
    raw_description: data.raw_description ?? '', company_name: data.name ?? '',
    industry: data.industry ?? '', business_model: data.business_model ?? '',
    product_category: data.product_category ?? '', value_proposition: data.value_proposition ?? '',
    target_customer_summary: data.target_customer_summary ?? '',
    price_position: data.price_position ?? '', brand_tone: data.brand_tone ?? '',
    source: (data.source ?? 'empty') as CompanyProfile['source'],
    website: data.website ?? undefined, location: data.location ?? undefined,
    avg_order_value: data.avg_order_value ?? undefined,
    product_price: data.product_price ?? undefined, currency: data.currency ?? undefined,
  };
}

// ---------------------------------------------------------------- audiences
export async function listAudiences(): Promise<SavedAudience[]> {
  const sb = getSupabase(); if (!sb) return [];
  const { data } = await sb.from('audiences').select('*').order('created_at', { ascending: false });
  return (data ?? []).map((d) => ({
    id: d.id, name: d.name, description: d.description ?? '', segment: d.segment ?? '',
    createdAt: new Date(d.created_at).getTime(), usedInCount: d.used_in_count ?? 0,
  }));
}

export async function saveAudience(a: SavedAudience): Promise<void> {
  const sb = getSupabase(); const user_id = await uid();
  if (!sb || !user_id) return;
  await sb.from('audiences').upsert({
    id: a.id, user_id, name: a.name, description: a.description,
    segment: a.segment, used_in_count: a.usedInCount,
  });
}

export async function deleteAudience(id: string): Promise<void> {
  const sb = getSupabase(); if (!sb) return;
  await sb.from('audiences').delete().eq('id', id);
}

// ---------------------------------------------------------------- campaigns
function variantRows(c: SavedCampaign, user_id: string) {
  const vs: SavedVariantResult[] = c.variants && c.variants.length
    ? c.variants
    : [{
        label: 'A', headline: c.name, thumbnailUrl: c.thumbnailUrl,
        result: c.result, roasP50: c.roasP50, roiP50: c.roiP50,
        ctrPct: c.ctrPct, verdictClass: c.verdictClass,
      }];
  return vs.map((v, i) => ({
    user_id, label: v.label, headline: v.headline, thumbnail_url: v.thumbnailUrl,
    roas_p50: v.roasP50, roi_p50: v.roiP50, ctr_pct: v.ctrPct,
    verdict_class: v.verdictClass, result: v.result as unknown,
    original_request: (c.originalRequests?.[i] ?? null) as unknown,
  }));
}

export async function saveCampaign(c: SavedCampaign): Promise<string | null> {
  const sb = getSupabase(); const user_id = await uid();
  if (!sb || !user_id) return null;
  // Upsert by the client-generated UUID so the browser and DB share one id
  // and re-saves (e.g. re-runs) don't duplicate.
  const { error } = await sb.from('campaigns').upsert({
    id: c.id,
    user_id, name: c.name, platform_name: c.platformName, format_name: c.formatName,
    audience_label: c.audienceLabel, budget: c.budget, days: c.days,
    roas_p50: c.roasP50, roi_p50: c.roiP50, ctr_pct: c.ctrPct,
    verdict_class: c.verdictClass, thumbnail_url: c.thumbnailUrl,
    market_context: (c.marketContext ?? null) as unknown,
    rerun_of_id: c.rerunOfId ?? null,
  });
  if (error) { console.error('[db] saveCampaign', error.message); return null; }
  // Replace variants for this campaign (delete + insert keeps it idempotent).
  await sb.from('campaign_variants').delete().eq('campaign_id', c.id);
  const rows = variantRows(c, user_id).map((r) => ({ ...r, campaign_id: c.id }));
  await sb.from('campaign_variants').insert(rows);
  return c.id;
}

export async function listCampaigns(): Promise<SavedCampaign[]> {
  const sb = getSupabase(); if (!sb) return [];
  const { data: camps } = await sb.from('campaigns')
    .select('*').order('created_at', { ascending: false });
  if (!camps || !camps.length) return [];
  const { data: vars } = await sb.from('campaign_variants')
    .select('*').in('campaign_id', camps.map((c) => c.id));
  const byCampaign = new Map<string, SavedVariantResult[]>();
  for (const v of vars ?? []) {
    const list = byCampaign.get(v.campaign_id) ?? [];
    list.push({
      label: v.label, headline: v.headline, thumbnailUrl: v.thumbnail_url,
      result: v.result as SimulateResponse, roasP50: v.roas_p50,
      roiP50: v.roi_p50, ctrPct: v.ctr_pct, verdictClass: v.verdict_class,
    });
    byCampaign.set(v.campaign_id, list);
  }
  return camps.map((c) => {
    const variants = (byCampaign.get(c.id) ?? []).sort((a, b) => a.label.localeCompare(b.label));
    return {
      id: c.id, name: c.name, createdAt: new Date(c.created_at).getTime(),
      platformName: c.platform_name, formatName: c.format_name,
      audienceLabel: c.audience_label, budget: c.budget, days: c.days,
      roasP50: c.roas_p50, roiP50: c.roi_p50, ctrPct: c.ctr_pct,
      verdictClass: c.verdict_class, thumbnailUrl: c.thumbnail_url,
      result: variants[0]?.result as SimulateResponse,
      variants: variants.length > 1 ? variants : undefined,
      marketContext: c.market_context ?? null, rerunOfId: c.rerun_of_id ?? undefined,
    };
  });
}

export async function deleteCampaign(id: string): Promise<void> {
  const sb = getSupabase(); if (!sb) return;
  await sb.from('campaigns').delete().eq('id', id);   // variants cascade
}

// ---------------------------------------------------------- ad_outcomes (Path B)
// Only these columns exist on the table; ingest rows carry extras (placement,
// real_ctr, …) we must not send.
const OUTCOME_COLS = [
  'ad_name', 'date_start', 'date_end', 'platform', 'format', 'spend',
  'impressions', 'clicks', 'conversions', 'revenue', 'ad_copy', 'audience',
  'creative_url', 'test_group', 'conversion_type', 'objective', 'currency',
  'geo', 'product_price',
];

function isoDate(v: unknown): string | null {
  if (!v) return null;
  const s = String(v).slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : null;
}

export async function insertOutcomes(rows: Record<string, unknown>[], sourceFile?: string): Promise<number> {
  const sb = getSupabase(); const user_id = await uid();
  if (!sb || !user_id || !rows.length) return 0;
  const clean = rows.map((r) => {
    const o: Record<string, unknown> = { user_id, source_file: sourceFile ?? null };
    for (const c of OUTCOME_COLS) if (r[c] !== undefined) o[c] = r[c];
    o.date_start = isoDate(r.date_start);
    o.date_end = isoDate(r.date_end);
    return o;
  });
  let inserted = 0;
  for (let i = 0; i < clean.length; i += 500) {        // batch large exports
    const { data, error } = await sb.from('ad_outcomes').insert(clean.slice(i, i + 500)).select('id');
    if (error) { console.error('[db] insertOutcomes', error.message); break; }
    inserted += data?.length ?? 0;
  }
  return inserted;
}

// ---------------------------------------------------------- calibrations (Path B)
export async function saveCalibration(
  cal: AccountCalibration, nAds: number, backtest?: Backtest, sourceFile?: string,
): Promise<void> {
  const sb = getSupabase(); const user_id = await uid();
  if (!sb || !user_id) return;
  const { error } = await sb.from('calibrations').insert({
    user_id, scope: 'account', params: cal as unknown, n_ads: nAds,
    backtest: { ...(backtest ?? {}), source_file: sourceFile ?? null } as unknown,
  });
  if (error) console.error('[db] saveCalibration', error.message);
}

export async function getLatestCalibration(): Promise<AccountCalibration | null> {
  const sb = getSupabase(); if (!sb) return null;
  const { data } = await sb.from('calibrations').select('params')
    .eq('scope', 'account').order('created_at', { ascending: false }).limit(1).maybeSingle();
  return (data?.params as AccountCalibration) ?? null;
}
