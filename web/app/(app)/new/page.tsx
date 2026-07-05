'use client';
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import clsx from 'clsx';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { HelpHint } from '@/components/ui/HelpHint';
import { useApp } from '@/lib/store';
import { api } from '@/lib/api';
import { getLatestCalibration } from '@/lib/db';
import { uploadCreativeToSupabase } from '@/lib/storage';
import type { BenchmarkRefreshResponse, Platform, SavedCampaign, SavedVariantResult } from '@/lib/types';

// Map a wizard platform id to the calibration bucket produced by the ingest.
// P3a: anchor picking (hierarchical shrinkage), interest mapping and the
// platform-key normalizer live in lib/anchor.ts — pure + unit-tested.
import {
  calibrationPlatformKey,
  interestsFromText,
  interestsFromChipIds,
  pickCalibrationAnchor,
} from '@/lib/anchor';
import {
  filtersForPlatform,
  suggestedChips,
  describeFilters,
  type FilterCard as FilterCardType,
} from '@/lib/filters';

const OBJECTIVES = [
  { id: 'awareness', name: 'Awareness', sub: 'Reach + brand lift', glyph: '👁' },
  { id: 'consideration', name: 'Consideration', sub: 'Clicks + engagement', glyph: '💭' },
  { id: 'conversion', name: 'Conversion', sub: 'Sales / leads', glyph: '🎯' },
] as const;

const PLATFORM_BADGES: Record<string, { bg: string; label: string }> = {
  meta_facebook: { bg: 'bg-gradient-to-br from-blue-600 to-blue-900', label: 'FB' },
  meta_instagram: { bg: 'bg-gradient-to-br from-yellow-500 via-pink-500 to-purple-600', label: 'IG' },
  google_search: { bg: 'bg-gradient-to-br from-blue-500 via-red-500 to-yellow-500', label: 'G' },
  google_display: { bg: 'bg-gradient-to-br from-blue-500 to-cyan-400', label: 'G' },
  youtube: { bg: 'bg-red-600', label: '▶' },
  linkedin: { bg: 'bg-[#0A66C2]', label: 'in' },
  tiktok: { bg: 'bg-gradient-to-br from-cyan-400 via-black to-pink-500', label: 'TT' },
};

const STEPS = ['Goal', 'Platform & format', 'Audience', 'Creative', 'Run'];

