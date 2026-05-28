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
} from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text || res.statusText}`);
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
  researchCompany: (payload: { url?: string; description?: string; geo?: string }) =>
    request<ResearchProposal>('/api/research-company', {
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
    const res = await fetch('/api/upload', { method: 'POST', body: fd });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Upload failed (${res.status}): ${text || res.statusText}`);
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
};
