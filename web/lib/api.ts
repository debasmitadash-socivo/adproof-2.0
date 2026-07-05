// Fetch wrapper — proxied through Next.js to FastAPI on :8000.
import type {
  AudienceMatch,
  BenchmarkRefreshResponse,
  CompanyProfile,
  Platform,
  MarketContextResponse,
  PolicyCheckResponse,
  ResearchProposal,
  SimulateRequest,
  SimulateResponse,
  UploadResponse,
  IngestResult,
  ProviderHealthSnapshot,
  ConnectorProvider,
  CompanyIntel,
  LabRunResult,
  MetaInterest,
} from './types';

// Plain-English explanation for infrastructure / HTTP errors that don't carry
// a FastAPI {detail}. So the UI always shows words, never a bare "502".
export function friendlyHttpError(status: number, fallback = ''): string {
  switch (status) {
    case 502:
    case 503:
      return `The server was briefly unavailable — usually a quick restart or a heavy job finishing. Wait a few seconds and try again.`;
    case 504:
      return `That took too long and timed out. Try again — with fewer variants or a smaller budget if it was a big run.`;
    case 500:
      return `Something went wrong on our end while processing that. Try again; if it keeps happening the run hit an unexpected error.`;
    case 429:
      return `Too many requests in a short window — give it a moment, then try again.`;
    case 413:
      return `That file or request was too large (max 25 MB). Try a smaller file.`;
    case 401:
    case 403:
      return `You're not signed in, or not allowed to do that — try signing in again.`;
    case 404:
      return `We couldn't find what that request was pointing at.`;
    default:
      return fallback || `Request failed (error ${status}). Please try again.`;
  }
}

