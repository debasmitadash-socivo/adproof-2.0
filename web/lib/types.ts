// Shapes mirrored from the Python backend.

export interface CompanyProfile {
  raw_description: string;
  company_name: string;
  industry: string;
  business_model: string;
  product_category: string;
  value_proposition: string;
  target_customer_summary: string;
  price_position: string;
  brand_tone: string;
  source: 'llm' | 'heuristic' | 'empty';
  // --- Economics + market (Phase 1). Optional so old saved profiles still parse.
  website?: string;
  location?: string;            // primary market, e.g. "UK", "US", "London"
  avg_order_value?: number;     // customer value in `currency`
  product_price?: number;
  currency?: string;            // ISO-ish: GBP | USD | EUR ...
}

// AI-proposed economics from /api/research-company — an ESTIMATE to confirm.
export interface ResearchProposal {
  proposed: {
    company_name?: string;
    industry?: string;
    business_model?: string;
    what_they_sell?: string;
    price_point?: string;
    estimated_avg_order_value?: number;
    currency?: string;
    location?: string;
    confidence?: 'low' | 'medium' | 'high';
    reasoning?: string;
  };
  model: string;
  sources: { title: string; uri: string }[];
  disclaimer: string;
}

export interface AudienceMatch {
  segment: string;
  confidence: number;
  rationale: string;
  secondary_segments: string[];
  source: 'llm' | 'heuristic';
}

export interface AdFormat {
  id: string;
  name: string;
  media_type: 'image' | 'video' | 'text' | 'carousel';
  asset_types: string[];
  benchmarks: {
    ctr: number;
    cpm: number;
    cpc: number | null;
    primary_metric: string;
    ctr_range?: [number, number];
    as_of?: string;
    source_2024?: { ctr?: number; cpm?: number; cpc?: number };
    trend_note?: string;
  };
  copy_limits: Record<string, number>;
  aspect_ratios: string[];
  best_for: string;
  tone: string;
  primary_objectives: string[];
}

export interface PolicyIssue {
  severity: 'error' | 'warning' | 'info';
  rule: string;
  rule_url?: string;
  violating_text?: string;
  explanation: string;
  fix: string;
}

export interface PolicyCheckResponse {
  platform: string;
  format: string;
  summary: string;
  overall_risk: 'low' | 'medium' | 'high' | 'unknown';
  policy_source_url: string;
  policies_consulted_year: string;
  issues: PolicyIssue[];
  grounding_sources: { title: string; uri: string }[];
}

export interface BenchmarkRefreshResponse {
  format_id: string;
  platform: string;
  format_name: string;
  stored_benchmarks: { ctr: number; cpm: number; cpc: number | null; as_of: string };
  fetched: {
    ctr?: number; cpm?: number; cpc?: number | null;
    ctr_range_low?: number; ctr_range_high?: number;
    source?: string; source_url?: string; year?: string; notes?: string;
  };
  delta_pct: { ctr: number | null; cpm: number | null };
  grounding_sources: { title: string; uri: string }[];
}

export interface Platform {
  id: string;
  name: string;
  audience_default: string;
  strength: string;
  formats: AdFormat[];
}

export interface CampaignBrief {
  objective: 'awareness' | 'consideration' | 'conversion';
  platform_id: string;
  format_id: string;
  budget: number;
  days: number;
  daily_reach: number;
  n_runs: number;
  target_conversion_rate: number;
}

export interface SimulateRequest {
  company_description: string;
  audience_description: string;
  audience_segment?: string | null;
  objective: string;
  platform_id: string;
  format_id: string;
  budget: number;
  days: number;
  daily_reach: number;
  n_runs: number;
  target_conversion_rate: number;
  // Real economics + market (Phase 1)
  avg_order_value?: number | null;
  product_price?: number | null;
  currency?: string;
  geo?: string;
  image_path?: string | null;
  video_path?: string | null;
  headline: string;
  primary_text: string;
  description: string;
  cta: string;
  link: string;
  visual_provider: 'auto' | 'claude' | 'openai' | 'heuristic';
}

export interface DistBand {
  mean: number;
  std: number;
  p10: number;
  p50: number;
  p90: number;
}

