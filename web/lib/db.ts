// Supabase data-access layer. Every persisted row is RLS-scoped to the
// logged-in user, and every data row (campaigns, audiences, calibrations,
// ad_outcomes) is ALSO scoped to a workspace (`company_id`). One user can
// have N workspaces (e.g. agency managing multiple clients) — each
// workspace's calibration/audiences/campaigns stay independent.
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

// ============================== companies (workspaces) =====================
function rowToCompany(d: Record<string, unknown>): CompanyProfile {
  return {
    id: d.id as string,
    raw_description: (d.raw_description as string) ?? '',
    company_name: (d.name as string) ?? '',
    industry: (d.industry as string) ?? '',
    business_model: (d.business_model as string) ?? '',
    product_category: (d.product_category as string) ?? '',
    value_proposition: (d.value_proposition as string) ?? '',
    target_customer_summary: (d.target_customer_summary as string) ?? '',
    price_position: (d.price_position as string) ?? '',
    brand_tone: (d.brand_tone as string) ?? '',
    source: ((d.source as string) ?? 'empty') as CompanyProfile['source'],
    website: (d.website as string) ?? undefined,
    location: (d.location as string) ?? undefined,
    avg_order_value: (d.avg_order_value as number) ?? undefined,
    product_price: (d.product_price as number) ?? undefined,
    currency: (d.currency as string) ?? undefined,
    usps: (d.usps as string[]) ?? undefined,
    conversion_goal: (d.conversion_goal as CompanyProfile['conversion_goal']) ?? undefined,
    sales_cycle: (d.sales_cycle as CompanyProfile['sales_cycle']) ?? undefined,
    brand_color: (d.brand_color as string) ?? undefined,
  };
}

function companyRow(p: CompanyProfile, user_id: string) {
  return {
    user_id,
    name: p.company_name, raw_description: p.raw_description,
    industry: p.industry, business_model: p.business_model,
    product_category: p.product_category, value_proposition: p.value_proposition,
    target_customer_summary: p.target_customer_summary,
    price_position: p.price_position, brand_tone: p.brand_tone,
    website: p.website ?? null, location: p.location ?? null,
    currency: p.currency ?? 'GBP', avg_order_value: p.avg_order_value ?? null,
    product_price: p.product_price ?? null, source: p.source,
    usps: p.usps ?? null, conversion_goal: p.conversion_goal ?? null,
    sales_cycle: p.sales_cycle ?? null, brand_color: p.brand_color ?? null,
  };
}

export async function listCompanies(): Promise<CompanyProfile[]> {
  const sb = getSupabase(); if (!sb) return [];
  const { data } = await sb.from('companies').select('*')
    .eq('archived', false).order('created_at', { ascending: true });
  return (data ?? []).map(rowToCompany);
}

/** Create a brand-new workspace. Throws on failure so the caller can surface
 *  a usable error message — silent nulls leave the user staring at a dead
 *  button with no clue whether auth expired, RLS rejected, etc. */
export async function createCompany(p: CompanyProfile): Promise<string> {
  const sb = getSupabase();
  if (!sb) throw new Error('Supabase isn\'t configured. Check NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY.');
  const user_id = await uid();
  if (!user_id) throw new Error('You\'re not signed in. Sign in again to create a workspace.');
  const { data, error } = await sb.from('companies')
    .insert(companyRow(p, user_id)).select('id').single();
  if (error) throw new Error(`Couldn\'t save the workspace: ${error.message}`);
  if (!data) throw new Error('Couldn\'t save the workspace: no row returned.');
  return data.id as string;
}

/** Update an existing workspace's profile (by id). */
export async function saveCompany(p: CompanyProfile): Promise<void> {
  const sb = getSupabase(); const user_id = await uid();
  if (!sb || !user_id) return;
  if (!p.id) {
    // No id → can't update; caller should use createCompany for new workspaces.
    console.warn('[db] saveCompany: profile has no id; ignoring (use createCompany).');
    return;
  }
  const { error } = await sb.from('companies').update(companyRow(p, user_id)).eq('id', p.id);
  if (error) console.error('[db] saveCompany', error.message);
}