// Pull a FastAPI {detail} (our own plain-English errors) from a response body.
function fastapiDetail(text: string): string {
  try {
    const body = JSON.parse(text);
    if (body?.detail) {
      return typeof body.detail === 'string' ? body.detail : (body.detail.message || '');
    }
  } catch { /* response wasn't JSON */ }
  return '';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init });
  } catch {
    throw new Error(`Couldn't reach the server — check your connection and try again.`);
  }
  if (!res.ok) {
    const text = await res.text();
    // Prefer our own plain-English detail; otherwise translate the status code.
    throw new Error(fastapiDetail(text) || friendlyHttpError(res.status, res.statusText));
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{
    ok: boolean; llm: boolean;
    anthropic: boolean; openai: boolean; gemini: boolean; groq: boolean;
    mistral: boolean; openrouter: boolean; xai: boolean; together: boolean;
    version: string;
  }>('/api/healthz'),
  platforms: () => request<{ platforms: Platform[] }>('/api/platforms'),
  // Simulation Lab: lightweight numeric-only engine run (no LLM/vision).
  labRun: (payload: {
    platform_id: string; format_id: string; objective: string;
    budget: number; days: number; daily_reach: number; n_runs?: number;
    segment: string; creative_quality: number;
    target_ctr?: number | null; cpm_override?: number | null;
    target_conversion_rate?: number | null; aov?: number | null;
    fatigue_per_exposure?: number | null; reachable_audience?: number | null;
    audience_mix?: { age: string; gender: string; share: number }[] | null;
    currency?: string;
  }) =>
    request<LabRunResult>('/api/lab/run', {
      method: 'POST', body: JSON.stringify(payload),
    }),
  providerHealth: () => request<ProviderHealthSnapshot>('/api/admin/provider-health'),
  pingProviders: () =>
    request<ProviderHealthSnapshot & { results: { provider: string; status: string; reason?: string }[] }>(
      '/api/admin/ping-providers', { method: 'POST' }),
  parseCompany: (description: string) =>
    request<CompanyProfile>('/api/parse-company', {
      method: 'POST',
      body: JSON.stringify({ description }),
    }),
  matchAudience: (description: string) =>
    request<AudienceMatch>('/api/match-audience', {
      method: 'POST',
      body: JSON.stringify({ description }),
    }),
  suggestAudience: (payload: {
    company_description?: string; industry?: string; product_category?: string;
    business_model?: string; value_proposition?: string; conversion_goal?: string;
    platform_id: string;
    available_chips: { id: string; label: string; group: string }[];
  }) =>
    request<{
      selected_chip_ids: string[]; custom_interests: string[];
      gender: 'all' | 'women' | 'men'; rationale: string;
      audience_name: string; source: string;
    }>('/api/suggest-audience', { method: 'POST', body: JSON.stringify(payload) }),
  researchCompany: (payload: { url?: string; description?: string; geo?: string }) =>
    request<ResearchProposal>('/api/research-company', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  // Deep one-shot intake: full profile + economics w/ competitor prices +
  // brand color/logo from the real site + researched smart audiences.
  companyIntel: (payload: { url?: string; description?: string; geo?: string }) =>
    request<CompanyIntel>('/api/company-intel', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  marketContext: (payload: { geo: string; industry?: string; product?: string; company_description?: string }) =>
    request<MarketContextResponse>('/api/market-context', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  simulate: (req: SimulateRequest) =>
    request<SimulateResponse>('/api/simulate', {
      method: 'POST',
      body: JSON.stringify(req),
    }),
  upload: async (file: File): Promise<UploadResponse> => {
    const fd = new FormData();
    fd.append('file', file);
    let res: Response;
    try {
      res = await fetch('/api/upload', { method: 'POST', body: fd });
    } catch {
      throw new Error(`Couldn't reach the server to upload — check your connection and try again.`);
    }
    if (!res.ok) {
      const text = await res.text();
      throw new Error(fastapiDetail(text) || friendlyHttpError(res.status, res.statusText));
    }
    return res.json();
  },
  // Multi-platform connector registry — which platforms exist, what
  // credentials each needs, how gated its access is. UI renders from this.
  connectionProviders: () =>
    request<{ providers: ConnectorProvider[] }>('/api/connections/providers'),
  // Live targeting-interest search (Meta today) — same options Ads Manager
  // shows, with audience sizes. Used by the audience builder.
  searchInterests: (payload: { provider: string; credentials: Record<string, string>; q: string }) =>
    request<{ interests: MetaInterest[] }>('/api/connections/interests', {
      method: 'POST', body: JSON.stringify(payload),
    }),
  // Verify credentials read-only (one cheap GET against the platform).
  testConnection: (payload: { provider: string; credentials: Record<string, string> }) =>
    request<{ ok: boolean; detail: string; account_name?: string | null; currency?: string | null }>(
      '/api/connections/test', { method: 'POST', body: JSON.stringify(payload) }),
  // Live ad-account pull (read-only): returns the same shape as ingestOutcomes
  // so the data page renders calibration + backtest + fatigue identically.
  syncConnection: (payload: {
    provider: string; credentials: Record<string, string>;
    since: string; until: string;
    segment?: 'general' | 'b2b_saas'; currency?: string;
  }) =>
    request<IngestResult>('/api/connections/sync', {
      method: 'POST', body: JSON.stringify(payload),
    }),
  ingestOutcomes: async (file: File, segment: 'general' | 'b2b_saas' = 'general', platform = 'auto'): Promise<IngestResult> => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('segment', segment);   // tags fatigue thresholds (B2B fatigues sooner)
    fd.append('platform', platform); // which ad platform this export is from (calibration isolation)
    let res: Response;
    try {
      res = await fetch('/api/ingest-outcomes', { method: 'POST', body: fd });
    } catch {
      throw new Error(`Couldn't reach the server to read that file — check your connection and try again.`);
    }
    if (!res.ok) {
      const text = await res.text();
      throw new Error(fastapiDetail(text) || friendlyHttpError(res.status, res.statusText));
    }
    return res.json();
  },
  setApiKeys: (keys: {
    anthropic_key?: string; openai_key?: string;
    gemini_key?: string; groq_key?: string;
    mistral_key?: string; openrouter_key?: string;
    xai_key?: string; together_key?: string;
  }) =>
    request<{
      updated: string[]; llm: boolean;
      anthropic: boolean; openai: boolean; gemini: boolean; groq: boolean;
      mistral: boolean; openrouter: boolean; xai: boolean; together: boolean;
    }>('/api/settings/api-keys',
      { method: 'POST', body: JSON.stringify(keys) }),
  testLlm: () =>
    request<{
      ok: boolean;
      provider?: string;
      model?: string;
      echo?: string;
      reason?: string;
      anthropic_key_set?: boolean;
      openai_key_set?: boolean;
      gemini_key_set?: boolean;
    }>('/api/settings/test-llm', { method: 'POST' }),
  refreshBenchmarks: (format_id: string, industry?: string, geo?: string) =>
    request<BenchmarkRefreshResponse>('/api/benchmarks/refresh', {
      method: 'POST', body: JSON.stringify({ format_id, industry, geo }),
    }),
  policyCheck: (payload: {
    platform_id: string; format_id: string;
    headline?: string; primary_text?: string; description?: string;
    cta?: string; link?: string; industry?: string; geo?: string;
  }) =>
    request<PolicyCheckResponse>('/api/policy-check', {
      method: 'POST', body: JSON.stringify(payload),
    }),
  // -------- Pillars E + F: Blotato MCP wrappers ------------------------
  blotatoStatus: () => request<{ enabled: boolean }>('/api/blotato/status'),
  blotatoTemplates: () =>
    request<{ templates: { id: string; description: string }[] }>(
      '/api/blotato/templates'),
  blotatoGenerateVariants: (payload: {
    template_id?: string;
    variables?: Record<string, unknown>;
    count?: number;
    wait?: boolean;
  }) =>
    request<{
      template_id: string;
      variants: {
        status: string;
        visual_id?: string;
        result?: Record<string, unknown>;
        error?: string;
      }[];
    }>('/api/blotato/generate-variants', {
      method: 'POST', body: JSON.stringify(payload),
    }),
  blotatoExtractSource: (payload: {
    url?: string;
    text?: string;
    wait?: boolean;
  }) =>
    request<{
      status: string;
      source_id?: string;
      result?: Record<string, unknown>;
      error?: string;
    }>('/api/blotato/extract-source', {
      method: 'POST', body: JSON.stringify(payload),
    }),
};