export interface SimulateResponse {
  company: CompanyProfile;
  match: AudienceMatch;
  brief: CampaignBrief;
  format: { id: string; name: string; platform: string; benchmarks: AdFormat['benchmarks'] };
  mc: {
    audience_size: number;
    n_runs: number;
    sim_days: number;
    channel: string;
    budget: number;
    total_impressions: number;
    mean_aov: number;
    sample_ctrs: number[];
    predicted_clicks: DistBand;
    predicted_conversions: DistBand;
    predicted_revenue: DistBand;
    predicted_roi: DistBand;
    predicted_roas: DistBand;
    aggregate_click_factors: Record<string, number>;
  };
  insights: {
    verdict_class: 'strong' | 'positive' | 'break_even' | 'underperforming';
    headline: string;
    one_liner: string;
    benchmark_note: string;
    headline_metrics: Record<string, number | string>;
    what_works: string[];
    what_holds_back: string[];
    recommendations: string[];
    caveats: string[];
    markdown: string;
  };
  visual: {
    scores: Record<string, number>;
    explanations: Record<string, string>;
    strengths: string[];
    weaknesses: string[];
    overall: string;
    provider: string;
    model: string;
    is_heuristic: boolean;
    brand_relevance?: number;
    brand_relevance_explanation?: string;
    brand_relevance_source?: 'llm' | 'heuristic';
    image_description?: string;
    image_copy_coherence?: number;
    image_copy_coherence_explanation?: string;
    // When a non-heuristic provider was attempted but failed (quota, bad
    // key, network) and we degraded to the heuristic, this carries the
    // underlying error so the UI can show "Gemini failed: quota exhausted"
    // instead of leaving the user guessing.
    provider_error?: string;
  } | null;
  figures: Record<string, unknown>;
  validation: { severity: 'error' | 'warning' | 'info'; message: string }[];
  headline_md: string;
  visual_md: string;
  narrative_md: string;
  // Plain-English additions surfaced by the API for the marketer view.
  plain_verdict: {
    headline: string;
    class: 'strong' | 'positive' | 'break_even' | 'underperforming';
    roas_p50: number;
    roi_p50_pct: number;
    ctr_vs_bench_pct: number;
    break_even_chance_pct: number;
  };
  factor_plain: { name: string; share: number; direction: '+' | '-'; label: string }[];
  data_sources: { label: string; value: string; note: string }[];
  confidence: { level: 'medium' | 'low_medium' | 'low'; blurb: string; heuristic_count: number };
  copy_critique?: CopyCritique[];
  // Honest channel economics (Phase 1) — break-even math on the user's real numbers.
  economics?: {
    currency: string;
    geo: string;
    avg_order_value: number;
    avg_order_value_source: string;   // "your figure" | "estimated (no figure supplied)"
    product_price?: number | null;
    conversion_rate: number;
    budget: number;
    impressions: number;
    modelled_ctr: number;
    benchmark_ctr: number;
    break_even_ctr: number | null;
    clears_break_even: boolean | null;
    headroom_x: number | null;
    verdict: 'comfortable' | 'marginal' | 'shortfall' | 'unknown';
  };
}

// ---------- locally-persisted account data ----------

export interface UserProfile {
  name: string;
  email: string;
  createdAt: number;
}

// One creative variant within a campaign.
export interface Variant {
  id: string;
  label: string;            // "A" / "B" / ...
  headline: string;
  primaryText: string;
  description: string;
  cta: string;
  link: string;
  imagePath: string | null;
  imageUrl: string | null;
  videoPath: string | null;
  videoUrl: string | null;
}

// A finished variant inside a saved multi-creative campaign.
export interface SavedVariantResult {
  label: string;
  headline: string;
  thumbnailUrl: string | null;
  result: SimulateResponse;
  roasP50: number;
  roiP50: number;
  ctrPct: number;
  verdictClass: 'strong' | 'positive' | 'break_even' | 'underperforming';
}

export interface SavedCampaign {
  id: string;
  name: string;
  createdAt: number;
  platformName: string;
  formatName: string;
  audienceLabel: string;
  budget: number;
  days: number;
  roasP50: number;          // aggregate (mean of variant ROAS)
  roiP50: number;
  ctrPct: number;
  verdictClass: 'strong' | 'positive' | 'break_even' | 'underperforming';
  thumbnailUrl: string | null;
  result: SimulateResponse; // first variant's result (back-compat)
  variants?: SavedVariantResult[];
  // Original simulate request(s) — one per variant — so a campaign can be
  // re-run later against the latest backend (improved LLM, fresher
  // benchmarks, fixed bugs) without the user having to remember inputs.
  originalRequests?: SimulateRequest[];
  // Lineage: if this is a re-run, points to the campaign id it was cloned from.
  rerunOfId?: string;
}

export interface SavedAudience {
  id: string;
  name: string;
  description: string;
  segment: string;
  createdAt: number;
  usedInCount: number;
}

export interface UploadResponse {
  path: string;
  url: string;
  filename: string;
  size: number;
  content_type: string | null;
  kind: 'image' | 'video';
}

export interface CopyCritique {
  severity: 'error' | 'warning' | 'info';
  field: 'headline' | 'primary_text' | 'description' | 'cta' | 'link' | 'copy';
  message: string;
  fix: string;
  lift_pct?: number;
}
