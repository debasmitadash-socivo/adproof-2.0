# AdProof — Project Context (handoff to a fresh chat)

> Paste this entire file into a new Claude conversation as the first message so
> the new session has full context on what's built, what's pending, and the
> design decisions / user preferences that have shaped the project.

---

## TL;DR

**AdProof** is a SaaS-style web app that scores an ad creative (image + copy)
for an audience on a chosen platform/format **before** the user spends a
dollar. It outputs a defensible forecast (CTR, conversions, ROAS in p10–p90
bands), a plain-English verdict, specific copy fixes, brand-relevance check,
and a live policy-compliance check.

Built on an agent-based Mesa simulation calibrated against 2026 industry
benchmark estimates, with Gemini 2.5 Flash powering the LLM-tier features
(image inspection, semantic company/audience parsing, web-grounded
benchmark refresh, web-grounded policy check).

**Working directory:** `/Users/debs/Desktop/Claude projects/ad-simulator/`

---

## Tech stack

### Backend (`api/`)
- **FastAPI** + Pydantic v2, Python 3.9+ compatible (use `Optional[X]` not `X | None` in pydantic models)
- **Uvicorn** on port `:8000`
- LLM SDKs: `anthropic`, `openai`, `google-genai` (all lazy-imported)
- Wraps the existing analytics engine in `src/`

### Analytics engine (`src/`)
- **Mesa 3.x** for agent-based simulation (gracefully imported — works without Mesa installed)
- **NetworkX** for the social graph powering word-of-mouth
- **pandas**, **numpy**, **scipy**, **scikit-learn**
- **Pillow** for image preparation
- **Plotly** for the figure JSON returned to the frontend

### Frontend (`web/`)
- **Next.js 14** App Router + TypeScript
- **TailwindCSS 3** with a custom design system (warm cream paper, coral/magenta/violet sunset gradient, Instrument Serif italic display, Bricolage Grotesque section heads, Inter body)
- **Zustand 4.5** with `persist` middleware (localStorage key: `adproof-account-v1`)
- **react-plotly.js** for charts

### Running it
```bash
# Terminal 1 — API (port 8000)
cd api && /Users/debs/Desktop/Claude\ projects/ad-simulator/.venv-preview/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --log-level warning

# Terminal 2 — Web (port 3000)
export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh"
cd web && npm run dev

# Open http://localhost:3000/login
```

Two venvs exist:
- `.venv-preview/` — Python 3.9, has numpy/pandas/networkx/pillow/plotly/fastapi/uvicorn/pydantic/google-genai installed; works for backend smoke-testing
- A proper Python 3.12 venv `.venv/` is NOT created yet — Mesa needs Python 3.11+, but the model uses graceful imports so it currently runs on 3.9

Node 20 was installed via nvm.

API keys persist in `data/.secrets.json` (chmod 600). Auto-loaded on uvicorn startup.

---

## Architecture

