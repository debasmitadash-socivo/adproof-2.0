// Shapes mirrored from the Python backend.

export interface CompanyProfile {
  id?: string;                  // DB id — present once persisted (the workspace id)
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
  // Onboarding overhaul: richer fields that genuinely move the forecast.
  usps?: string[];                          // top 3 unique selling points
  conversion_goal?: 'purchase' | 'lead' | 'demo' | 'signup' | 'awareness';
  sales_cycle?: 'impulse' | 'considered' | 'long' | 'enterprise';
  brand_color?: string;                     // hex e.g. '#FF5A4D'
  // True when this workspace belongs to someone else and was shared with the
  // current user via a team invite. Client-side flag only — never persisted.
  shared?: boolean;
}

// ---- Deep company intelligence (/api/company-intel) -----------------------
// One-shot researched understanding of a business: profile + economics with
// competitor context + brand + smart audiences mapped to the simulator's
// real segment/interest taxonomy. Always a PROPOSAL the user can edit.
export interface SmartAudience {
  name: string;
  description: string;           // one targeting sentence (feeds the matcher)
  segment: string;               // one of the 9 simulator segments
  interests: string[];           // subset of the 12 interest buckets
  gender: 'all' | 'women' | 'men';
  age_range: string;
  rationale: string;
}
export interface CompanyIntel {
  profile: Partial<CompanyProfile> & { target_customer_summary?: string };
  economics: {
    estimated_avg_order_value?: number;
    currency?: string;
    location?: string;
    competitor_context?: { name: string; price_note: string }[];
    price_range_low?: number;
    price_range_high?: number;
    confidence?: 'low' | 'medium' | 'high';
    reasoning?: string;
  };
  brand: { brand_color_hex?: string | null; logo_url?: string | null; color_source?: string };
  audiences: SmartAudience[];
  site_fetched: boolean;
  grounded?: boolean;            // false = web search was rate-limited, site-only
  model: string;
  sources: { title: string; uri: string }[];
  disclaimer: string;
}

// ---- Simulation Lab (/api/lab/run) ----------------------------------------
export interface LabBand { p10: number; p50: number; p90: number }
export interface LabEvent { day: number; kind: 'reach' | 'click' | 'convert' | 'wom' | 'fatigue' | 'summary'; text: string }
export interface MetaInterest {
  id: string; name: string; path?: string; topic?: string | null;
  audience_size_lower?: number | null; audience_size_upper?: number | null;
}
export interface LabRunResult {
  events?: LabEvent[];
  kpis: {
    impressions: number;
    ctr: number;                 // fraction
    cpm: number | null;
    spend: number;
    clicks: LabBand;
    conversions: LabBand;
    revenue: LabBand;
    roas: LabBand;
    reach_agents: number;
  };
  daily: { day: number; clicks: Record<string, number>; conversions: Record<string, number> }[];
  factors: Record<string, number>;
  // cells: per-agent "age|gender" labels — powers the Living Market view.
  timeline: { agents: number; days: number; frames: string[]; cells?: string[] };
  saturation: Record<string, unknown> | null;
  meta: {
    n_runs: number; sim_days: number; channel: string;
    audience_personas: number; segment: string;
    audience_source?: string;
    creative: string; fatigue_source: string;
  };
}

// ---- Platform connections (multi-platform live data pulls) ---------------
// Mirrors the backend connector registry (src/connectors PROVIDERS).
export interface ConnectorField {
  key: string;
  label: string;
  secret: boolean;
  placeholder?: string;
  help_url?: string;
  optional?: boolean;
}
export interface ConnectorProvider {
  id: string;                       // 'meta' | 'tiktok' | 'google' | 'linkedin' | 'reddit' | 'x'
  label: string;
  platforms: string[];
  access: 'ready' | 'gated';
  access_note: string;
  sync: boolean;                    // false = connection verify only (X, for now)
  fields: ConnectorField[];
  how_to: string[];
}
// One saved connection (platform_connections row), workspace-scoped.
export interface PlatformConnection {
  id: string;
  companyId: string;
  provider: string;
  label: string | null;             // account name from the verify call
  credentials: Record<string, string>;
  accountRef: string | null;
  status: 'unverified' | 'ok' | 'error';
  statusNote: string | null;
  lastSyncedAt: number | null;
  createdAt: number;
}