export default function NewAnalysisPage() {
  const router = useRouter();
  const w = useApp();
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [audienceMethod, setAudienceMethod] = useState<'saved' | 'words' | 'filters'>('words');
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Per-campaign economics + market — default from the company profile,
  // overridable for this run (e.g. test a US push for one product). Initialised
  // once from the saved company profile.
  const cp = w.companyProfile;
  const [geo, setGeo] = useState<string>(cp?.location || 'UK');
  const [currency, setCurrency] = useState<string>(cp?.currency || 'GBP');
  const [aov, setAov] = useState<string>(cp?.avg_order_value != null ? String(cp.avg_order_value) : '');
  const [convRate, setConvRate] = useState<string>('2.5');   // % — user-facing
  const [reachAudience, setReachAudience] = useState<string>('');   // opt-in saturation

  useEffect(() => {
    api.platforms().then((d) => setPlatforms(d.platforms)).catch(() => setPlatforms([]));
  }, []);

  // Default audience method: filters if no saved audiences exist
  // (matches what most users want), saved otherwise.
  useEffect(() => {
    if (w.savedAudiences.length > 0) setAudienceMethod('saved');
    else setAudienceMethod('filters');
  }, [w.savedAudiences.length]);

  // When the user lands on Step 3 with no filters set, auto-apply the
  // company-driven suggestions so the wizard never starts blank.
  useEffect(() => {
    if (w.step !== 3) return;
    if (Object.keys(w.filterSelections).length > 0) return;
    const category = w.companyProfile?.product_category ?? 'general';
    const chips = suggestedChips(category, w.platformId);
    if (chips.length > 0) w.setManyFilters(chips);
  }, [w.step, w.platformId, w.companyProfile?.product_category]);

  const platform = platforms.find((p) => p.id === w.platformId);
  const format = platform?.formats.find((f) => f.id === w.formatId);

  async function onPickFile(file: File) {
    setUploading(true);
    setError(null);
    try {
      // Tier 2: upload direct to Supabase Storage so files survive Railway
      // redeploys. Returns the same shape as the legacy /api/upload so the
      // rest of this handler is unchanged.
      const r = await uploadCreativeToSupabase(file);
      const isVideo = r.kind === 'video';
      // Route to the active variant. Variant A lives in the base store fields;
      // B/C/D live in extraVariants[idx-1].
      if (w.activeVariant === 0) {
        if (isVideo) { w.setVideo(r.path, r.url); w.setImage(null, null); }
        else         { w.setImage(r.path, r.url); w.setVideo(null, null); }
      } else {
        const ei = w.activeVariant - 1;
        w.updateExtraVariant(ei, {
          imagePath: isVideo ? null : r.path,
          imageUrl:  isVideo ? null : r.url,
          videoPath: isVideo ? r.path : null,
          videoUrl:  isVideo ? r.url : null,
        });
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  // Active-variant media (used by the upload preview UI).
  const activeMedia = w.activeVariant === 0
    ? { imageUrl: w.imageUrl, videoUrl: w.videoUrl }
    : { imageUrl: w.extraVariants[w.activeVariant - 1]?.imageUrl ?? null,
        videoUrl: w.extraVariants[w.activeVariant - 1]?.videoUrl ?? null };

  async function runSimulation() {
    setRunning(true);
    setError(null);
    try {
      // Build the audience description the matcher will read.
      // If the user used filters, convert their chip selections into a
      // sentence the matcher can use; if they used words, use their text;
      // if they picked a saved audience, audience_segment overrides matching.
      const filterDescription = describeFilters(
        Object.keys(w.filterSelections),
        w.platformId,
      );
      const audienceDescription =
        audienceMethod === 'filters' ? filterDescription
        : audienceMethod === 'words' ? w.audienceDescription
        : '';

      // Build the full COPY variant list: Variant A (base store) + any extras.
      // These are different headlines/creatives the user wants to compare.
      const copyVariants = [
        {
          label: 'A',
          headline: w.headline, primaryText: w.primaryText,
          description: w.description, cta: w.cta, link: w.link,
          imagePath: w.imagePath, videoPath: w.videoPath, imageUrl: w.imageUrl,
        },
        ...w.extraVariants.map((v) => ({
          label: v.label,
          headline: v.headline, primaryText: v.primaryText,
          description: v.description, cta: v.cta, link: v.link,
          imagePath: v.imagePath, videoPath: v.videoPath, imageUrl: v.imageUrl,
        })),
      ];

      // PRE-FLIGHT GUARD — don't spend a single API call if a creative is
      // missing. Without an image/video there's no ad to run and nothing to
      // analyse, so we stop here BEFORE firing simulate or the market-context
      // call (both cost API/quota).
      const needsCreative = format ? format.media_type !== 'text' : true;
      if (needsCreative) {
        const missing = copyVariants.filter((v) => !v.imagePath && !v.videoPath);
        if (missing.length) {
          throw new Error(
            missing.length === copyVariants.length
              ? `Upload ${format?.media_type === 'video' ? 'a video' : 'an image'} for ${format?.name ?? 'this format'} before running — there's nothing to analyse (and no ad to run) without a creative.`
              : `Variant${missing.length > 1 ? 's' : ''} ${missing.map((m) => m.label).join(', ')} ${missing.length > 1 ? 'are' : 'is'} missing a creative. Add ${format?.media_type === 'video' ? 'a video' : 'an image'} to every variant before running.`,
          );
        }
      }

      // PLACEMENT EXPANSION — for each additional placement (Meta multi-select
      // etc.), every copy variant gets one extra run. Build the (placement_id,
      // platform_id, format_obj) tuple list, starting with the PRIMARY (so the
      // base run keeps its short single-letter label).
      const placementRuns: { formatId: string; platformId: string; formatName: string }[] = [
        { formatId: w.formatId, platformId: w.platformId, formatName: format?.name ?? '' },
      ];
      for (const fid of w.additionalFormatIds) {
        const ownerPlatform = platforms.find((p) => p.formats.some((f) => f.id === fid));
        const fmt = ownerPlatform?.formats.find((f) => f.id === fid);
        if (!ownerPlatform || !fmt) continue;            // catalogue out of sync — skip silently
        placementRuns.push({
          formatId: fid,
          platformId: ownerPlatform.id,
          formatName: `${ownerPlatform.name.split(' — ').pop() ?? ownerPlatform.name} · ${fmt.name}`,
        });
      }

      // Flatten into the full run list: one entry per (copy variant, placement).
      // The base label stays a single letter when there's no extra placement
      // (so existing single-format flows look unchanged); otherwise the label
      // carries the placement name for the leaderboard.
      type RunPlan = (typeof copyVariants)[number] & {
        runLabel: string; placementName: string; formatId: string; platformId: string;
      };
      const variants: RunPlan[] = [];
      for (const cv of copyVariants) {
        for (const pl of placementRuns) {
          variants.push({
            ...cv,
            runLabel: placementRuns.length > 1
              ? `${cv.label} · ${pl.formatName}`
              : cv.label,
            placementName: pl.formatName,
            formatId: pl.formatId,
            platformId: pl.platformId,
          });
        }
      }

      // Pillar B+ : 4-level anchor chain — (segment × interest) → segment →
      // interest → platform → overall. Interests are inferred from whichever
      // audience-picker mode is active (filter chips / free text / saved +
      // company product_category), then mapped to the same taxonomy as
      // outcomes.INTEREST_BUCKETS so frontend and backend agree.
      let calCtr: number | null = null;
      let calCpm: number | null = null;
      let calCvr: number | null = null;
      let calSource: string | null = null;
      let calNAds: number | null = null;
      let calFatigueLambda: number | null = null;
      // Build the user's interest list from the active mode.
      const profileInterestText = [
        w.companyProfile?.product_category ?? '',
        w.companyProfile?.industry ?? '',
        w.companyProfile?.value_proposition ?? '',
      ].join(' ');
      let userInterests: string[] = [];
      if (audienceMethod === 'filters') {
        userInterests = interestsFromChipIds(Object.keys(w.filterSelections ?? {}));
      } else if (audienceMethod === 'words') {
        userInterests = interestsFromText(
          (w.audienceDescription || '') + ' ' + profileInterestText);
      } else {
        // 'saved' — saved audiences don't yet carry their own interests,
        // so derive from the company profile as a soft proxy.
        userInterests = interestsFromText(profileInterestText);
      }
      try {
        const cal = await getLatestCalibration(w.currentCompanyId ?? undefined);
        if (cal) {
          const seg = audienceMethod === 'saved' ? w.audienceSegment : null;
          const platformKey = calibrationPlatformKey(w.platformId);
          // P3a: the chosen format's published benchmark is the root prior —
          // thin account data gets blended toward it instead of either fully
          // overriding it (3 ads of luck) or being fully ignored (2 ads).
          const fmtBench = platforms
            .find((p) => p.id === w.platformId)?.formats
            .find((f) => f.id === w.formatId)?.benchmarks ?? null;
          const pick = pickCalibrationAnchor(
            cal, seg ?? null, userInterests, platformKey,
            fmtBench ? { ctr: fmtBench.ctr, cpm: fmtBench.cpm } : null);
          calCtr = pick.ctr;
          calCpm = pick.cpm;
          calCvr = pick.cvr;
          calSource = pick.source;
          calNAds = pick.nAds;
          // P3b: adjust the CPM anchor for the CURRENT month's auction
          // seasonality, fitted from the account's own history (shrunk +
          // clamped server-side, so a noisy month can't distort it much).
          const season = cal.auction?.cpm_seasonality;
          if (calCpm != null && season?.usable) {
            const f = season.factors[String(new Date().getMonth() + 1)];
            if (f && f > 0) calCpm = calCpm * f;
          }
          // Simulation-based calibration: send the account's fitted fatigue
          // decay (λ, observed CTR slope per repeat view). The backend runs
          // the simcal bisection loop to convert it into the engine's logit
          // constant — never pasted in raw.
          const fat = cal.auction?.fatigue;
          if (fat?.usable && fat.lambda_per_exposure != null) {
            calFatigueLambda = fat.lambda_per_exposure;
          }
        }
      } catch { /* calibration is best-effort — never block a run */ }

      // Common simulate inputs reused per variant.
      const commonInputs = {
        company_description: w.companyDescription,
        audience_description: audienceDescription,
        audience_segment: audienceMethod === 'saved' ? w.audienceSegment : null,
        objective: w.objective,
        platform_id: w.platformId,
        format_id: w.formatId,
        budget: w.budget,
        days: w.days,
        daily_reach: w.dailyReach,
        n_runs: w.nRuns,
        // Real economics + market for THIS campaign (defaults from company
        // profile, overridable on the Run step). Conversion rate is entered
        // as a percentage in the UI; convert to a fraction here. A calibrated
        // conversion rate (from real data) wins when available.
        target_conversion_rate: (calCvr && calCvr > 0)
          ? calCvr
          : Math.max(Number(convRate) || 2.5, 0.01) / 100,
        // Calibrated click + cost benchmarks (null = fall back to generic).
        target_ctr: calCtr,
        cpm_override: calCpm,
        // Account fatigue decay — converted server-side to the engine
        // constant by the simulation-calibration loop (src/simcal.py).
        fatigue_lambda: calFatigueLambda,
        // Pillar B / B+: which calibration layer fed the anchor + how many
        // ads it was built from — surfaced in the report's data-provenance row.
        calibration_source: calSource,
        calibration_n_ads: calNAds,
        // Honest-ROAS: the workspace's conversion goal picks the CITED
        // industry CVR range shown when no real data calibrates the account.
        conversion_goal: cp?.conversion_goal ?? null,
        // Pillar B+: the user's mapped interests, sent so the backend can
        // store them on creative_scores + label the calibration source.
        interests: userInterests,
        // Opt-in budget saturation (assumption-based; blank = linear).
        reachable_audience: reachAudience ? Math.round(Number(reachAudience)) : null,
        avg_order_value: aov ? Number(aov) : null,
        currency,
        geo,
        // 'auto' picks the strongest provider with a key: Claude > OpenAI >
        // Gemini > heuristic. If you've set a Gemini key in /settings the
        // multimodal model will actually look at the image.
        visual_provider: 'auto' as const,
      };

      // Capture the exact requests we sent — saved with the campaign so it
      // can be re-run later against improved backend code. Each variant's
      // platform_id and format_id override commonInputs (they vary across
      // copy × placement expansion).
      const originalRequests = variants.map((v) => ({
        ...commonInputs,
        platform_id: v.platformId,
        format_id: v.formatId,
        image_path: v.imagePath,
        video_path: v.videoPath,
        headline: v.headline,
        primary_text: v.primaryText,
        description: v.description,
        cta: v.cta,
        link: v.link,
      }));

      // Run each variant + fetch market/cultural context ONCE (it depends on
      // geo + industry + month, not the creative — so one call covers all
      // variants). Concurrent to keep UX snappy; market context is best-effort
      // (a quota failure shouldn't block the forecast).
      const marketContextP = api.marketContext({
        geo,
        industry: w.companyProfile?.industry || '',
        product: w.companyProfile?.value_proposition || '',
        company_description: w.companyDescription,
      }).catch(() => null);

      // Run variants/placements SEQUENTIALLY — NOT in parallel. Each forecast
      // is memory-heavy (a 20-run Monte Carlo + vision); firing several at once
      // OOM-kills a small backend instance, and when the worker dies EVERY
      // request 502s until it restarts (not just the heavy one). One-at-a-time
      // is reliable. Market context (light) still runs concurrently.
      const results: Awaited<ReturnType<typeof api.simulate>>[] = [];
      for (const req of originalRequests) {
        results.push(await api.simulate(req));
      }
      const marketContext = await marketContextP;

      const firstResult = results[0];
      const hasMultiPlacement = placementRuns.length > 1;
      const savedVariants: SavedVariantResult[] = results.map((r, i) => {
        const v = variants[i];
        // Headline is what's displayed on the leaderboard. When the user is
        // running across multiple placements, lead with the placement so the
        // cards visually distinguish FB Reels vs IG Reels even when the copy
        // is identical.
        const baseHeadline = v.headline || `Variant ${v.label}`;
        const headline = hasMultiPlacement
          ? `${baseHeadline} · ${v.placementName}`
          : baseHeadline;
        return {
          label: v.runLabel,
          headline,
          thumbnailUrl: v.imageUrl,
          result: r,
          roasP50: r.mc.predicted_roas.p50,
          roiP50: r.mc.predicted_roi.p50,
          ctrPct: (r.mc.sample_ctrs.reduce((a, b) => a + b, 0) /
                   Math.max(r.mc.sample_ctrs.length, 1)) * 100,
          // A void forecast (banned / broken creative) is NOT "underperforming"
          // (which implies it runs but poorly) — it can't be forecast at all.
          verdictClass: (r.viability && (r.viability.forecast_valid === false || r.viability.runnable === false))
            ? 'void'
            : r.insights.verdict_class,
        };
      });

      // Aggregate ROAS = mean across variants. ROI same.
      const avgRoas = savedVariants.reduce((s, v) => s + v.roasP50, 0) / savedVariants.length;
      const avgRoi = savedVariants.reduce((s, v) => s + v.roiP50, 0) / savedVariants.length;
      const avgCtr = savedVariants.reduce((s, v) => s + v.ctrPct, 0) / savedVariants.length;
      // Worst-case verdict (most pessimistic) so dashboard is honest.
      const worstVerdict = (
        savedVariants.some((v) => v.verdictClass === 'void') ? 'void'
        : savedVariants.some((v) => v.verdictClass === 'underperforming') ? 'underperforming'
        : savedVariants.some((v) => v.verdictClass === 'break_even') ? 'break_even'
        : savedVariants.some((v) => v.verdictClass === 'positive') ? 'positive'
        : 'strong'
      ) as SavedCampaign['verdictClass'];

      const campaign: SavedCampaign = {
        id: (typeof crypto !== 'undefined' && crypto.randomUUID)
          ? crypto.randomUUID()
          : `c_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        name: (w.headline || `${firstResult.format.platform} · ${firstResult.format.name}`)
              + (savedVariants.length > 1 ? ` (${savedVariants.length} variants)` : ''),
        createdAt: Date.now(),
        platformName: firstResult.format.platform,
        formatName: firstResult.format.name,
        audienceLabel: firstResult.match.segment,
        budget: firstResult.mc.budget,
        days: firstResult.mc.sim_days,
        roasP50: avgRoas,
        roiP50: avgRoi,
        ctrPct: avgCtr,
        verdictClass: worstVerdict,
        thumbnailUrl: w.imageUrl,
        result: firstResult,
        variants: savedVariants.length > 1 ? savedVariants : undefined,
        originalRequests,
        marketContext,
      };
      w.addCampaign(campaign);
      w.setResult(firstResult);
      w.setCurrentCampaign(campaign);
      router.push('/result');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  function next() { w.setStep(Math.min(w.step + 1, 5)); }
  function back() { w.setStep(Math.max(w.step - 1, 1)); }

  return (
    <>
      <div className="text-[12.5px] text-ink-muted mb-2">Dashboard · New analysis</div>
      <div className="display-italic text-[38px] leading-[1.05]">
        Score a new <span className="gradient-text">ad campaign</span>
      </div>

      {running && (
        <div className="fixed inset-0 z-50 bg-bg-deep/70 backdrop-blur-sm flex items-center justify-center">
          <div className="bg-surface border border-border rounded-xl shadow-soft p-8 max-w-sm text-center mx-4">
            <div className="w-10 h-10 mx-auto mb-4 rounded-full border-[3px] border-coral border-t-transparent animate-spin" />
            <div className="font-heading text-[16px] font-bold mb-1">Running your forecast…</div>
            <div className="text-[13px] text-ink-muted leading-snug">This can take up to a minute — longer with multiple variants, which run one at a time. Keep this tab open.</div>
          </div>
        </div>
      )}

      <div className="flex gap-1 mt-6 mb-8">
        {STEPS.map((label, i) => {
          const n = i + 1;
          const active = w.step === n;
          const done = w.step > n;
          return (
            <div
              key={label}
              onClick={() => w.setStep(n)}
              className={clsx(
                'flex-1 flex items-center gap-2.5 py-3.5 px-3 border-b-[3px] text-[13.5px] font-medium transition-colors cursor-pointer hover:opacity-80',
                active && 'border-coral text-coral font-semibold',
                done && 'border-success text-success',
                !active && !done && 'border-border text-ink-muted',
              )}
            >
              <span className={clsx(
                'w-6 h-6 rounded-full flex items-center justify-center text-white text-[12px] font-bold font-mono',
                active && 'bg-gradient-sunset',
                done && 'bg-success',
                !active && !done && 'bg-border',
              )}>{n}</span>
              {label}
            </div>
          );
        })}
      </div>

      {/* STEP 1 — GOAL */}
      {w.step === 1 && (
        <div>
          <h2 className="font-heading text-[18px] font-bold tracking-tight">What&apos;s the campaign goal?</h2>
          <p className="text-ink-muted text-[14px] mb-4">Drives how the model weighs visual + psychology + audience match in scoring.</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
            {OBJECTIVES.map((o) => (
              <button
                key={o.id}
                onClick={() => w.setObjective(o.id)}
                className={clsx(
                  'text-left border-2 rounded-md p-5 transition-all bg-surface',
                  w.objective === o.id
                    ? 'border-coral bg-coral-soft shadow-soft'
                    : 'border-border hover:border-ink-faint',
                )}
              >
                <div className="text-3xl mb-2">{o.glyph}</div>
                <div className="font-semibold text-[16px]">{o.name}</div>
                <div className="text-ink-muted text-[13px]">{o.sub}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* STEP 2 — PLATFORM + FORMAT */}
      {w.step === 2 && (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-7">
          <div>
            <h2 className="font-heading text-[18px] font-bold tracking-tight">Where will it run?</h2>
            <p className="text-ink-muted text-[14px] mb-4">Pick the platform first — the format options below adapt accordingly.</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 mb-6">
              {platforms.map((p) => {
                const badge = PLATFORM_BADGES[p.id];
                return (
                  <button
                    key={p.id}
                    onClick={() => { w.setPlatform(p.id); w.setFormat(p.formats[0]?.id ?? ''); }}
                    className={clsx(
                      'text-left border-2 rounded-md p-3.5 transition-all bg-surface',
                      w.platformId === p.id ? 'border-coral bg-coral-soft' : 'border-border hover:border-ink-faint',
                    )}
                  >
                    <div className="flex items-center gap-2.5 mb-1.5">
                      <div className={`w-8 h-8 rounded-md ${badge?.bg ?? 'bg-ink'} text-white text-[12px] font-heading font-bold flex items-center justify-center`}>{badge?.label}</div>
                      <div className="font-semibold text-[14px]">{p.name}</div>
                    </div>
                    <div className="text-ink-muted text-[12px] leading-snug">{p.strength}</div>
                  </button>
                );
              })}
            </div>

            <h3 className="font-heading text-[15px] font-bold mt-4 mb-2">Ad format on {platform?.name ?? 'this platform'}</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {(platform?.formats ?? []).map((f) => {
                const maxSec = f.copy_limits?.video_seconds_max as number | undefined;
                return (
                  <button
                    key={f.id}
                    onClick={() => w.setFormat(f.id)}
                    className={clsx(
                      'text-left border-2 rounded-md p-3.5 transition-all bg-surface',
                      w.formatId === f.id ? 'border-coral bg-coral-soft' : 'border-border hover:border-ink-faint',
                    )}
                  >
                    <div className="font-semibold text-[14px]">{f.name}</div>
                    <div className="text-ink-muted text-[12px] mt-0.5 leading-snug">{f.best_for}</div>
                    <div className="mt-2 flex gap-1.5 flex-wrap">
                      <Pill tone="violet">{f.media_type}</Pill>
                      {/* Aspect-ratio + duration are the at-a-glance markers that make
                          Reels (9:16, ≤90s) instantly distinguishable from In-Feed
                          Video (1:1 / 4:5 / 9:16, ≤240s). */}
                      {f.aspect_ratios.length > 0 && (
                        <Pill tone="muted">{f.aspect_ratios.join(' / ')}</Pill>
                      )}
                      {maxSec && <Pill tone="muted">≤{maxSec}s</Pill>}
                      <Pill tone="lime">CTR {(f.benchmarks.ctr * 100).toFixed(2)}%</Pill>
                      {f.benchmarks.cpm > 0 && <Pill tone="muted">CPM ${f.benchmarks.cpm.toFixed(0)}</Pill>}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Also-run-on placements. Lets a Meta advertiser score the same
                creative on FB Reels AND IG Reels at once, or run a hero ad
                on multiple platforms. Each ticked placement = one extra
                simulation per copy variant (so 2 copy variants × 2 extra
                placements = 6 runs total). */}
            <AdditionalPlacements platforms={platforms} primaryFormatId={w.formatId} />
          </div>

          {format && <BenchmarkCard format={format} industry={w.companyProfile?.industry} />}
        </div>
      )}

      {/* STEP 3 — AUDIENCE */}
      {w.step === 3 && (
        <div>
          <h2 className="font-heading text-[18px] font-bold tracking-tight">Who&apos;s the audience?</h2>
          <p className="text-ink-muted text-[14px] mb-4">Build the audience with the same filters {platform?.name.split(' — ')[0] ?? 'the platform'} uses, describe one in words, or pick a saved audience.</p>

          {/* What we understood from your company — be transparent + let user fix */}
          {w.companyProfile && (
            <Card className="!bg-violet-soft !border-violet/30 mb-4">
              <div className="flex items-start gap-3">
                <span className="text-2xl">🧭</span>
                <div className="flex-1">
                  <div className="font-semibold text-[14px]">What we understood from your company</div>
                  <div className="text-[13px] text-ink mt-1">
                    Category: <strong>{w.companyProfile.product_category}</strong> · price tier <strong>{w.companyProfile.price_position}</strong> · model <strong>{w.companyProfile.business_model.toUpperCase()}</strong>
                    {w.companyProfile.source === 'heuristic' && (
                      <span className="text-warning ml-2 text-[12px] font-semibold">⚠ keyword-matched, may misclassify niche businesses</span>
                    )}
                  </div>
                  <div className="text-[12.5px] text-ink-muted mt-1.5">
                    If the category looks wrong, fix the description on <Link href="/company" className="underline text-violet font-semibold">Company profile</Link> — our suggested filters below adapt to it.
                  </div>
                </div>
              </div>
            </Card>
          )}

          <div className="inline-flex bg-bg-deep p-1 rounded-xl mb-5">
            {(['filters', 'words', 'saved'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setAudienceMethod(m)}
                disabled={m === 'saved' && w.savedAudiences.length === 0}
                className={clsx(
                  'px-4 py-2 rounded-lg text-[13px] font-medium transition-colors',
                  audienceMethod === m ? 'bg-surface shadow-soft text-ink font-semibold' : 'text-ink-muted',
                  m === 'saved' && w.savedAudiences.length === 0 && 'opacity-40 cursor-not-allowed',
                )}
              >
                {m === 'filters' ? 'Build with filters' : m === 'words' ? 'Describe in words'
                  : w.savedAudiences.some((a) => a.name.startsWith('✨'))
                    ? '✨ Smart & saved'
                    : `Saved audience${w.savedAudiences.length === 0 ? ' · empty' : ''}`}
              </button>
            ))}
          </div>

          {audienceMethod === 'saved' && (
            w.savedAudiences.length === 0 ? (
              <Card className="text-center py-10">
                <div className="text-ink-muted text-[14px]">No saved audiences yet. Describe one below — you can save it after a successful run.</div>
              </Card>
            ) : (
              <div className="flex flex-col gap-2.5">
                {w.savedAudiences.map((a) => (
                  <button
                    key={a.id}
                    onClick={() => {
                      // Set BOTH the segment (drives the persona filter) and
                      // the description (drives the interest-based calibration
                      // anchor + matcher) — segment alone silently dropped the
                      // audience's interests from the forecast.
                      w.setAudienceSegment(a.segment);
                      w.setAudienceDescription(a.description);
                    }}
                    className={clsx(
                      'text-left border-2 rounded-md p-4 transition-all bg-surface',
                      w.audienceSegment === a.segment && w.audienceDescription === a.description
                        ? 'border-coral bg-coral-soft' : 'border-border hover:border-ink-faint',
                    )}
                  >
                    <div className="font-semibold flex items-center gap-2">
                      {a.name}
                      {a.name.startsWith('✨') && (
                        <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded bg-coral-soft text-coral">smart · researched</span>
                      )}
                      {a.segment !== 'all' && (
                        <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded bg-violet-soft text-violet">{a.segment.replace(/_/g, ' ')}</span>
                      )}
                    </div>
                    <div className="text-ink-muted text-[12.5px]">{a.description}</div>
                  </button>
                ))}
              </div>
            )
          )}

          {audienceMethod === 'words' && (
            <div>
              <textarea
                className="input min-h-[120px]"
                value={w.audienceDescription}
                onChange={(e) => w.setAudienceDescription(e.target.value)}
                placeholder="e.g. Suburban new mums 28–38, ingredient-conscious, follow wellness creators on Instagram and TikTok."
              />
              <p className="help">We&apos;ll map this onto a 1,000-persona panel and pick the closest-fitting segment plus secondary fits.</p>
            </div>
          )}

          {audienceMethod === 'filters' && (
            <PlatformFilters platformId={w.platformId} />
          )}

          <Card className="mt-5 !bg-violet-soft !border-violet/30">
            <div className="text-[13.5px] text-violet">
              <strong>Filter set adapts to platform.</strong> Meta shows Detailed Targeting (Interests · Behaviours · Demographics · Life events). Google Ads shows affinity &amp; in-market audiences. LinkedIn shows job title · function · seniority · company size. TikTok shows creator categories &amp; video interactions. Same filters, the way each platform structures them.
            </div>
          </Card>
        </div>
      )}

      {/* STEP 4 — CREATIVE (with variants A / B / C / D) */}
      {w.step === 4 && (
        <>
          <div className="flex items-center gap-2 mb-4 flex-wrap">
            <span className="text-[13.5px] text-ink-muted mr-2">Variants:</span>
            {/* Variant A (always present, lives in base store fields) */}
            <button
              onClick={() => w.setActiveVariant(0)}
              className={clsx(
                'px-3.5 py-1.5 rounded-full border text-[13px] font-semibold transition-colors',
                w.activeVariant === 0
                  ? 'bg-coral text-white border-coral'
                  : 'bg-surface border-border hover:border-coral',
              )}
            >Variant A {w.imageUrl || w.videoUrl ? '·' : ''} {w.headline ? `"${w.headline.slice(0, 20)}${w.headline.length > 20 ? '…' : ''}"` : <span className="opacity-60">empty</span>}</button>
            {w.extraVariants.map((v, i) => (
              <button
                key={v.id}
                onClick={() => w.setActiveVariant(i + 1)}
                className={clsx(
                  'px-3.5 py-1.5 rounded-full border text-[13px] font-semibold transition-colors',
                  w.activeVariant === i + 1
                    ? 'bg-coral text-white border-coral'
                    : 'bg-surface border-border hover:border-coral',
                )}
              >Variant {v.label} {v.imageUrl || v.videoUrl ? '·' : ''} {v.headline ? `"${v.headline.slice(0, 20)}${v.headline.length > 20 ? '…' : ''}"` : <span className="opacity-60">empty</span>}
                <span
                  onClick={(e) => { e.stopPropagation(); w.removeVariant(i + 1); }}
                  className="ml-2 opacity-70 hover:opacity-100"
                >×</span>
              </button>
            ))}
            {w.extraVariants.length < 3 && (
              <button
                onClick={() => w.addVariant()}
                className="px-3.5 py-1.5 rounded-full border-2 border-dashed border-coral text-coral text-[13px] font-semibold hover:bg-coral-soft"
              >+ Add variant</button>
            )}
            {(w.extraVariants.length > 0) && (
              <span className="ml-2 text-[12.5px] text-ink-muted">
                We'll score each variant and show you a leaderboard + aggregate forecast.
              </span>
            )}
          </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-7">
          {format?.media_type === 'text' ? (
            <Card className="!bg-violet-soft !border-violet/30">
              <div className="font-heading text-[16px] font-bold mb-1.5">No upload needed for {format.name}</div>
              <div className="text-[13.5px] text-ink mb-2">This is a text-only format. Fill in the headlines and descriptions on the right — Google Search picks the best combination at auction time.</div>
              <div className="text-[12.5px] text-ink-muted">Required: {format.copy_limits.min_headlines ?? 3}+ headlines (≤{format.copy_limits.headline_chars} chars each), {format.copy_limits.min_descriptions ?? 2}+ descriptions (≤{format.copy_limits.description_chars} chars).</div>
            </Card>
          ) : (
            <div>
              <h2 className="font-heading text-[18px] font-bold tracking-tight">Upload your creative</h2>
              <p className="text-ink-muted text-[14px] mb-4">Required assets are dictated by the chosen format.</p>
              <div
                onClick={() => fileRef.current?.click()}
                className="border-2 border-dashed border-border rounded-md p-6 text-center bg-surface hover:border-coral hover:bg-coral-soft cursor-pointer transition-all min-h-[260px] flex flex-col items-center justify-center"
              >
                {activeMedia.imageUrl ? (
                  <div className="w-full">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={activeMedia.imageUrl} alt="creative preview" className="max-h-[220px] mx-auto rounded-md border border-border object-contain" />
                    <div className="text-[12.5px] text-ink-muted mt-3">Click to replace · or drop a new file</div>
                  </div>
                ) : activeMedia.videoUrl ? (
                  <div className="w-full">
                    <video src={activeMedia.videoUrl} controls className="max-h-[220px] mx-auto rounded-md border border-border" />
                    <div className="text-[12.5px] text-ink-muted mt-3">Video uploaded — visual scoring uses a heuristic on the file metadata for now (v1.1 will extract a thumbnail and run multimodal scoring on it).</div>
                  </div>
                ) : (
                  <>
                    <div className="w-11 h-11 rounded-lg bg-coral-soft text-coral flex items-center justify-center mx-auto mb-3 text-2xl">↑</div>
                    <div className="font-semibold mb-1">{uploading ? 'Uploading…' : 'Click to upload — or drop a file here'}</div>
                    <div className="text-ink-muted text-[12.5px]">{format?.media_type === 'video' ? 'MP4 / MOV — under 25MB' : 'PNG · JPG · WebP — under 25MB'}{format?.media_type === 'video' ? ' · or upload a still frame instead' : ''}</div>
                  </>
                )}
                <input
                  ref={fileRef}
                  type="file"
                  accept={format?.media_type === 'video' ? 'video/mp4,video/quicktime,image/png,image/jpeg' : 'image/png,image/jpeg,image/webp,image/gif'}
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) onPickFile(f);
                    e.target.value = '';
                  }}
                />
              </div>
              <div className="mt-3 text-[12.5px] text-ink-muted">
                {format
                  ? <>Required for <strong>{format.name}</strong>: {format.media_type}{format.aspect_ratios.length > 0 ? ` · aspect ratio ${format.aspect_ratios.join(' or ')}` : ''}</>
                  : 'Pick a format on Step 2 to see required asset specs.'}
              </div>
              {error && <div className="mt-3 text-[12.5px] text-danger bg-danger-soft border border-danger/30 rounded-md p-2.5">{error}</div>}
            </div>
          )}

          <div>
            <h2 className="font-heading text-[18px] font-bold tracking-tight">Copy {w.activeVariant > 0 ? `· Variant ${w.extraVariants[w.activeVariant - 1]?.label}` : ''}</h2>
            <p className="text-ink-muted text-[14px] mb-4">Same slots the platform would ask for.</p>
            {(() => {
              const isExtra = w.activeVariant > 0;
              const ei = w.activeVariant - 1;
              const v = isExtra ? w.extraVariants[ei] : null;
              const cur = {
                headline: isExtra ? (v?.headline ?? '') : w.headline,
                primaryText: isExtra ? (v?.primaryText ?? '') : w.primaryText,
                cta: isExtra ? (v?.cta ?? '') : w.cta,
                link: isExtra ? (v?.link ?? '') : w.link,
              };
              const set = (patch: any) => {
                if (isExtra) w.updateExtraVariant(ei, patch);
                else {
                  if ('headline' in patch) w.setCreativeField('headline', patch.headline);
                  if ('primaryText' in patch) w.setCreativeField('primaryText', patch.primaryText);
                  if ('cta' in patch) w.setCreativeField('cta', patch.cta);
                  if ('link' in patch) w.setCreativeField('link', patch.link);
                }
              };
              // Reuse text from a past AdProof analysis. A campaign can hold
              // several copy variants (A/B/C/D) — list EVERY variant so you can
              // pull any one's text, not just Variant A. (Imports carry ad names,
              // not body copy, so previous analyses are the reliable text source.)
              const pastOptions = w.savedCampaigns.flatMap((c) => {
                const reqs = c.originalRequests || [];
                const multi = reqs.filter((r) => r.headline || r.primary_text).length > 1;
                return reqs
                  .map((req, i) => ({
                    key: `${c.id}::${i}`, req, name: c.name, createdAt: c.createdAt,
                    vlabel: multi ? ` · Variant ${String.fromCharCode(65 + i)}` : '',
                  }))
                  .filter((o) => o.req.headline || o.req.primary_text);
              });
              const loadOption = (key: string) => {
                const [id, idx] = key.split('::');
                const req = w.savedCampaigns.find((x) => x.id === id)?.originalRequests?.[Number(idx)];
                if (req) set({ headline: req.headline || '', primaryText: req.primary_text || '',
                               cta: req.cta || '', link: req.link || '' });
              };
              return (
                <div className="space-y-3">
                  {pastOptions.length > 0 && (
                    <div>
                      <label className="label">Reuse copy from a previous analysis</label>
                      <select
                        className="input text-[13px]"
                        value=""
                        onChange={(e) => { if (e.target.value) loadOption(e.target.value); }}
                      >
                        <option value="">Start fresh — or pull text from a past campaign…</option>
                        {pastOptions.map((o) => (
                          <option key={o.key} value={o.key}>
                            {(o.name || 'Untitled').slice(0, 34)}{o.vlabel} · {new Date(o.createdAt).toLocaleDateString()}
                          </option>
                        ))}
                      </select>
                      <div className="text-[11.5px] text-ink-muted mt-1">Pulls the text (headline, body, CTA, URL) into this variant — edit freely after.</div>
                    </div>
                  )}
                  <div><label className="label">Headline</label><input className="input" value={cur.headline} onChange={(e) => set({ headline: e.target.value })} placeholder="Your headline" /></div>
                  <div><label className="label">Primary text / caption</label><textarea className="input" rows={3} value={cur.primaryText} onChange={(e) => set({ primaryText: e.target.value })} placeholder="What you'd say in the body of the post / ad" /></div>
                  <div className="grid grid-cols-2 gap-3">
                    <div><label className="label">CTA</label><input className="input" value={cur.cta} onChange={(e) => set({ cta: e.target.value })} placeholder="e.g. Shop now" /></div>
                    <div><label className="label">Destination URL</label><input className="input" value={cur.link} onChange={(e) => set({ link: e.target.value })} placeholder="https://" /></div>
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
        </>
      )}

      {/* STEP 5 — RUN */}
      {w.step === 5 && (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-7">
          <Card>
            <h2 className="font-heading text-[18px] font-bold tracking-tight">Campaign settings &amp; run</h2>
            <p className="text-ink-muted text-[14px] mb-5">Final spend and pacing, then we hand it to the simulator.</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label">Budget ({currency})</label>
                <input className="input" type="number" value={w.budget} onChange={(e) => w.setBudget(+e.target.value)} />
                <div className="help">Total over the flight</div>
              </div>
              <div>
                <label className="label">Campaign days</label>
                <input className="input" type="number" value={w.days} onChange={(e) => w.setDays(+e.target.value)} />
              </div>
              <div>
                <label className="label">
                  Monte Carlo runs
                  <HelpHint label="What is a Monte Carlo run?">
                    Each "run" is one independent simulation of your entire campaign with a different random seed (different exposure order, different conversion rolls). We run many to get a <em>distribution</em>: that's how you get p10/p50/p90 bands instead of a single overconfident number. 20 is the sweet spot — diminishing returns above 25.
                  </HelpHint>
                </label>
                <input className="input" type="number" value={w.nRuns} onChange={(e) => w.setNRuns(+e.target.value)} />
                <div className="help">Independent simulations, used to build the confidence band.</div>
              </div>
            </div>

            {/* Economics + market — the inputs that make the forecast real. */}
            <div className="mt-6 pt-5 border-t border-border">
              <div className="flex items-center gap-2 mb-1">
                <h3 className="font-heading text-[15px] font-bold tracking-tight">Economics &amp; market</h3>
                <HelpHint label="Why this matters">
                  A £5 product and a £5,000 course with the same budget have completely different break-even maths. We use <em>your</em> real numbers instead of a synthetic guess. These default from your company profile — override them to test a different market or product here.
                </HelpHint>
              </div>
              <p className="text-ink-muted text-[13px] mb-3">
                {cp?.avg_order_value != null
                  ? <>Defaults pulled from your company profile. Override for this campaign if needed.</>
                  : <>You haven&apos;t set economics on your <a href="/company" className="underline text-coral">company profile</a> yet — enter them here so the forecast is grounded in real numbers, not a guess.</>}
              </p>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Target market</label>
                  <select className="input" value={geo} onChange={(e) => setGeo(e.target.value)}>
                    {['UK', 'US', 'EU', 'Canada', 'Australia', 'Global'].map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
                  <div className="help">Drives benchmarks, currency &amp; the cultural lens.</div>
                </div>
                <div>
                  <label className="label">Currency</label>
                  <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                    {['GBP', 'USD', 'EUR', 'CAD', 'AUD'].map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Avg order / customer value</label>
                  <input className="input font-mono" type="number" min={0} inputMode="decimal"
                         value={aov} onChange={(e) => setAov(e.target.value)} placeholder="e.g. 250" />
                  <div className="help">{aov ? `${currency} ${Number(aov).toLocaleString()} per customer` : 'What one customer is worth'}</div>
                </div>
                <div>
                  <label className="label">
                    Expected conversion rate
                    <HelpHint label="Conversion rate">
                      Of the people who click your ad, what % actually buy / convert on your landing page? If you don&apos;t know, 2–3% is a typical starting point for cold traffic. This is the single biggest lever on whether the maths works.
                    </HelpHint>
                  </label>
                  <div className="flex items-center gap-2">
                    <input className="input font-mono" type="number" min={0.1} max={100} step={0.1} inputMode="decimal"
                           value={convRate} onChange={(e) => setConvRate(e.target.value)} />
                    <span className="text-ink-muted text-[14px]">%</span>
                  </div>
                  <div className="help">Clicks → customers. Typical cold traffic: 2–3%.</div>
                </div>
                <div>
                  <label className="label">
                    Reachable audience <span className="text-ink-faint font-normal">(optional)</span>
                    <HelpHint label="Reachable audience">
                      Roughly how many real people you can realistically reach with this targeting. If set, the forecast models diminishing returns — pour more budget into the same audience and ROAS falls as you re-show the same people. It&apos;s a modelling assumption, not from your data. Leave blank to keep the forecast linear in budget.
                    </HelpHint>
                  </label>
                  <input className="input font-mono" type="number" min={0} inputMode="numeric"
                         value={reachAudience} onChange={(e) => setReachAudience(e.target.value)} placeholder="e.g. 200000" />
                  <div className="help">Blank = no saturation. Set it to see budget have diminishing returns.</div>
                </div>
              </div>
              {!aov && (
                <div className="mt-3 text-[12.5px] text-yellow-800 bg-warning-soft border border-warning/30 rounded-md p-2.5">
                  No order value set — the forecast will fall back to a rough category estimate. Enter your real figure for grounded break-even maths.
                </div>
              )}
            </div>

            {error && <div className="mt-4 text-[13px] text-danger bg-danger-soft border border-danger/30 rounded-md p-3">{error}</div>}
          </Card>
          <Card>
            <div className="text-[11.5px] text-coral font-bold uppercase tracking-[0.09em] mb-2">Summary</div>
            <div className="space-y-2 text-[13.5px]">
              <div><strong>Goal:</strong> {w.objective}</div>
              <div><strong>Platform:</strong> {platform?.name ?? '—'}</div>
              <div><strong>Format:</strong> {format?.name ?? '—'}</div>
              {w.additionalFormatIds.length > 0 && (
                <div><strong>Also on:</strong> {w.additionalFormatIds.length} extra placement{w.additionalFormatIds.length > 1 ? 's' : ''}
                  {(() => {
                    const totalRuns = (1 + w.extraVariants.length) * (1 + w.additionalFormatIds.length);
                    return <span className="text-ink-muted"> · {totalRuns} runs total</span>;
                  })()}
                </div>
              )}
              <div><strong>Audience:</strong> {audienceMethod === 'saved' ? (w.audienceSegment ?? '—') : audienceMethod === 'words' ? (w.audienceDescription ? w.audienceDescription.slice(0, 60) + '…' : '—') : 'filters'}</div>
              {(() => {
                // Summary used to only check imagePath — missed videos AND missed
                // extra variants. Now counts every variant that has either an
                // image OR video so the user can see X/N at a glance.
                const totalVariants = 1 + w.extraVariants.length;
                const variantHas = (v: { imagePath?: string | null; videoPath?: string | null }) =>
                  !!(v.imagePath || v.videoPath);
                let uploadedCount = (w.imagePath || w.videoPath) ? 1 : 0;
                uploadedCount += w.extraVariants.filter(variantHas).length;
                const allUploaded = uploadedCount === totalVariants;
                const partial = uploadedCount > 0 && !allUploaded;
                return (
                  <div>
                    <strong>Creative:</strong>{' '}
                    {allUploaded
                      ? <span className="text-success">✓ uploaded ({uploadedCount}/{totalVariants})</span>
                      : partial
                        ? <span className="text-warning">partial — {uploadedCount}/{totalVariants} uploaded</span>
                        : <span className="text-danger">— not uploaded (0/{totalVariants})</span>}
                  </div>
                );
              })()}
              <div><strong>Market:</strong> {geo}</div>
              <div><strong>Budget:</strong> {currency} {w.budget.toLocaleString()} / {w.days} days</div>
              <div><strong>Order value:</strong> {aov ? `${currency} ${Number(aov).toLocaleString()}` : <span className="text-warning">not set</span>} · {convRate}% conv</div>
            </div>
          </Card>
        </div>
      )}

      <div className="flex justify-between mt-9 pt-6 border-t border-border">
        <Button variant="secondary" onClick={back} disabled={w.step === 1}>← Back</Button>
        {w.step < 5
          ? <Button size="lg" onClick={next}>Continue →</Button>
          : <Button size="lg" onClick={runSimulation} disabled={running}>{running ? 'Running…' : 'Run simulation →'}</Button>}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Additional placements — multi-select chip list for "also run on these
// formats". Groups by platform; chips show aspect-ratio + duration so the
// user can pick valid alternatives for their creative at a glance.
// ---------------------------------------------------------------------------

function AdditionalPlacements({
  platforms,
  primaryFormatId,
}: {
  platforms: Platform[];
  primaryFormatId: string;
}) {
  const additionalFormatIds = useApp((s) => s.additionalFormatIds);
  const toggleAdditionalFormat = useApp((s) => s.toggleAdditionalFormat);
  const clearAdditionalFormats = useApp((s) => s.clearAdditionalFormats);

  // Find the primary so we can hide it (it's already the headline run).
  const primary = platforms.flatMap((p) => p.formats).find((f) => f.id === primaryFormatId);
  // Bias the suggestions: if primary is Meta, surface the OTHER Meta formats
  // first (since "FB and IG run together" is the most common ask).
  const primaryPlatformId = platforms.find((p) =>
    p.formats.some((f) => f.id === primaryFormatId))?.id ?? '';
  const isMetaPrimary = primaryPlatformId.startsWith('meta_');

  const grouped = platforms
    .map((p) => ({
      platform: p,
      formats: p.formats.filter((f) => f.id !== primaryFormatId),
    }))
    .filter((g) => g.formats.length > 0)
    .sort((a, b) => {
      // Meta first when primary is Meta, else current platform first.
      const aMeta = a.platform.id.startsWith('meta_');
      const bMeta = b.platform.id.startsWith('meta_');
      if (isMetaPrimary && aMeta !== bMeta) return aMeta ? -1 : 1;
      if (a.platform.id === primaryPlatformId) return -1;
      if (b.platform.id === primaryPlatformId) return 1;
      return 0;
    });

  if (!primary) return null;

  return (
    <div className="mt-6 border-t border-border pt-5">
      <div className="flex items-baseline justify-between mb-1">
        <h3 className="font-heading text-[15px] font-bold tracking-tight">
          Also run this creative on… <span className="text-ink-muted font-normal">(optional)</span>
        </h3>
        {additionalFormatIds.length > 0 && (
          <button onClick={clearAdditionalFormats}
            className="text-coral font-semibold text-[12px]">Clear all</button>
        )}
      </div>
      <p className="text-ink-muted text-[12.5px] mb-3 leading-snug">
        Score the same creative on extra placements at the same time. Each ticked placement
        becomes an extra variant per copy version — so 2 copy variants × 2 extra placements = 6 runs.
        Watch the aspect-ratio pills: a 1:1 image can&apos;t legitimately run on a 9:16 Reel.
      </p>
      {grouped.map(({ platform: p, formats }) => (
        <div key={p.id} className="mb-3 last:mb-0">
          <div className="text-[11px] text-ink-muted font-bold uppercase tracking-[0.07em] mb-1.5">
            {p.name}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {formats.map((f) => {
              const on = additionalFormatIds.includes(f.id);
              const maxSec = f.copy_limits?.video_seconds_max as number | undefined;
              return (
                <button
                  key={f.id}
                  onClick={() => toggleAdditionalFormat(f.id)}
                  className={clsx(
                    'inline-flex items-center gap-2 px-2.5 py-1.5 rounded-full border text-[12px] transition-colors',
                    on
                      ? 'bg-coral text-white border-coral font-semibold'
                      : 'bg-surface border-border text-ink hover:border-coral',
                  )}
                >
                  <span>{f.name}</span>
                  <span className={clsx('text-[10.5px] font-normal',
                    on ? 'text-white/85' : 'text-ink-muted')}>
                    {f.aspect_ratios.join('/')}
                    {maxSec ? ` · ≤${maxSec}s` : ''}
                  </span>
                  {on && <span>×</span>}
                </button>
              );
            })}
          </div>
        </div>
      ))}
      {additionalFormatIds.length > 0 && (
        <div className="mt-3 text-[12.5px] bg-coral-soft border border-coral/30 rounded-md p-3">
          <strong className="text-coral">{additionalFormatIds.length} extra placement{additionalFormatIds.length > 1 ? 's' : ''}.</strong>
          {' '}Each copy variant will also run on {additionalFormatIds.length === 1 ? 'this' : 'these'} —
          you&apos;ll see a per-placement leaderboard on the result page.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Platform-native filters — data-driven, backed by the store. The chip set
// adapts to platform; chip selections feed audience matching at run time.
// ---------------------------------------------------------------------------

function PlatformFilters({ platformId }: { platformId: string }) {
  const filterSelections = useApp((s) => s.filterSelections);
  const toggleFilter = useApp((s) => s.toggleFilter);
  const clearFilters = useApp((s) => s.clearFilters);
  const setManyFilters = useApp((s) => s.setManyFilters);
  const profile = useApp((s) => s.companyProfile);
  const savedAudiences = useApp((s) => s.savedAudiences);
  const addAudience = useApp((s) => s.addAudience);
  const currentCompanyId = useApp((s) => s.currentCompanyId);
  const [saveToast, setSaveToast] = useState<string | null>(null);
  // Tracks the chip-signature of the last tailor so a follow-up tailor with
  // a different mix can offer 'save as new' without dupes. Reserved for the
  // next slice; read-out happens in the auto-save check below.
  const [, setLastTailorSig] = useState<string | null>(null);

  const cards = filtersForPlatform(platformId);
  const selectedIds = Object.keys(filterSelections);
  const selectedCount = selectedIds.length;
  const customChips = selectedIds.filter((id) => id.startsWith('custom:'));
  const hasSelections = selectedCount > 0;

  const [tailoring, setTailoring] = useState(false);
  const [rationale, setRationale] = useState<string | null>(null);
  const [tailorErr, setTailorErr] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [customText, setCustomText] = useState('');

  // Flatten the catalogue so the LLM can only return ids we know how to toggle.
  const allChips = cards.flatMap((card) =>
    card.groups.flatMap((g) => g.chips.map((ch) =>
      ({ id: ch.id, label: ch.label, group: g.title || card.title }))));

  async function tailorToCompany() {
    setTailoring(true); setTailorErr(null);
    try {
      const r = await api.suggestAudience({
        company_description: profile?.raw_description ?? '',
        industry: profile?.industry ?? '',
        product_category: profile?.product_category ?? '',
        business_model: profile?.business_model ?? '',
        value_proposition: profile?.value_proposition ?? '',
        conversion_goal: profile?.conversion_goal,
        platform_id: platformId,
        available_chips: allChips,
      });
      // Drop any existing gender (single-select) and let the AI's one win.
      const next = new Set(selectedIds.filter((id) => !id.startsWith('gender:')));
      r.selected_chip_ids.filter((id) => !id.startsWith('gender:')).forEach((id) => next.add(id));
      r.custom_interests.forEach((t) => next.add(`custom:${t}`));
      if (r.gender) next.add(`gender:${r.gender}`);
      const chipList = [...next];
      setManyFilters(chipList);
      setRationale(r.rationale || null);
      setShowAll(false);                     // collapse to the relevant groups
      if (r.source !== 'llm') setTailorErr('AI was unavailable — pick chips manually, or try again.');

      // Fix #4: auto-save the tailored set as a SavedAudience the first time
      // we tailor (owner ask: don't make users repeat this step). The chip
      // selection is serialised into the description field so it survives
      // existing audiences-table schema with no migration needed. Skipped
      // when an identical chipset is already saved.
      const sig = chipList.slice().sort().join('|');
      setLastTailorSig(sig);
      const existingSigs = new Set(savedAudiences.map((a) => {
        try {
          const parsed = JSON.parse(a.description || '{}');
          return Array.isArray(parsed?.chips) ? parsed.chips.slice().sort().join('|') : '';
        } catch { return ''; }
      }));
      if (!existingSigs.has(sig)) {
        const name = savedAudiences.length === 0
          ? `Auto-tailored for ${profile?.company_name || 'your brand'}`
          : `Tailored ${new Date().toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}`;
        addAudience({
          id: crypto.randomUUID?.() ?? `aud_${Date.now()}`,
          companyId: currentCompanyId ?? undefined,
          name,
          description: JSON.stringify({
            chips: chipList,
            rationale: r.rationale || '',
            tailored_at: new Date().toISOString(),
            platform_id: platformId,
          }),
          segment: 'all',                    // chip-based audience; segment falls back
          createdAt: Date.now(),
          usedInCount: 0,
        });
        setSaveToast(savedAudiences.length === 0
          ? `✓ Saved as your first audience: "${name}"`
          : `✓ Saved as new audience: "${name}"`);
        setTimeout(() => setSaveToast(null), 5000);
      }
    } catch (e) {
      setTailorErr((e as Error).message);
    } finally { setTailoring(false); }
  }

  function addCustom() {
    const t = customText.trim();
    if (!t) return;
    setManyFilters([...new Set([...selectedIds, `custom:${t}`])]);
    setCustomText('');
  }

  function groupVisible(card: FilterCardType, g: { chips: { id: string }[] }) {
    if (showAll || !hasSelections) return true;
    if (card.id.includes('gender') || card.id.includes('location')) return true;
    return g.chips.some((ch) => filterSelections[ch.id]);
  }

  return (
    <div className="space-y-3">
      {/* Tailor-to-company bar */}
      <Card className="!bg-coral-soft !border-coral/30">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="text-[13.5px] flex-1">
            <strong>✨ Tailor to {profile?.company_name || 'your company'}.</strong>{' '}
            We read your profile and pick only the interests, behaviours &amp; demographics that fit — and hide the rest.
          </div>
          <Button size="sm" onClick={tailorToCompany} disabled={tailoring}>
            {tailoring ? 'Tailoring…' : '✨ Tailor to my company'}
          </Button>
          {hasSelections && (
            <Button size="sm" variant="ghost" onClick={() => { clearFilters(); setRationale(null); }}>Clear</Button>
          )}
        </div>
        {rationale && <div className="text-[12.5px] text-ink mt-2 pt-2 border-t border-coral/20"><strong>Why:</strong> {rationale}</div>}
        {saveToast && <div className="text-[12.5px] text-success mt-2 bg-lime-soft border border-lime-deep/30 rounded-md px-2.5 py-1.5">{saveToast}</div>}
        {tailorErr && <div className="text-[12.5px] text-danger mt-2">{tailorErr}</div>}
      </Card>

      <div className="text-[12.5px] text-ink-muted px-1 flex items-center gap-2 flex-wrap">
        <span>{selectedCount === 0
          ? 'Nothing selected yet — tailor to your company, or click chips below.'
          : <><strong className="text-ink">{selectedCount}</strong> selected — sent as the audience on Run.</>}</span>
        <div className="flex-1" />
        {hasSelections && (
          <button type="button" className="text-coral font-semibold text-[12.5px]"
            onClick={() => setShowAll((v) => !v)}>
            {showAll ? 'Show only relevant ↑' : 'Show everything ↓'}
          </button>
        )}
      </div>

      {/* Free-text custom interests */}
      <Card>
        <div className="text-[11.5px] text-ink-muted font-bold uppercase tracking-[0.07em] mb-2">Your own interests — type anything</div>
        <div className="flex items-center gap-2 flex-wrap">
          {customChips.map((id) => (
            <span key={id} onClick={() => toggleFilter(id)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-coral bg-coral-soft text-coral text-[13px] font-semibold cursor-pointer">
              {id.slice(7)} <span className="font-bold">×</span>
            </span>
          ))}
          <input value={customText} onChange={(e) => setCustomText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addCustom(); } }}
            placeholder="e.g. marketing automation, fly fishing…"
            className="input flex-1 min-w-[200px] text-[13px]" />
          <Button size="sm" variant="secondary" onClick={addCustom} disabled={!customText.trim()}>Add</Button>
        </div>
      </Card>

      {cards.map((card) => {
        const visGroups = card.groups.filter((g) => groupVisible(card, g));
        if (visGroups.length === 0) return null;
        return (
          <FilterCardPanel key={card.id} card={{ ...card, groups: visGroups }}
            selections={filterSelections} onToggle={toggleFilter} />
        );
      })}
    </div>
  );
}

function FilterCardPanel({
  card,
  selections,
  onToggle,
}: {
  card: FilterCardType;
  selections: Record<string, true>;
  onToggle: (id: string) => void;
}) {
  return (
    <Card>
      <div className="font-semibold text-[14px] mb-3 flex items-center gap-2">
        <span>{card.glyph}</span>{card.title}
      </div>
      {card.groups.map((g) => (
        <div key={g.id} className="mb-3 last:mb-0">
          {g.title && (
            <div className="text-[11.5px] text-ink-muted font-bold uppercase tracking-[0.07em] mb-2">{g.title}</div>
          )}
          <div className="flex flex-wrap gap-2">
            {g.chips.map((ch) => {
              const on = selections[ch.id] === true;
              return (
                <span
                  key={ch.id}
                  onClick={() => onToggle(ch.id)}
                  className={clsx(
                    'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-[13px] font-medium cursor-pointer transition-colors',
                    on
                      ? 'bg-coral-soft border-coral text-coral font-semibold'
                      : 'bg-surface border-border hover:border-coral',
                  )}
                >
                  {ch.label}{on && <span className="text-coral font-bold">×</span>}
                </span>
              );
            })}
          </div>
        </div>
      ))}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Benchmark card — shows stored 2026 numbers + a Gemini-grounded "refresh
// from the web" button that pulls current published averages.
// ---------------------------------------------------------------------------

function BenchmarkCard({ format, industry }: { format: any; industry?: string }) {
  const [refreshing, setRefreshing] = useState(false);
  const [refresh, setRefresh] = useState<BenchmarkRefreshResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const asOf = format.benchmarks.as_of ?? '2026';
  const trend = format.benchmarks.trend_note;

  async function pullLive() {
    setRefreshing(true); setErr(null); setRefresh(null);
    try {
      setRefresh(await api.refreshBenchmarks(format.id, industry));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <aside className="border border-border bg-surface rounded-md p-5 sticky top-6 self-start shadow-soft">
      <div className="flex items-center justify-between">
        <div className="text-[11.5px] text-coral font-bold uppercase tracking-[0.09em]">Benchmark</div>
        <Pill tone="muted">as of {asOf}</Pill>
      </div>
      <h3 className="display-italic text-[28px] mt-1 leading-none">
        {(format.benchmarks.ctr * 100).toFixed(2)}%<span className="text-ink-muted text-[14px] font-sans not-italic"> CTR</span>
      </h3>
      {format.benchmarks.ctr_range && (
        <div className="text-ink-muted text-[12px] font-mono mt-1.5">range {(format.benchmarks.ctr_range[0] * 100).toFixed(2)}–{(format.benchmarks.ctr_range[1] * 100).toFixed(2)}%</div>
      )}
      {format.benchmarks.source_2024 && format.benchmarks.source_2024.ctr && (
        <div className="text-ink-muted text-[12px] mt-1">
          2024 was <span className="font-mono">{(format.benchmarks.source_2024.ctr * 100).toFixed(2)}%</span>{format.benchmarks.source_2024.cpm ? ` / $${format.benchmarks.source_2024.cpm} CPM` : ''}
        </div>
      )}
      {trend && (
        <div className="text-[12px] text-ink mt-2 italic leading-snug">{trend}</div>
      )}

      <hr className="my-3 border-border" />
      <div className="text-[13px] leading-snug"><strong>Best for:</strong> {format.best_for}</div>
      <div className="text-[13px] leading-snug mt-2"><strong>Tone:</strong> {format.tone}</div>
      <div className="text-[13px] leading-snug mt-2"><strong>Required assets:</strong> {format.asset_types.join(', ')}</div>

      <hr className="my-3 border-border" />
      <Button size="sm" variant="secondary" onClick={pullLive} disabled={refreshing} className="w-full">
        {refreshing ? '🔎 Searching the web…' : '🔎 Refresh from web (Gemini)'}
      </Button>
      <div className="help mt-1.5">Pulls current published CTR/CPM via Gemini's Google-search grounding. Needs your Gemini key in /settings.</div>

      {err && (
        <div className="mt-3 text-[12px] text-danger bg-danger-soft border border-danger/30 rounded-md p-2.5">{err}</div>
      )}

      {refresh && refresh.fetched && (
        <div className="mt-3 bg-lime-soft border border-lime-deep/30 rounded-md p-3 text-[12.5px]">
          <div className="font-bold text-[11.5px] text-lime-deep uppercase tracking-[0.06em] mb-1.5">Live web result</div>
          {refresh.fetched.ctr !== undefined && refresh.fetched.ctr !== null && (
            <div>CTR: <strong>{(refresh.fetched.ctr * 100).toFixed(2)}%</strong> {refresh.delta_pct.ctr !== null && (
              <span className={refresh.delta_pct.ctr >= 0 ? 'text-success' : 'text-danger'}>
                {' '}({refresh.delta_pct.ctr >= 0 ? '+' : ''}{refresh.delta_pct.ctr}% vs stored)
              </span>
            )}</div>
          )}
          {refresh.fetched.cpm !== undefined && refresh.fetched.cpm !== null && (
            <div>CPM: <strong>${refresh.fetched.cpm}</strong> {refresh.delta_pct.cpm !== null && (
              <span className={refresh.delta_pct.cpm <= 0 ? 'text-success' : 'text-danger'}>
                {' '}({refresh.delta_pct.cpm >= 0 ? '+' : ''}{refresh.delta_pct.cpm}% vs stored)
              </span>
            )}</div>
          )}
          {refresh.fetched.year && (
            <div className="mt-1.5 text-ink-muted">Year: {refresh.fetched.year}</div>
          )}
          {refresh.fetched.source && (
            <div className="text-ink-muted mt-1 line-clamp-2">Sources: {refresh.fetched.source}</div>
          )}
          {refresh.fetched.notes && (
            <div className="text-ink mt-2 italic leading-snug">{refresh.fetched.notes}</div>
          )}
        </div>
      )}
    </aside>
  );
}