/** Backward-compat for code that loaded "the company": returns the first one. */
export async function getCompany(): Promise<CompanyProfile | null> {
  const list = await listCompanies();
  return list[0] ?? null;
}

// ============================== audiences ===================================
export async function listAudiences(companyId?: string): Promise<SavedAudience[]> {
  const sb = getSupabase(); if (!sb) return [];
  let q = sb.from('audiences').select('*').order('created_at', { ascending: false });
  if (companyId) q = q.eq('company_id', companyId);
  const { data } = await q;
  return (data ?? []).map((d) => ({
    id: d.id, companyId: d.company_id ?? undefined, name: d.name,
    description: d.description ?? '', segment: d.segment ?? '',
    createdAt: new Date(d.created_at).getTime(), usedInCount: d.used_in_count ?? 0,
  }));
}

export async function saveAudience(a: SavedAudience): Promise<void> {
  const sb = getSupabase(); const user_id = await uid();
  if (!sb || !user_id) return;
  await sb.from('audiences').upsert({
    id: a.id, user_id, company_id: a.companyId ?? null,
    name: a.name, description: a.description,
    segment: a.segment, used_in_count: a.usedInCount,
  });
}

export async function deleteAudience(id: string): Promise<void> {
  const sb = getSupabase(); if (!sb) return;
  await sb.from('audiences').delete().eq('id', id);
}

// ============================== campaigns ===================================
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
  const { error } = await sb.from('campaigns').upsert({
    id: c.id,
    user_id, company_id: c.companyId ?? null,
    name: c.name, platform_name: c.platformName, format_name: c.formatName,
    audience_label: c.audienceLabel, budget: c.budget, days: c.days,
    roas_p50: c.roasP50, roi_p50: c.roiP50, ctr_pct: c.ctrPct,
    verdict_class: c.verdictClass, thumbnail_url: c.thumbnailUrl,
    market_context: (c.marketContext ?? null) as unknown,
    rerun_of_id: c.rerunOfId ?? null,
  });
  if (error) { console.error('[db] saveCampaign', error.message); return null; }
  await sb.from('campaign_variants').delete().eq('campaign_id', c.id);
  const rows = variantRows(c, user_id).map((r) => ({ ...r, campaign_id: c.id }));
  await sb.from('campaign_variants').insert(rows);

  // Pillar C: stamp one creative_scores row per variant for the future
  // per-account creative->CTR model. Best-effort — never block the
  // campaign save on this.
  try {
    await persistCreativeScores(c, user_id);
  } catch (e) {
    console.error('[db] persistCreativeScores', e);
  }

  return c.id;
}

// ============================== Pillar C: creative_scores ==================
// Banks every forecast's creative + scores + headline for the future
// per-account learned model. Joined later against ad_outcomes by
// (user_id, creative_url) to fit predicted-vs-actual per account.