// One row of a workspace's team roster (company_members). The owner isn't
// listed here — ownership lives on companies.user_id.
export interface WorkspaceMember {
  id: string;
  companyId: string;
  userId: string | null;         // null until the invite is claimed
  email: string;
  status: 'invited' | 'active';
  createdAt: number;
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
  jurisdiction?: string;
  regulator?: string;
  summary: string;
  overall_risk: 'low' | 'medium' | 'high' | 'unknown';
  policy_source_url: string;
  policies_consulted_year: string;
  issues: PolicyIssue[];
  grounding_sources: { title: string; uri: string }[];
}

// Market & cultural context (Phase 2) — grounded culture/season/recent-events.
export interface MarketContextResponse {
  geo: string;
  industry: string;
  as_of: string;
  cached: boolean;
  model: string;
  context: {
    cultural_notes?: string[];
    seasonality?: { current_window?: string; advice?: string };
    recent_events?: { event: string; use_as: 'leverage' | 'landmine'; note: string }[];
    overall?: string;
  };
  sources: { title: string; uri: string }[];
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

// Live LLM/vision provider health — quota-exhaustion + liveness telemetry.
export interface ProviderHealthEvent {
  ts: number;
  provider: string;
  model: string;
  kind: 'ok' | 'quota' | 'error';
  reason: string;
}
export interface ProviderHealthSummary {
  provider: string;
  last_ok_ts: number | null;
  last_error_ts: number | null;
  last_error_kind: 'quota' | 'error' | null;
  last_error_reason: string;
  ok_count: number;
  quota_count: number;
  error_count: number;
  exhausted_models: string[];
}
export interface ProviderHealthSnapshot {
  keys: Record<string, boolean>;
  events: ProviderHealthEvent[];
  summary: Record<string, ProviderHealthSummary>;
  now: number;
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
  // Per-account calibration (Path B): the user's REAL CTR / CPM override the
  // generic format benchmarks when they've uploaded their ad history.
  target_ctr?: number | null;
  cpm_override?: number | null;
  // Pillar B / B+: which calibration layer fed the anchor (so the report can
  // be honest about whether this is segment-interest- / segment- / interest-
  // / platform- / overall-calibrated).
  calibration_source?: string | null;       // 'segment:<seg>:interest:<int>' | 'segment:<seg>' | 'interest:<int>' | 'platform:<plat>' | 'overall' | null
  calibration_n_ads?: number | null;
  // Honest-ROAS: picks the cited industry CVR range when uncalibrated.
  conversion_goal?: string | null;
  // Pillar B+: the user-chosen interests after wizard mapping to the
  // canonical taxonomy (see outcomes.INTEREST_BUCKETS).
  interests?: string[];
  // Opt-in budget saturation (assumption-based): realistically reachable people.
  reachable_audience?: number | null;
}

// ---------- Path B: real-data ingest + per-account calibration ----------
export interface PlatformCalibration {
  n_ads: number;
  impressions: number;
  real_ctr: number | null;
  real_cpm: number | null;
  real_cpc: number | null;
  real_cvr: number | null;
  real_roas: number | null;
  confidence: 'low' | 'medium' | 'high';
}
export interface CalibrationTrend {
  older_ctr: number;
  recent_ctr: number;
  change_pct: number;
  direction: 'up' | 'down' | 'flat';
}
export interface AccountCalibration {
  currency: string;
  overall: Partial<PlatformCalibration>;
  by_platform: Record<string, PlatformCalibration>;
  // Pillar B: per-audience-segment calibration when the upload carried
  // audience hints. Keys are the simulator's AUDIENCE_SEGMENTS slugs
  // (gen_z, millennials, gen_x, boomers, high_income, budget_conscious,
  // early_adopters, socially_influenced, all). Segments are only present
  // when ≥3 ads + ≥5k impressions matched; lower coverage falls back to
  // by_platform → overall.
  by_segment?: Record<string, PlatformCalibration>;
  // Pillar B+: flat by-interest aggregation (when the upload carries
  // interest hints but no audience info). Used by the anchor chain
  // when segment can't be matched but a clean interest cell exists.
  by_interest?: Record<string, PlatformCalibration>;
  // Pillar B+: the (segment × interest) cross-tab — the actual answer
  // to "which audience+interest combo wins for me". Surfaced on the
  // data page as a "What's working" matrix.
  by_segment_interest?: Record<string, Record<string, PlatformCalibration>>;
  // Count of rows that couldn't be tagged to a segment / interest —
  // surfaces in UI as honest coverage info.
  by_segment_unknown?: number;
  by_interest_unknown?: number;
  usable: boolean;
  window?: string;
  trend?: CalibrationTrend | null;
  // P3b: auction-layer params fitted from the account's own daily data.
  auction?: {
    cpm_seasonality: {
      usable: boolean;
      factors: Record<string, number>;   // month (1-12) -> CPM multiplier
      n_ads: number;
      months_covered: number;
      reason?: string | null;
    };
    fatigue: {
      usable: boolean;
      lambda_per_exposure: number | null;  // logit decay per extra exposure
      n_ads: number;
      reason?: string | null;
    };
  };
}
export interface Backtest {
  usable: boolean;
  reason?: string;
  n_train?: number;
  n_test?: number;
  split?: string;
  metric?: string;
  median_abs_pct_error?: number;
  within_20pct?: number;
  within_30pct?: number;
  agg_predicted_ctr?: number;
  agg_actual_ctr?: number;
  agg_abs_pct_error?: number | null;
  note?: string;
}
export interface IngestReport {
  n_rows_in: number;
  n_rows_kept: number;
  currency: string;
  mapped: Record<string, string>;
  missing: string[];
  warnings: string[];
  sheet: string | null;
}
export interface FatigueAd {
  ad_name: string;
  platform: string;
  status: 'healthy' | 'warning' | 'urgent' | 'depleted';
  frequency: number | null;
  ctr_change_pct: number | null;
  impressions: number;
  reasons: string[];
}
export interface Fatigue {
  usable: boolean;
  reason?: string;
  segment: string;
  n_ads?: number;
  counts?: Record<'healthy' | 'warning' | 'urgent' | 'depleted', number>;
  needs_attention?: number;
  signals_used?: string[];
  ads?: FatigueAd[];
  note?: string;
}
export interface IngestResult {
  report: IngestReport;
  calibration: AccountCalibration;
  backtest: Backtest;
  fatigue: Fatigue;
  preview: Record<string, unknown>[];
  rows: Record<string, unknown>[];
  // Audience breakdowns (age × gender per ad) from live pulls — stored in the
  // separate ad_breakdowns table so they never double-count outcome totals.
  breakdowns?: { rows: Record<string, unknown>[]; n: number; note: string };
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
    saturation?: {
      reachable_audience: number;
      raw_impressions: number;
      effective_impressions: number;
      efficiency: number;
      est_frequency: number | null;
      assumption: boolean;
    };
  };
  insights: {
    verdict_class:
      | 'strong' | 'positive' | 'break_even' | 'underperforming'
      | 'wide_reach' | 'moderate_reach' | 'narrow_reach'
      | 'strong_engagement' | 'fair_engagement' | 'weak_engagement'
      | 'wont_run' | 'broken_creative';
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
    // Account-ban / appropriateness risk from the image (LLM only).
    ban_risk?: {
      level: 'none' | 'low' | 'medium' | 'high' | 'unknown';
      flags: string[];
      explanation: string;
    };
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
  // Phase 1: industry × platform × region benchmark context. Drawn from
  // Rival IQ 2025 (industry engagement) + Sprout 2026 (platform context).
  // null when the company couldn't be classified into a known industry.
  industry_context?: {
    industry: string;
    platform_id: string;
    geo: string;
    modelled_ctr: number;
    format_benchmark_ctr: number;
    industry_engagement?: {
      value: {
        engagement_rate: number;
        posts_per_week: number | null;
        industry: string;
        platform: string;
        data_year: number;
      };
      source: string;
      cite: string;
      notes: { metric_kind?: string; sample?: string };
    } | null;
    platform_2026?: {
      value: { platform_label: string; text: string; char_count: number };
      source: string;
      cite: string;
    } | null;
    global_2026?: {
      value: Record<string, number>;
      source: string;
      cite: string;
    } | null;
  } | null;
  // Pillar A3: which metric the grade is computed against + why. Shown
  // directly under the hero so the user always sees the grading axis.
  grading_basis?: {
    objective: 'awareness' | 'consideration' | 'conversion';
    metric: 'CPM' | 'CTR' | 'ROAS';
    explanation: string;
    change_hint: string;
  };
  // Plain-English additions surfaced by the API for the marketer view.
  plain_verdict: {
    headline: string;
    class: string;                       // widened — per-objective verdict words
    objective?: 'awareness' | 'consideration' | 'conversion';
    lead?: 'cpm' | 'ctr' | 'roas';
    roas_p50: number;
    roi_p50_pct: number;
    ctr_p50?: number;
    ctr_vs_bench_pct: number;
    cpm_p50?: number;
    cpm_vs_bench_pct?: number;
    reach_value?: number;
    break_even_chance_pct: number;
    // Honest-ROAS provenance: 'your_data' = a real conversion rate calibrated
    // this forecast; 'default_cvr' = ROAS shown as a cited scenario band.
    roas_scenarios?: {
      basis: 'your_data' | 'user_input' | 'default_cvr';
      cvr_used: number;
      n_ads?: number | null;
      source?: string;
      cvr_low?: number;
      cvr_high?: number;
      roas_low?: number;
      roas_high?: number;
    };
  };
  factor_plain: { name: string; share: number; direction: '+' | '-'; label: string }[];
  data_sources: { label: string; value: string; note: string }[];
  confidence: { level: 'medium' | 'low_medium' | 'low'; blurb: string; heuristic_count: number };
  copy_critique?: CopyCritique[];
  // Directional linguistic read (readability / density / persuasion markers).
  // Pure-Python, approximate — labelled directional in the UI, not a measured grade.
  linguistics?: {
    word_count: number;
    sentence_count: number;
    avg_words_per_sentence: number;
    avg_syllables_per_word: number;
    flesch_reading_ease: number;
    grade_level: number;
    readability_label: string;
    reading_time_seconds: number;
    persuasion_markers: Record<string, string[]>;
    persuasion_count: number;
    insights: string[];
    is_empty: boolean;
  } | null;
  // Visual Prominence (Moat Step 2): spectral-residual saliency heatmap on the
  // image creative. Honest — shows what POPS, NOT eye-tracking. null when no image.
  visual_prominence?: {
    found: boolean;
    label: string;
    overlay: string;            // JPEG data URI: heatmap overlaid on the creative
    focal_point: string;        // e.g. "top-centre"
    focal_xy_pct: [number, number];
    top_third_pct: number;
    middle_third_pct: number;
    bottom_third_pct: number;
    insight: string;
  } | null;
  // Viability gate — fatal/severe creative problems void the forecast.
  viability?: {
    runnable: boolean;
    forecast_valid: boolean;
    blockers: {
      severity: 'fatal' | 'severe';
      kind: 'policy' | 'coherence' | 'brand';
      label: string;
      detail: string;
      flags: string[];
    }[];
    headline: string;
    verdict_class: string;
  };
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
    // Plain "% vs break-even": negative = short, positive = above.
    pct_vs_breakeven?: number | null;
    // Estimated-AOV honesty: flag + soft range shown instead of fake precision.
    aov_is_estimate?: boolean;
    aov_low?: number | null;
    aov_high?: number | null;
    verdict: 'comfortable' | 'marginal' | 'shortfall' | 'unknown';
  };
  // Phase B: creative type + objective-aware advice.
  creative_advice?: {
    type: string;
    label: string;
    explanation: string;
    objective: 'awareness' | 'consideration' | 'conversion';
    advice: string[];
  } | null;
  // Phase C: talking-head script critique + rewrite (Gemini-powered).
  // null for non-video / non-talking-head creatives.
  script_critique?: {
    transcript: string;
    critique: string[];
    rewrite: string;
    rewrite_explanation: string;
    objective: string;
    provider: string;
    model: string;
    is_skipped: boolean;
    skipped_reason: string;
  } | null;
  // Session 2: Meta-specific paid critic (Socivo's KB).
  // Only present when platform_id starts with 'meta_' AND Gemini was
  // available. Focuses on offer strength + message-market-fit +
  // creative-as-targeting (the levers VIE and the LinkedIn critic
  // don't cover).
  meta_critique?: {
    scores: {
      offer_strength: number;
      message_market_fit: number;
      creative_as_targeting: number;
      hook: number;
      cta_alignment: number;
      format_execution: number;
    };
    composite: number;
    grade: string;
    explanations: Record<string, string>;
    detected_concept: string;
    recommended_concepts: { concept: string; why: string }[];
    detected_funnel_stage: string;
    intended_funnel_stage: string;
    stage_mismatch_warning: string;
    offer_no_brainer_pass: Record<string, string>;   // 6 axes Pass/Fail
    offer_issues: string[];
    copy_formula_gaps: string[];
    icp_specificity_score: number;
    icp_specificity_issues: string[];
    placement_findings: string[];
    hook_score: number;
    hook_alternatives: { hook: string; reason: string }[];
    predicted_quality_score: {
      urgency: number;     // /3
      budget: number;      // /3
      fit: number;         // /3
      total: number;       // /9
      rationale: string;
    };
    deterministic_findings: string[];
    biggest_strength: string;
    biggest_weakness: string;
    one_specific_fix: string;
    provider: string;
    model: string;
    is_skipped: boolean;
    skipped_reason: string;
  } | null;
  // Session 1: LinkedIn-specific paid critic (Socivo's KB
  // + the owner's LDA 6-dim scorecard). Only present when platform_id
  // starts with 'linkedin' AND Gemini was available.
  linkedin_critique?: {
    scores: {
      hook: number;             // /10
      body: number;             // /10
      credibility: number;      // /10
      audience_fit: number;     // /10
      cta: number;              // /10
      format_execution: number; // /10
    };
    composite: number;          // 0-10 weighted (Hook 30%, Body 20%, etc.)
    grade: string;              // A+/A/B/C/D/F/—
    explanations: Record<string, string>;
    detected_awareness_stage: string;
    intended_awareness_stage: string;
    stage_mismatch_warning: string;
    funnel_stage: string;
    // Socivo's paid-LinkedIn benchmark band for this funnel stage (B2B SaaS,
    // USD). Reference ranges, NOT a CTR prediction. BenchmarkLookup.to_dict()
    // shape; `value` is null / the object missing on older cached critiques.
    paid_benchmark?: {
      value: {
        objective: string;
        funnel_stage: string;
        ctrtlp_band: { label: string; low_pct: number; high_pct: number; note: string };
        ctrtlp_overall_avg_pct: number;
        ctrtlp_good_threshold_pct: number;
        cpm_usd: { low: number; high: number; spotlight: number };
        cpc_usd: { standard_low: number; standard_high: number; tla_low: number };
        cost_per_lead_usd: { low: number; high: number; note: string };
        roas_pct: number;
        format_ranking: { rank: number; format: string; best_for: string; efficiency: string }[];
        scope: string;
        currency: string;
      } | null;
      source: string;
      cite: string;
      found: boolean;
      notes: Record<string, string>;
    };
    detected_angle: string;
    recommended_angles: { angle: string; why: string }[];
    factual_accuracy_issues: string[];
    tone_violations: string[];
    structure_issues: string[];
    text_density_issues: string[];
    audience_fit_issues: string[];
    hook_score: number;
    hook_alternatives: { hook: string; reason: string }[];
    tla_eligible: boolean;
    tla_notes: string;
    deterministic_findings: string[];
    biggest_strength: string;
    biggest_weakness: string;
    one_specific_fix: string;
    provider: string;
    model: string;
    is_skipped: boolean;
    skipped_reason: string;
  } | null;
  // Reel Quality — VIE 8-dim short-video critic (only when a video was
  // uploaded and Gemini was available). Same call also produces hook
  // autopsy + algorithm-risk + publish verdict.
  reel_quality?: {
    scores: {
      attention: number;        // /15
      curiosity: number;        // /15
      emotion: number;          // /15
      retention: number;        // /20
      shareability: number;     // /10
      saveability: number;      // /10
      uniqueness: number;       // /10
      platform_fit: number;     // /5
    };
    composite: number;          // 0-100 (simple sum of sub-scores)
    grade: string;              // A+/A/B/C/D/F/—
    explanations: Record<string, string>;
    biggest_strength: string;
    biggest_weakness: string;
    drop_off_point: string;
    hook_score: number;         // /10
    hook_alternatives: { hook: string; reason: string }[];
    viral_pattern: string;
    algorithm_risk: Record<string, string>;   // 10 axes → Low/Medium/High
    publish_verdict: string;    // 'YES' | 'NO'
    publish_changes_required: string[];
    provider: string;
    model: string;
    is_skipped: boolean;
    skipped_reason: string;
  } | null;
  // KPI scoreboard — the plain numbers a marketer expects, with p10/p50/p90.
  kpis?: {
    currency: string;
    objective?: 'awareness' | 'consideration' | 'conversion';
    lead?: 'cpm' | 'ctr' | 'roas';
    impressions: { value: number };
    reach?: { value: number };
    cpm?: { value: number; benchmark: number };
    frequency: { value: number } | null;
    link_clicks: { p10: number; p50: number; p90: number };
    ctr: { p50: number; benchmark: number };
    conversions: { p10: number; p50: number; p90: number };
    conversion_rate: { p50: number };
    cpc: { p10: number; p50: number; p90: number };
    cost_per_result: { p50: number };
    revenue: { p10: number; p50: number; p90: number };
    roas: { p10: number; p50: number; p90: number };
    roi_pct: { p50: number };
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
  verdictClass:
    | 'strong' | 'positive' | 'break_even' | 'underperforming'
    | 'wide_reach' | 'moderate_reach' | 'narrow_reach'
    | 'strong_engagement' | 'fair_engagement' | 'weak_engagement'
    | 'wont_run' | 'broken_creative' | 'void';
}

export interface SavedCampaign {
  id: string;
  companyId?: string;            // workspace this campaign belongs to
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
  verdictClass:
    | 'strong' | 'positive' | 'break_even' | 'underperforming'
    | 'wide_reach' | 'moderate_reach' | 'narrow_reach'
    | 'strong_engagement' | 'fair_engagement' | 'weak_engagement'
    | 'wont_run' | 'broken_creative' | 'void';
  thumbnailUrl: string | null;
  result: SimulateResponse; // first variant's result (back-compat)
  variants?: SavedVariantResult[];
  // Original simulate request(s) — one per variant — so a campaign can be
  // re-run later against the latest backend (improved LLM, fresher
  // benchmarks, fixed bugs) without the user having to remember inputs.
  originalRequests?: SimulateRequest[];
  // Lineage: if this is a re-run, points to the campaign id it was cloned from.
  rerunOfId?: string;
  // Market & cultural context (Phase 2) — one grounded read per campaign.
  marketContext?: MarketContextResponse | null;
}

export interface SavedAudience {
  id: string;
  companyId?: string;            // workspace this audience belongs to
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
  source?: string;   // "socivo" for Socivo rules; absent = built-in
}