```
┌─────────────────────────── Browser (localhost:3000) ──────────────────────────┐
│ Next.js App Router                                                           │
│  ├── app/login                — entry, then onboarding or dashboard          │
│  ├── app/onboarding            — name + company description (2-step)         │
│  ├── app/(app)/dashboard       — empty for new accounts; real campaigns once │
│  │                                user has run any                            │
│  ├── app/(app)/new             — 5-step wizard (Goal/Platform/Audience/      │
│  │                                Creative/Run)                               │
│  ├── app/(app)/result          — forecast scorecard                          │
│  ├── app/(app)/audiences       — CRUD on saved audiences                     │
│  ├── app/(app)/creatives       — gallery of uploaded creatives               │
│  ├── app/(app)/campaigns       — stub (v1.1)                                 │
│  ├── app/(app)/company         — editable company profile                    │
│  ├── app/(app)/settings        — profile + LLM API keys + reset workspace    │
│  └── lib/                                                                     │
│       ├── store.ts             — Zustand store (persisted to localStorage)   │
│       ├── api.ts               — typed fetch wrapper                          │
│       ├── types.ts             — mirrors backend response shapes              │
│       └── filters.ts           — platform-native filter taxonomy +           │
│                                  company-driven chip suggestions              │
└──────────────────────────────────────────────────────────────────────────────┘
                                        │ HTTP (/api/* proxied via next.config.mjs)
                                        ▼
┌─────────────────────────── FastAPI (localhost:8000) ──────────────────────────┐
│  api/main.py                                                                  │
│   ├── GET  /api/healthz                                                       │
│   ├── GET  /api/me                                                            │
│   ├── GET  /api/platforms              — platform × format catalogue          │
│   ├── POST /api/parse-company          — free-text → CompanyProfile           │
│   ├── POST /api/match-audience         — free-text → AudienceMatch            │
│   ├── POST /api/simulate               — full pipeline + plain-English        │
│   │                                       verdict + drivers + data-sources    │
│   │                                       + copy critique                     │
│   ├── POST /api/upload                 — image/video upload                   │
│   ├── POST /api/settings/api-keys      — set Anthropic/OpenAI/Gemini keys     │
│   ├── POST /api/settings/test-llm      — connectivity test                    │
│   ├── POST /api/benchmarks/refresh     — Gemini Google-search grounded        │
│   │                                       benchmark refresh                   │
│   └── POST /api/policy-check           — Gemini grounded policy compliance    │
│                                          check vs current platform docs      │
└──────────────────────────────────────────────────────────────────────────────┘
                                        │ imports
                                        ▼
┌─────────────────────────── Analytics engine (src/) ──────────────────────────┐
│  src/personas.py        Synthetic persona generator (1000 personas, 2026     │
│                          consumption patterns: TikTok 38% for Gen-Z, +0.10    │
│                          ad-skepticism baseline). Written to data/personas/.  │
│  src/platforms.py       Platform × ad-format taxonomy with 2026-Q1 benchmark  │
│                          numbers, each format carries an `as_of` field +      │
│                          source_2024 + trend_note.                            │
│  src/company_profile.py Heuristic + LLM company description parser.           │
│  src/audience_match.py  Heuristic + LLM audience matcher.                    │
│  src/brief.py           CampaignBrief + CreativeAssets dataclasses +          │
│                          format-aware validation.                             │
│  src/copy_critique.py   Rule-based copy critique (CAPS, weak CTAs, missing    │
│                          punctuation, generic phrases, B2B tone mismatch,     │
│                          URL hygiene).                                        │
│  src/visual_analysis.py Multimodal LLM ad-image scorer. Returns image_       │
│                          description (proves the model saw the file),         │
│                          image_copy_coherence (separate from brand_           │
│                          relevance), the 4 visual rubric scores, strengths/   │
│                          weaknesses/overall. Heuristic fallback is honest:    │
│                          says "cannot check coherence without LLM".           │
│  src/llm.py             text_complete() wrapper. Auto-picks provider:         │
│                          Claude > OpenAI > Gemini. Gemini call disables       │
│                          thinking_budget to keep token budget tight on text.  │
│  src/data_loader.py     Existing CTR-dataset loaders (Avazu, Criteo,          │
│                          synthetic) -- background training data.              │
│  src/calibration.py     Logistic regression fitting psychology-rule weights.  │
│  src/agent.py           AdConsumerAgent (Mesa Agent) -- per-persona click +   │
│                          conversion funnel on logit scale.                    │
│  src/model.py           AdSimulationModel (Mesa Model) -- orchestrates daily  │
│                          exposure, agent stepping, WoM propagation. Has      │
│                          anchor_to_benchmark + target_ctr +                  │
│                          target_conversion_rate so absolute CTRs match the   │
│                          channel benchmark rather than stacking on top.       │
│  src/simulation.py      Monte Carlo runner — runs the model N times,          │
│                          aggregates to p10/p50/p90.                           │
│  src/explain.py         Verdict + recommendations + caveats.                  │
│  src/charts.py          Plotly figure builders.                               │
│  src/pipeline.py        run_wizard_simulation() — the end-to-end function.   │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## What is built (mostly working)

### Web UI flow
1. **Login** — "Set up my workspace" button → onboarding
2. **Onboarding** — Step 1: name+email · Step 2: company description → AI-parsed profile (Gemini if key set, else keyword heuristic)
3. **Dashboard** — Empty-state for new accounts (no fake "Debs Singh / Lumen Skincare" anywhere). When campaigns exist, shows: metrics derived from actual saved campaigns, recent analyses table, saved audiences, recommendations
4. **Wizard (`/new`)** — 5-step flow with persistent state:
   - Step 1: Goal (Awareness/Consideration/Conversion)
   - Step 2: Platform × Format with benchmark card showing 2026 CTR/CPM + the `🔎 Refresh from web (Gemini)` button
   - Step 3: Audience — three methods (Saved / Describe in words / Build with filters). Filters auto-suggested from company's `product_category`. "What we understood from your company" callout shows the parsed category with a fix link to /company
   - Step 4: Creative — variant tabs (A/B/C/D); upload routes image vs video correctly (PIL can't open mp4); text-only formats (Google Search RSA) hide the upload entirely
   - Step 5: Run — Monte Carlo runs for each variant in parallel via Promise.all
5. **Result page** — Multi-variant leaderboard (winner ★, sortable, click rows to switch detail). Provenance banner at top says heuristic vs LLM. Plain-English verdict + "for every $1 spent you'll get back…". Driver bars relabel/grey-out the "Visual" driver when heuristic. Image description + image-↔-copy coherence + brand-fit panels. Copy critique cards with severity + specific fix + lift estimate. Live policy-compliance check button. "↺ Re-run with latest engine" button replays saved inputs against current backend
6. **Audiences (`/audiences`)** — CRUD modal with filter chip taxonomy reused from wizard
7. **Creatives (`/creatives`)** — gallery of uploaded thumbnails with ROAS
8. **Company (`/company`)** — editable profile + re-parse button
9. **Settings (`/settings`)** — profile editor + LLM key entry (Gemini highlighted as recommended free option) + Test connection + reset workspace

### Backend pipelines (verified working)

- **Heuristic mode (no API key):** keyword company parsing, keyword audience matching, image colour/contrast statistics, copy critique. Confidence locked LOW. Honest about limits in every panel.
- **Gemini mode (key set):**
  - Company parsing extracts industry, value_prop, target customer, tone
  - Audience matching gives confidence + rationale
  - Visual analysis returns image_description, image_copy_coherence (caught the demo image's red-circle stock-shape mismatch with skincare copy at 5% coherence)
  - Confidence MEDIUM
- **Live web grounding (Gemini google_search tool):**
  - `/api/benchmarks/refresh` — pulled real 2026 IG Reels CTR (0.76%) from sources like ad-amigo.ai, feedbird, advertizingly. Showed our hardcoded 1.35% estimate was too optimistic
  - `/api/policy-check` — fetches current Meta/Google/LinkedIn/TikTok policy docs, evaluates copy, returns rule violations with rule URL

### Honest data-provenance contract

Every result page surfaces what was measured vs estimated:
- **Personas:** synthetic, 2026 consumption distributions, not real customers
- **CTR benchmark:** marked `as_of 2026-Q1`, with the source_2024 number and a trend_note
- **Company parsing:** marked `✨ Gemini` or `keyword heuristic`
- **Audience match:** marked with active provider + confidence
- **Visual analysis:** marked with provider; for LLM runs, the literal image description is shown
- **Calibration:** still `synthetic CTR dataset (replaceable)` — flagged for v1.1 upload feature

Confidence levels: LOW (mostly heuristic) → LOW_MEDIUM (mixed) → MEDIUM (all LLM). HIGH is reserved for when the user uploads their own past performance.

---

## Critical design decisions baked in

1. **No fake data ever.** New accounts start completely empty. Greeting uses the user's actual name. Workspace name comes from their parsed company. Dashboard metrics computed from `savedCampaigns[]`, empty states when zero. Filter chips all deselected by default.
2. **The user is impatient and skeptical.** Devil's-advocate framing requested. Be brutally honest about what works and what doesn't.
3. **Confidence > confidence theatre.** Every visible claim ties back to its data source. Heuristic visual scores never claim to "understand the image". Industry benchmarks always labelled with their year.
4. **Plain English over jargon.** Logit-scale contributions are converted to "Persuasion cues in the copy: +24%". "Monte Carlo runs" gets a tooltip explanation. "ROAS" is rendered as "for every $1 spent you'll get back $X".
5. **All-PROVIDER attribution.** When showing "AI parsed", show *which* AI (Claude / GPT-4o / Gemini). Don't just say "LLM".
6. **Logit-scale combination, sigmoid out.** Click probability never escapes [0,1] because base + visual + persona_match + psychology are all logit-scale, then sigmoid is applied.
7. **Anchor to benchmark.** `AdSimulationModel(anchor_to_benchmark=True)` shifts `base_logit` so the audience mean click probability matches the channel benchmark, so strong/weak creatives deviate around it rather than stacking on top.
8. **Variant tabs > single creative.** Step 4 of the wizard supports Variant A + add B/C/D. Run fires `/api/simulate` per variant in parallel. Result page has a leaderboard.

---

## ⚠️ User's data-handling principle (very important)

> *"i dont want you to take in my data as the industry standard, its data which
> worked good or bad you dont know dont take it with your eyes closed (and its
> just 2 clients in 2 diff industries) we never know how it might perform for
> others"*

**Per-customer uploaded data must stay per-customer.**

- An uploaded XLSX/CSV from a Meta Ads Manager export calibrates **only that
  customer's** future forecasts — never gets aggregated into a "global"
  benchmark for other users.
- We don't know whether a customer's 1.20% Feed CTR is good or bad for *their*
  industry; we only know it's *their* baseline.
- Cross-customer aggregation, if ever built, requires: explicit opt-in,
  k≥5 minimum cohort, differential-privacy noise on gradients, and surfaces
  *only* aggregate priors ("beauty category saw +12% CTR lift on scarcity
  cues in Q1 2026"), never any single customer's traces.
- Industry-average defaults stay in `src/platforms.py` (2026-Q1) and are
  refreshable via the Gemini-grounded `/api/benchmarks/refresh` endpoint.
  Users' own data NEVER mutates those defaults globally.

This is non-negotiable per the user.

---

## Open user-shared data (do NOT use as global priors)

The user provided two XLSX files for testing/demo only:
- `/Users/debs/Downloads/MTC-2025-2026-report.xlsx` (1,540 rows, 11 campaigns, 74 ads, $71k CAD spend, 6.5M impressions). Sheet: "Creative Reporting".
- `/Users/debs/Downloads/Evolve-and-grow-report-Jan-1-2025-to-May-24-2026.xlsx` (765 rows). Sheets: "Formatted Report" + "Raw Data Report". GBP currency.

Both are Meta Ads Manager exports. Columns typically include: Campaign name, Ad name, Placement, Impressions, Link clicks, CTR (all), CPC, Amount spent, Cost per result, Result type, Reporting dates.

**Status: NOT YET IMPORTED.** The CSV/XLSX upload + per-customer calibration feature is the next major piece of work. When built, it must:
- Store the parsed data per-customer (per workspace)
- Calibrate THAT customer's `target_ctr` / `target_conversion_rate` / `mean_aov` per format from their actual numbers
- Bump confidence LOW/MEDIUM → HIGH only for that customer's forecasts
- NEVER mutate the global `src/platforms.py` benchmarks
- Surface a "Calibrated against your X ads (Y impressions, Z spend)" note on the result page

---

## What is shaky / known limitations

1. **Personas are synthetic.** 1000 generated people with 2026-ish consumption distributions, not a real survey panel. Used for relative comparison, not absolute prediction.
2. **Calibration psychology weights are fitted on a SYNTHETIC CTR dataset** (`src/data_loader.generate_synthetic_ctr_data`). All calibration outputs label themselves as `is_synthetic: True`.
3. **Heuristic visual analysis** is colour + contrast + saturation statistics + copy keywords. It does NOT see the image. UI labels this everywhere.
4. **Gemini 2.5 Flash "thinking" budget** must be set to 0 for text completions (otherwise tokens get eaten and `resp.text` returns None). For vision we leave thinking_budget at 512.
5. **Live benchmark refresh accuracy depends on the web** — Gemini grounding pulls from current sources but those sources themselves vary in trustworthiness (we cite source URLs back to the user).
6. **No real auth.** Stub user lives in localStorage. No multi-tenant DB. v2 territory.
7. **No real campaign hierarchy.** "Campaign" in this app currently = Meta's "ad set" level (one audience, one format, multiple creatives). True Campaign → Ad Set → Ad hierarchy is v2.
8. **Mesa requires Python 3.11+** but the simulator uses a graceful Mesa import so it runs on Python 3.9 without it (degraded to no auto-scheduler features but they're not used).
9. **API key persistence is a JSON file in `data/.secrets.json`** — fine for local-dev, NOT acceptable for production. Real per-user encrypted storage is v2.
10. **Numpy `matmul` raises spurious FPE warnings** on some platforms — wrapped in `np.errstate(divide="ignore", over="ignore", invalid="ignore")` around the IRLS solver in `src/calibration.py`, with explicit finite-check on outputs.

---

## What's still on the roadmap (per priority)

### Already discussed in the chat
1. **CSV/XLSX upload for per-customer calibration** — the next single biggest unlock. User provided two real Meta Ads Manager exports; we have all the parsing knowledge from previous deep-dives. **Do this next.** Honestly, this is where the chat left off.
2. **Meta Ad Library scraper + implied-performance scoring** — pull live competitor ads in tracked industries, score "implied performance" from runtime + spend + variant survival + geo breadth (not from any private outcomes). Build a vector index over (image, copy) embeddings via Gemini multimodal. At simulate time, nearest-neighbour lookup gives "your creative is similar to ads from {brands} that ran avg X days".
3. **Per-format benchmark override UI** — let users punch in their own per-format CTR/CPM into the wizard's benchmark card to override defaults (without depending on a full CSV import).
4. **Campaign → Ad Set → Ad real hierarchy.** A campaign can hold multiple ad sets (different audiences), each with multiple ads.
5. **Real auth + persistent DB.** Clerk + Postgres. Per-user encrypted secret storage.
6. **OAuth integrations** (Meta Marketing API, Google Ads API, LinkedIn Marketing API) so the user clicks "Connect Meta", we pull their performance automatically.
7. **Cross-customer aggregate priors** — opt-in, k≥5, DP-noised. This is the federated-learning piece the user explicitly endorsed but flagged needs care.
8. **More expressive heuristics for fitness/B2B/SaaS categories.** Already partially done (running club, marketing_agency, saas categories) but the persona side could use more 2026-realistic distributions for B2B / professional audiences.

### Smaller polish items
- `/campaigns` page is a stub
- "Compare" button on result page shows other campaigns but only swaps the result — should be side-by-side
- Settings → no team / billing UI yet
- No accessibility audit done (aria-labels, colour contrast on the gradient text)
- Mobile responsiveness untested
- Charts could be simpler / less Plotly-ish per earlier feedback

---

## User preferences / communication style (READ THIS)

- **Hates fake placeholder data.** "Debs Singh / Lumen Skincare" was called out hard. Everything must be either the user's actual input or an explicit empty state.
- **Wants devil's-advocate audits.** Asks for "rate this, what's broken, what can be improved."
- **Wants plain English, not jargon.** "ROAS" gets explained as "$X back per $1 spent". "Logit" is invisible to users.
- **Reads UI in screenshots.** Will paste UI screenshots and point at problems with bounding-box precision. Look closely.
- **Impatient with build cycles.** Says "do all" / "do it" / "go" frequently. Don't over-confirm before building.
- **Skeptical of LLM accuracy claims.** Wants every claim tied back to its data source. "How do you know? Where did this number come from?"
- **Cares about 2026 data**, not 2024 (the chat happened on `2026-05-23` to `2026-05-24`).
- **Pasted Gemini API key in chat** at some point — they should rotate that one. Current key is `AIza...` stored in `data/.secrets.json`.

---

## Where to pick up the next chat

The chat ended on a key clarification from the user about their uploaded
Meta data being per-customer signal, not global truth. The agreed next
piece is:

**Build the per-customer XLSX/CSV upload + calibration feature.**

Concretely:
1. New page `/data` ("Calibrate on your real campaigns")
2. Backend `/api/data/upload` endpoint that accepts XLSX/CSV
3. Parser that handles both Meta Ads Manager export layouts seen in the user's
   files (the MTC "Creative Reporting" single-sheet layout AND the Evolve &
   Grow "Formatted Report" / "Raw Data" multi-sheet layout)
4. Extractor that computes per-placement actuals: CTR, CPM, conversion-cost,
   spend, impressions, unique ads
5. **Per-workspace storage** in `data/.user_calibrations/{workspace_id}.json`
   — NEVER mutates `src/platforms.py`
6. Simulator reads from per-workspace overrides when present, falls back to
   industry defaults otherwise
7. Result page confidence panel bumps to HIGH when calibrated, with text:
   "Calibrated against your {N} past ads ({date_range}, {spend} spend,
   {impressions} impressions)"
8. Show a before/after table so user can review what's changing

The user has explicitly said data must stay per-customer — no global learning
from a 2-customer sample.

---

## Quick file map for the new session

```
ad-simulator/
├── api/
│   ├── main.py                  ← FastAPI app, routes, key persistence
│   └── requirements.txt         ← fastapi/uvicorn/pydantic/google-genai
├── src/
│   ├── personas.py              ← persona generator (2026 distributions)
│   ├── platforms.py             ← platform/format taxonomy, 2026 benchmarks
│   ├── company_profile.py       ← LLM + heuristic company parser
│   ├── audience_match.py        ← LLM + heuristic audience matcher
│   ├── brief.py                 ← CampaignBrief + CreativeAssets
│   ├── copy_critique.py         ← rule-based copy critic
│   ├── visual_analysis.py       ← Gemini/Claude/OpenAI vision + heuristic
│   ├── llm.py                   ← text_complete() multi-provider wrapper
│   ├── data_loader.py           ← CTR dataset loading (synthetic + Avazu/Criteo)
│   ├── calibration.py           ← logistic regression psychology-weight fit
│   ├── agent.py                 ← AdConsumerAgent (Mesa)
│   ├── model.py                 ← AdSimulationModel (Mesa)
│   ├── simulation.py            ← Monte Carlo runner
│   ├── explain.py               ← verdict + recommendations
│   ├── charts.py                ← Plotly figures
│   └── pipeline.py              ← run_wizard_simulation entry point
├── web/
│   ├── app/
│   │   ├── login/page.tsx
│   │   ├── onboarding/page.tsx
│   │   ├── (app)/
│   │   │   ├── layout.tsx           ← Sidebar + Topbar + onboarding redirect
│   │   │   ├── dashboard/page.tsx
│   │   │   ├── new/page.tsx         ← 5-step wizard (biggest single file)
│   │   │   ├── result/page.tsx      ← scorecard + leaderboard + critique
│   │   │   ├── audiences/page.tsx   ← CRUD modal
│   │   │   ├── creatives/page.tsx
│   │   │   ├── company/page.tsx
│   │   │   └── settings/page.tsx
│   │   └── globals.css              ← Tailwind + print CSS + design tokens
│   ├── components/
│   │   ├── Sidebar.tsx              ← workspace switcher, nav, user
│   │   ├── Topbar.tsx               ← search, LLM-status pill
│   │   ├── Charts.tsx               ← Plotly wrapper
│   │   └── ui/                      ← Button, Card, Pill, HelpHint
│   ├── lib/
│   │   ├── store.ts                 ← Zustand store with persist
│   │   ├── api.ts                   ← typed fetch wrapper
│   │   ├── types.ts                 ← all backend response types
│   │   └── filters.ts               ← chip taxonomy + suggestions
│   ├── tailwind.config.ts           ← design tokens
│   ├── next.config.mjs              ← /api/* proxy → :8000
│   └── package.json
├── mockups/                         ← static HTML mockups (v0 design)
├── data/
│   ├── .secrets.json                ← API keys (gitignored, 0600)
│   ├── personas/personas.csv        ← generated personas
│   ├── raw/uploads/                 ← user-uploaded creatives
│   └── benchmarks/                  ← calibration outputs
├── scripts/dev.sh                   ← one-command boot (needs Python 3.12)
├── README.md
└── CONTEXT.md                       ← this file
```

---

## Useful test commands

```bash
# Quick smoke test of a Gemini-powered simulate call
curl -s -X POST -H "Content-Type: application/json" -d '{
  "company_description":"Pace Lab is a running club for women 25-45.",
  "audience_description":"Urban millennials interested in fitness.",
  "platform_id":"meta_instagram","format_id":"meta_ig_reels",
  "budget":3000,"days":7,"n_runs":10,"daily_reach":0.35,
  "target_conversion_rate":0.025,
  "headline":"Hit your first 10K","primary_text":"Train together weekends.",
  "cta":"Join","link":"https://example.com",
  "image_path":"/Users/debs/Desktop/Claude projects/ad-simulator/data/raw/demo_ad.png",
  "visual_provider":"auto"
}' http://127.0.0.1:8000/api/simulate | python3 -m json.tool

# Refresh a benchmark from the live web
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"format_id":"meta_ig_reels"}' \
  http://127.0.0.1:8000/api/benchmarks/refresh | python3 -m json.tool

# Run a policy compliance check
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"platform_id":"linkedin","format_id":"linkedin_sponsored_image",
       "headline":"GUARANTEED 10X YOUR MONEY","primary_text":"…"}' \
  http://127.0.0.1:8000/api/policy-check | python3 -m json.tool
```

---

## One-line summary to lead with in the new chat

> *"Continuing AdProof — an ad-creative scoring SaaS built on Mesa agent
> simulation + Gemini multimodal. Working app at localhost:3000 + FastAPI
> at :8000. Next ticket: per-customer XLSX upload from Meta Ads Manager
> exports that calibrates only-that-customer's future forecasts. Real data
> never becomes a global prior — user has been explicit on that. Read
> `CONTEXT.md` at the project root for the full handoff."*