async function persistCreativeScores(
  c: SavedCampaign, user_id: string,
): Promise<void> {
  const sb = getSupabase(); if (!sb) return;
  const vs: SavedVariantResult[] = c.variants && c.variants.length
    ? c.variants
    : [{
        label: 'A', headline: c.name, thumbnailUrl: c.thumbnailUrl,
        result: c.result, roasP50: c.roasP50, roiP50: c.roiP50,
        ctrPct: c.ctrPct, verdictClass: c.verdictClass,
      }];
  // Defensive: skip if all variants have no result (a draft).
  const usable = vs.filter((v) => !!v.result);
  if (!usable.length) return;

  const rows = usable.map((v, i) => {
    const r = v.result!;
    const req = c.originalRequests?.[i];
    // 7-key VisualAnalysisResult-ish shape stays in vision_scores. We add
    // ban_risk + brand_relevance + image_copy_coherence alongside the four
    // numeric scores so the row is self-describing.
    const vis = r.visual ? {
      ...r.visual.scores,
      ban_risk: r.visual.ban_risk ?? null,
      brand_relevance: r.visual.brand_relevance ?? null,
      image_copy_coherence: r.visual.image_copy_coherence ?? null,
    } : null;
    const creativeUrl = v.thumbnailUrl
      ?? req?.image_path
      ?? req?.video_path
      ?? null;
    const creativeKind = req?.video_path ? 'video'
      : req?.image_path ? 'image' : null;
    return {
      user_id,
      company_id: c.companyId ?? null,
      campaign_id: c.id,
      creative_url: creativeUrl,
      thumbnail_url: v.thumbnailUrl ?? null,
      creative_kind: creativeKind,
      ad_name: v.label,
      objective: req?.objective ?? null,
      platform_id: req?.platform_id ?? null,
      format_id: req?.format_id ?? null,
      audience_segment: req?.audience_segment ?? null,
      vision_scores: vis as unknown,
      reel_quality: (r.reel_quality ?? null) as unknown,
      forecast_ctr_p50: r.kpis?.ctr?.p50 ?? null,
      forecast_roas_p50: v.roasP50 ?? null,
      forecast_cpm_p50: r.kpis?.cpm?.value ?? null,
      verdict_class: v.verdictClass,
      visual_provider: r.visual?.provider ?? 'none',
      visual_model: r.visual?.model ?? '',
      is_heuristic: r.visual?.is_heuristic ?? false,
    };
  });
  const { error } = await sb.from('creative_scores').insert(rows);
  if (error) console.error('[db] creative_scores insert', error.message);
}

export async function listCampaigns(companyId?: string): Promise<SavedCampaign[]> {
  const sb = getSupabase(); if (!sb) return [];
  let q = sb.from('campaigns').select('*').order('created_at', { ascending: false });
  if (companyId) q = q.eq('company_id', companyId);
  const { data: camps } = await q;
  if (!camps || !camps.length) return [];
  const { data: vars } = await sb.from('campaign_variants')
    .select('*').in('campaign_id', camps.map((c) => c.id));
  // Keep the raw rows per campaign so we can rebuild BOTH the variant results
  // and the saved original requests (needed for re-run), aligned by label.
  const rowsByCampaign = new Map<string, Record<string, unknown>[]>();
  for (const v of vars ?? []) {
    const list = rowsByCampaign.get(v.campaign_id as string) ?? [];
    list.push(v);
    rowsByCampaign.set(v.campaign_id as string, list);
  }
  return camps.map((c) => {
    const rows = (rowsByCampaign.get(c.id) ?? [])
      .sort((a, b) => String(a.label ?? '').localeCompare(String(b.label ?? '')));
    const variants: SavedVariantResult[] = rows.map((v) => ({
      label: v.label as string, headline: v.headline as string,
      thumbnailUrl: (v.thumbnail_url as string) ?? null,
      result: v.result as SimulateResponse, roasP50: v.roas_p50 as number,
      roiP50: v.roi_p50 as number, ctrPct: v.ctr_pct as number,
      verdictClass: v.verdict_class as SavedVariantResult['verdictClass'],
    }));
    // Re-run inputs: one saved request per variant, aligned 1:1 with `variants`
    // (same sorted order). All-or-nothing — if any variant lacks its request we
    // can't reliably replay the set, so re-run stays disabled (undefined) rather
    // than misaligning labels/thumbnails.
    const reqs = rows.map((v) => v.original_request);
    const originalRequests = (reqs.length > 0 && reqs.every((r) => r != null))
      ? (reqs as SimulateRequest[]) : undefined;
    return {
      id: c.id, companyId: c.company_id ?? undefined,
      name: c.name, createdAt: new Date(c.created_at).getTime(),
      platformName: c.platform_name, formatName: c.format_name,
      audienceLabel: c.audience_label, budget: c.budget, days: c.days,
      roasP50: c.roas_p50, roiP50: c.roi_p50, ctrPct: c.ctr_pct,
      verdictClass: c.verdict_class, thumbnailUrl: c.thumbnail_url,
      result: variants[0]?.result as SimulateResponse,
      variants: variants.length > 1 ? variants : undefined,
      originalRequests,
      marketContext: c.market_context ?? null, rerunOfId: c.rerun_of_id ?? undefined,
    };
  });
}

