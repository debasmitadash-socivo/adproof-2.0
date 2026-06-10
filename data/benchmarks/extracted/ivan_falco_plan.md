# Ivan Falco `ads-skills` — Integration Plan for AdProof

**Source:** [github.com/ivangfalco/ads-skills](https://github.com/ivangfalco/ads-skills)
**Status:** Licensed for our use per `project_flywheel-roadmap.md` memory.
**Attribution required:** Yes — every UI surface that uses Ivan-derived content
must carry *"Knowledge base adapted from Ivan Falco's `ads-skills`, licensed
for AdProof's use."*

This document is the **catalogue + cutting plan**. The owner reviews and
signs off BEFORE any of these files are folded into AdProof's prompts or
deterministic advice tables. No code in `src/` changes until that sign-off.

---

## Inventory

Three platform skills + one foundations bundle + scripts. ~6,700 lines
of marketing rules across 41 markdown files.

### `ads-foundations/` (10 files, 968 lines) — platform-agnostic

| File | Lines | What's in it | AdProof use |
|---|---:|---|---|
| **ad-copywriting.md** | 324 | Hook patterns, copy frameworks, do/don't for headline/primary text/description/CTA. Universal. | **HIGH.** Folds straight into `src/copy_critique.py` as a deeper rubric for `critique_copy()`. Replace placeholder rules with Ivan's specific ones. |
| **ad-personas.md** | 64 | Persona-creative fit framework. | MEDIUM. Sharper input for the per-segment calibration story (Pillar B+). |
| **budget-allocation.md** | 35 | How to split spend across funnel stages. | LOW (GTM operations, not pre-flight scoring). Skip. |
| **campaign-planning.md** | 37 | Campaign structure thinking. | LOW. Skip. |
| **channel-selection.md** | 57 | When to use which platform. | MEDIUM. Could power a "wrong channel for this objective" warning on the result page. |
| **demand-lifecycle.md** | 97 | Pre-aware → solution-aware → product-aware messaging. | **HIGH.** Per-objective creative critique gets sharper if it knows the lifecycle stage. |
| **measurement-scorecard.md** | 114 | What to measure per objective. | MEDIUM. Reinforces our objective-aware verdict (Pillar A). |
| **offers-strategy.md** | 74 | Offer types, when each works. | **HIGH.** New dimension in the Creative Advice card — most current AdProof scoring ignores the offer itself. |
| **optimization-signals.md** | 111 | What's signal vs noise per platform. | MEDIUM. Powers post-launch advice (out of current scope but useful for Phase 4). |
| **scaling-quadrant.md** | 55 | When to scale spend. | LOW (GTM). Skip. |

### `linkedin-ads/` (15 KB files, 2,548 lines)

| File | Lines | What's in it | AdProof use |
|---|---:|---|---|
| **creative-strategy.md** | 352 | LinkedIn-specific creative rules — single image / video / carousel / document / thought leader / message ads. | **CRITICAL.** Primary source for the new LinkedIn critic prompt (replacing LDA's narrower rubric). |
| **copy-audit-framework.md** | 90 | LinkedIn copy patterns + traps. | **HIGH.** Drives LinkedIn copy critic. |
| **audit-checklist.md** | 83 | Pre-flight checklist for LinkedIn ads. | **HIGH.** Becomes deterministic pre-flight checks in pipeline (similar to current `check_image_specs`). |
| **benchmarks.md** | 93 | LinkedIn-specific CPM/CPC/CTR benchmarks by industry. | **HIGH.** Extends `src/benchmarks.py` with LinkedIn-specific paid numbers (Rival IQ is organic only). |
| **full-funnel-framework.md** | 171 | Awareness → consideration → conversion creative ladder. | **HIGH.** Reinforces Pillar A's objective branching with LinkedIn-specific rules. |
| **document-ads.md** | 112 | Document/PDF format rules. | MEDIUM. We don't ship Document ads yet — useful when we do. |
| **conversation-ads.md** | 132 | Conversation ads format. | MEDIUM. Same. |
| **audience-sizing.md** | 241 | LinkedIn targeting size sweet spots. | MEDIUM. Could power per-platform `reachable_audience` defaults. |
| **scaling-strategy.md** | 282 | GTM ops. | LOW. Skip. |
| **bidding-strategy.md** | 159 | GTM ops. | LOW. Skip. |
| **campaign-structures.md** | 197 | GTM ops. | LOW. Skip. |
| **landing-pages.md** | 84 | LP optimisation. | LOW (out of AdProof's scope — we score the ad, not the LP). Skip. |
| **launch-checklist.md** | 111 | Launch operations. | LOW. Skip. |
| **ctv-strategy.md** | 40 | Connected TV strategy. | LOW. We don't ship CTV. Skip. |
| **abm-strategy.md** | 250 | ABM playbook. | LOW. Skip (per the owner's earlier "we score, not orchestrate" rule). |

### `meta-ads/` (15 KB files, 3,205 lines)

| File | Lines | What's in it | AdProof use |
|---|---:|---|---|
| **creative-strategy.md** | 238 | Meta-specific creative rules by format (Feed / Reels / Stories / Carousel / Advantage+). | **CRITICAL.** Primary source for the new Meta creative critic prompt. Layered over VIE for paid-Meta specificity. |
| **creative-cadence-operating-system.md** | 368 | Creative refresh cadence + fatigue thresholds. | **HIGH.** Extends current `src/fatigue.py` (already uses some Ivan knowledge per memory). |
| **creative-fatigue-detection.md** | 185 | Specific fatigue triggers. | **HIGH.** Same as above — sharpens fatigue.py. |
| **message-validation.md** | 167 | Message-market fit framework. | **HIGH.** New dimension in the Creative Advice card. |
| **offer-strategy.md** | 177 | Meta-specific offer rules. | **HIGH.** Pairs with foundations/offers-strategy.md to score the offer dimension. |
| **advantage-plus.md** | 223 | Meta Advantage+ format-specific rules. | **HIGH.** AdProof currently doesn't differentiate Advantage+ from manual placements — this fixes that. |
| **meta-ads-operating-system.md** | 461 | Full account operating system. | MEDIUM. Big file; relevant bits feed into the critic context. |
| **audience-strategy.md** | 156 | Meta targeting strategy. | MEDIUM. Reinforces segment + interest mapping (Pillar B+). |
| **meta-b2b-overview.md** | 96 | Meta for B2B. | MEDIUM. Useful when company is B2B + on Meta (rare but happens). |
| **campaign-structure.md** | 239 | GTM ops. | LOW. Skip. |
| **lead-form-optimization.md** | 123 | Lead form mechanics. | LOW (out of scope). Skip. |
| **abm-on-meta.md** | 243 | ABM tactics. | LOW. Skip. |
| **optimization-playbook.md** | 317 | Post-launch ops. | LOW. Skip. |
| **meta-capi-and-events.md** | 85 | Conversion tracking ops. | LOW. Skip. |
| **meta-setup-and-tracking.md** | 162 | Account setup ops. | LOW. Skip. |
| **meta-third-party-conversion-tracking.md** | 65 | Conversion tracking. | LOW. Skip. |

### `google-ads/` (1 file, 44 lines)

| File | Lines | What's in it | AdProof use |
|---|---:|---|---|
| **cheatsheet-overview.md** | 44 | Brief Google Ads overview. | LOW. **Ivan's Google coverage is thin.** Not enough to build a deep Google critic from this alone. We'd combine with Think with Google / Sprout data + grounded search to fill gaps. |

### Scripts (39 files)

Per project memory, his read-only API scripts are already partially
adapted into our connectors (`src/connectors/meta.py` etc.). The
remaining scripts are write/management operations we explicitly do
NOT want in AdProof (we score, not orchestrate). Skip.

---

## Where each kept file lands in AdProof

| AdProof module | Files folded in | Effort | Priority |
|---|---|---|---|
| **NEW `src/linkedin_critic.py`** | linkedin-ads/creative-strategy + copy-audit-framework + audit-checklist + full-funnel-framework | 2 hr | P1 |
| **NEW `src/meta_critic.py`** | meta-ads/creative-strategy + advantage-plus + offer-strategy + message-validation | 2 hr | P1 |
| **EXTEND `src/copy_critique.py`** | ads-foundations/ad-copywriting | 1 hr | P1 |
| **EXTEND `src/fatigue.py`** | meta-ads/creative-cadence-operating-system + creative-fatigue-detection | 0.5 hr | P2 |
| **EXTEND `src/creative_advice.py`** | foundations/offers-strategy + foundations/demand-lifecycle | 1 hr | P2 |
| **EXTEND `src/benchmarks.py`** | linkedin-ads/benchmarks (LinkedIn-specific paid CPM/CTR) | 0.5 hr | P2 |
| **NEW pre-flight checks** | linkedin-ads/audit-checklist | 1 hr | P3 |
| **Google Ads critic** | google-ads/cheatsheet (thin) + supplement with grounded search | 1.5 hr | P3 — defer until thin Google coverage is plugged |

Total: **~9.5 hours of focused work** to fully fold Ivan into AdProof.

---

## What I'd NOT do

- **Don't auto-load the entire knowledge base into every Gemini prompt.**
  Most files are 3-5k tokens — the full 6,700 lines is ~60k tokens. Cost
  + relevance both suffer. Per critic, we inject only the files relevant
  to the platform + objective being scored. The catalogue above maps
  that selection.
- **Don't copy his attribution-stripped content verbatim into AdProof
  source files.** Encode the RULES, cite his repo. The licence is for
  use — not republication.
- **Don't try to build a Google-Ads critic in this slice.** Ivan's
  Google coverage is one 44-line cheatsheet. Need supplementary
  knowledge first (Think with Google + grounded search), separate slice.

---

## Sign-off questions

1. **Approval on the file-by-file cuts above?** Owner reviews each
   HIGH-priority file before code goes in (~10 min of reading).
2. **LinkedIn critic — strict-paid or organic-paid blend?** Ivan's
   LinkedIn content is paid-ad focused. LDA (the owner's skill) is
   organic. Layer LDA over Ivan, or pick one? Recommend: Ivan as the
   primary rubric, LDA as a supplementary hook-template library only.
3. **Attribution wording exact text?** Default proposed: *"Knowledge
   base adapted from Ivan Falco's ads-skills, licensed for AdProof's
   use."* — keep, soften, or harden?
4. **Build order — LinkedIn first or Meta first?** LinkedIn has the
   biggest gap in AdProof today (no LinkedIn-specific critic). Meta
   has more content but VIE already covers ~half of Meta's surface.
   Recommend: LinkedIn first.

Once we have answers, the build is ~9.5 hours total — best split
across two sessions (LinkedIn + foundations in session 1, Meta + everything
else in session 2).
