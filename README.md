# AdProof

> Score every ad before you ship it. Upload a creative, pick a platform and audience, get a defensible ROAS forecast in p10–p90 bands — backed by a multimodal LLM that actually reads your image.

![status](https://img.shields.io/badge/status-v1-coral)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![node](https://img.shields.io/badge/node-20%2B-green)
![license](https://img.shields.io/badge/license-private-lightgrey)

## What it does

- **Reads your ad image** via a multimodal LLM (Gemini, Groq, Mistral, OpenRouter, xAI, Together, Claude, or GPT-4o — auto-fallback chain)
- **Forecasts** CTR / conversions / revenue / ROAS as a Monte Carlo distribution with confidence bands
- **Critiques the copy** with specific fixes (missing UTM, no urgency cues, weak CTA, etc.)
- **Checks platform policy compliance** in real time (Meta / Google / LinkedIn / TikTok) via Gemini web grounding
- **Refreshes industry benchmarks** from the live web on demand
- **Honest provenance** on every claim — labels every input as "LLM", "heuristic", or "synthetic" so you know what to trust

## Architecture

```
┌──────────── Next.js (web/) ─ :3000 ──┐    ┌──── FastAPI (api/) ─ :8000 ──────┐
│  App Router, Zustand, TailwindCSS    │ → │  Pydantic, lazy LLM SDKs          │
│  5-step wizard / result scorecard    │    │  Multi-provider fallback chain   │
└──────────────────────────────────────┘    └──────────────┬───────────────────┘
                                                          │ imports
                                                          ▼
                                            ┌── src/ analytics engine ─────────┐
                                            │  Mesa ABM · NetworkX WoM graph   │
                                            │  Monte Carlo · calibration       │
                                            │  Plotly figures · explanations   │
                                            └──────────────────────────────────┘
```

**Frontend:** Next.js 14 + React 18 + Tailwind 3 + Zustand 4 + Plotly
**Backend:** FastAPI + Pydantic v2 + Pillow + numpy/scipy/pandas
**LLM providers:** 8 supported, all optional, used in fallback order:
&nbsp;&nbsp;&nbsp;&nbsp;Claude → GPT-4o → Gemini (5-model rotation) → Groq → Mistral → OpenRouter → xAI → Together → heuristic

## Quick start (local)

You need **Python 3.9+** and **Node 20+**.

```bash
# 1. Clone
git clone https://github.com/<your-user>/adproof.git
cd adproof

# 2. Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r api/requirements.txt

# 3. Frontend
cd web && npm install && cd ..

# 4. Optional: paste any LLM key in .env (or do it in /settings once running)
cp .env.example .env
# edit .env

# 5. Run (in two terminals)
cd api && uvicorn main:app --port 8000        # terminal 1
cd web && npm run dev                          # terminal 2

# 6. Open http://localhost:3000
```

Or just paste keys in `/settings` once you're running — they persist to `data/.secrets.json` (chmod 600, gitignored) and are reloaded on every backend restart.

## Getting free LLM keys

You only need ONE provider to function. Best free combo: **Gemini + Groq + Mistral** — gives effectively unlimited usage.

| Provider | Get key | Notes |
|---|---|---|
| Gemini | https://aistudio.google.com/apikey | Backend rotates 5 Gemini models; 20 req/day per model |
| Groq | https://console.groq.com/keys | Llama 4 Scout vision, ~14k req/day |
| Mistral | https://console.mistral.ai/api-keys/ | Pixtral-12B vision, 500k tok/min |
| OpenRouter | https://openrouter.ai/keys | Gateway to ~50 models, has free tier |
| Together AI | https://api.together.xyz/settings/api-keys | Llama-Vision-Free; $1 free credit |
| xAI | https://console.x.ai/team/default/api-keys | Grok-2-Vision; paid |
| Anthropic | https://console.anthropic.com/ | Claude; paid |
| OpenAI | https://platform.openai.com/api-keys | GPT-4o; paid |

## Project layout

```
ad-simulator/
├── api/                    FastAPI server
│   ├── main.py             routes + LLM key persistence
│   └── requirements.txt
├── src/                    Analytics engine (Python)
│   ├── pipeline.py         end-to-end orchestrator
│   ├── model.py            Mesa-style agent simulation
│   ├── simulation.py       Monte Carlo runner
│   ├── visual_analysis.py  8-provider vision dispatcher
│   ├── llm.py              8-provider text dispatcher + cache
│   ├── company_profile.py  LLM company-parser + heuristic fallback
│   ├── audience_match.py   persona-segment matcher
│   ├── copy_critique.py    rule-based copy critic
│   ├── platforms.py        Meta/Google/LinkedIn/TikTok benchmarks
│   ├── personas.py         1000 synthetic personas (2026 distributions)
│   └── ...
├── web/                    Next.js frontend
│   ├── app/                App Router pages
│   ├── components/         UI components
│   ├── lib/                Zustand store, typed API client
│   └── package.json
├── data/                   Per-installation data (gitignored)
│   ├── .secrets.json       LLM API keys (chmod 600)
│   ├── personas/           generated persona CSVs
│   ├── benchmarks/         calibration JSON
│   └── raw/uploads/        user-uploaded creatives
├── requirements.txt        Python deps (root)
├── .env.example            env var template
├── CONTEXT.md              full project handoff notes
└── README.md
```

## Honesty principles baked in

1. **No fake placeholder data.** New accounts start empty; greeting uses your real name; dashboard metrics come from actual saved campaigns.
2. **Every claim is labelled.** "Visual analysis: heuristic / Gemini / Claude" — never "AI scored this".
3. **Confidence is calibrated.** LOW when all-heuristic, MEDIUM when LLM, reserved HIGH for when you upload past performance.
4. **No quota brick walls.** When one provider hits its daily limit, the chain falls forward automatically — and tells the user exactly what happened.
5. **Per-customer data stays per-customer.** Uploaded XLSX from one user's ad account NEVER becomes a global prior for other users.

## Deployment (production)

This repo deploys cleanly as a hybrid:

- **Frontend** → Vercel (free)
- **Backend** → Railway or Render (one container, ~$5/mo)
- **DB + Auth + Storage** → Supabase (free tier)

See [`DEPLOY.md`](./DEPLOY.md) for the full step-by-step.

## Status

This is **v1** — single-user, browser-local, no DB. Auth, multi-tenant, real billing, OAuth-connected ad accounts and historical-CTR ingestion are v2.

## License

Private repo — no public license granted. Don't redistribute.