export async function deleteCampaign(id: string): Promise<void> {
  const sb = getSupabase(); if (!sb) return;
  await sb.from('campaigns').delete().eq('id', id);
}

// ============================== ad_outcomes (Path B) ========================
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

export async function insertOutcomes(
  rows: Record<string, unknown>[], sourceFile?: string, companyId?: string,
): Promise<number> {
  const sb = getSupabase(); const user_id = await uid();
  if (!sb || !user_id || !rows.length) return 0;
  const clean = rows.map((r) => {
    const o: Record<string, unknown> = {
      user_id, company_id: companyId ?? null,
      source_file: sourceFile ?? null,
    };
    for (const c of OUTCOME_COLS) if (r[c] !== undefined) o[c] = r[c];
    o.date_start = isoDate(r.date_start);
    o.date_end = isoDate(r.date_end);
    return o;
  });
  let inserted = 0;
  for (let i = 0; i < clean.length; i += 500) {
    const { data, error } = await sb.from('ad_outcomes').insert(clean.slice(i, i + 500)).select('id');
    if (error) { console.error('[db] insertOutcomes', error.message); break; }
    inserted += data?.length ?? 0;
  }
  return inserted;
}

// ============================== calibrations (Path B) =======================
export async function saveCalibration(
  cal: AccountCalibration, nAds: number,
  backtest?: Backtest, sourceFile?: string, companyId?: string,
): Promise<void> {
  const sb = getSupabase(); const user_id = await uid();
  if (!sb || !user_id) return;
  const { error } = await sb.from('calibrations').insert({
    user_id, company_id: companyId ?? null,
    scope: 'account', params: cal as unknown, n_ads: nAds,
    backtest: { ...(backtest ?? {}), source_file: sourceFile ?? null } as unknown,
  });
  if (error) console.error('[db] saveCalibration', error.message);
}

export async function getLatestCalibration(companyId?: string): Promise<AccountCalibration | null> {
  const sb = getSupabase(); if (!sb) return null;
  let q = sb.from('calibrations').select('params').eq('scope', 'account')
    .order('created_at', { ascending: false }).limit(1);
  if (companyId) q = q.eq('company_id', companyId);
  const { data } = await q.maybeSingle();
  return (data?.params as AccountCalibration) ?? null;
}

/** Latest stored backtest (the accuracy proof) for a workspace, with the ad
 *  count and when it was measured. Lets the dashboard / result page show a
 *  PERSISTENT "how accurate are we on YOUR account" scorecard instead of only
 *  flashing it once at CSV-upload time. */
export async function getLatestBacktest(
  companyId?: string,
): Promise<{ backtest: Backtest; nAds: number | null; measuredAt: number | null } | null> {
  const sb = getSupabase(); if (!sb) return null;
  let q = sb.from('calibrations').select('backtest, n_ads, created_at')
    .eq('scope', 'account').order('created_at', { ascending: false }).limit(1);
  if (companyId) q = q.eq('company_id', companyId);
  const { data } = await q.maybeSingle();
  if (!data?.backtest) return null;
  return {
    backtest: data.backtest as Backtest,
    nAds: (data.n_ads as number) ?? null,
    measuredAt: data.created_at ? new Date(data.created_at as string).getTime() : null,
  };
}
