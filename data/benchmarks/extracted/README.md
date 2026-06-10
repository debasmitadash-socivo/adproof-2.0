# Benchmark reference — extracted JSON

Structured extracts from publicly-available 2025–2026 marketing benchmark
reports. The original PDFs live in `data/benchmarks/reference/` and are
gitignored (large, licensed under publisher terms). The JSONs in THIS folder
are the parsed extract we own and ship.

## Files

| File | Source | What's in it | Best use in AdProof |
|---|---|---|---|
| `rival_iq_2025_industry_engagement.json` | Rival IQ 2025 Social Media Industry Benchmark Report (2,100 companies × 14 industries) | Median engagement rate + posting frequency per (industry × platform). 14 industries × 4 platforms = 56 cells. | Industry × platform calibration anchor when the user hasn't uploaded their own data. Lets the report say *"For fitness brands on Instagram, the industry median engagement rate is 0.147%; your modelled CTR is X."* |
| `sprout_social_index_2026_platform_stats.json` | Sprout Social Index 2026 (120+ stats) | Platform-level demographics, DAU, growth, behavioural shifts. 11 platforms. Plus global context block (ad spend, social-search share, AI-aversion). | LLM-prompt context. Feed the relevant platform section into the creative critic so the model knows 2026 platform norms. Drives the audience-defaults too. |
| `hootsuite_social_trends_2026.json` | Hootsuite Social Trends 2026 (powered by Talkwalker AI) | 18 narrative trends + key takeaways. AI authenticity, social search, creator partnerships, fastvertising, etc. | LLM-prompt context for the creative critic — what's CULTURALLY happening on social in 2026. Used to nudge the critic toward 2026-aware advice (e.g. "flag AI-generated polish; users are tired of it"). |
| `hubspot_state_of_marketing_2026.json` | HubSpot State of Marketing 2026 (1,500+ global marketers) | AI usage, budget outlook, channel mix, short-form video dominance, brand-POV importance. Extracted from press coverage because the official report is a JS-rendered Replit app. | Strategic context for the LLM critic + the audience-defaults. Less granular than Rival IQ but more recent and broader. |

## How they're consumed at runtime

These JSONs are loaded once at FastAPI startup (lightweight, ~30KB total)
and made available to:

1. **`/api/industry-context`** (planned) — looks up `(industry × geo × platform)`
   and returns the layered confidence chain (real data > industry benchmark >
   platform baseline > global).
2. **Creative critic prompts** (existing modules under `src/`) — relevant
   subsections injected as context so the LLM has 2026-accurate norms.
3. **Wizard defaults** — Sprout demographics drive default `reachable_audience`
   per platform when the user doesn't override.

## Licence and attribution

Each report is free / freemium under the publisher's standard terms. The
extracts here are factual data points we re-shape into our own schema — we
cite the publisher prominently anywhere a number is surfaced in the UI.

If you ever ship this data to clients, the footer reads:
> Benchmarks: Rival IQ 2025 · Sprout Social Index 2026 · Hootsuite Social
> Trends 2026 · HubSpot State of Marketing 2026.

## Refresh cadence

These are ANNUAL reports. Re-run the parsers in Q1 of each year as new
versions drop. The extraction scripts that produced these files live in
the commit history of `data/benchmarks/extracted/` — search the repo for
the `pdfplumber.open(.../rival_iq_industry_benchmark_...)` pattern.

## Honest gaps

- **HubSpot data is press-coverage-aggregated**, not first-party. If/when
  the owner can grab a fuller HubSpot PDF or HubSpot exposes their data
  in a non-JS-rendered form, re-run the extraction.
- **Rival IQ is 2024 data** (published 2025). The 2025-data report will
  come early 2026 — refresh then.
- **Sprout and Hootsuite are 2026 reports** — most current.
- **None of these have CTR/CPM data for paid ads** directly. They cover
  organic engagement rates. Use the relationship (organic engagement
  correlates with paid creative quality) cautiously — see Pillar D / VIE
  caveats elsewhere in the codebase.
