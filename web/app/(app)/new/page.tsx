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
import type { BenchmarkRefreshResponse, Platform, SavedCampaign, SavedVariantResult } from '@/lib/types';

// Map a wizard platform id to the calibration bucket produced by the ingest.
function calibrationPlatformKey(platformId: string): string {
  const p = platformId.toLowerCase();
  if (p.includes('instagram')) return 'meta_instagram';
  if (p.includes('facebook') || p.includes('meta')) return 'meta_facebook';
  if (p.includes('linkedin')) return 'linkedin';
  if (p.includes('tiktok')) return 'tiktok';
  if (p.includes('youtube')) return 'youtube';
  if (p.includes('google') || p.includes('search')) return 'google_search';
  return platformId;
}
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
      const r = await api.upload(file);
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

      // Build the full variant list: Variant A (base store) + any extras.
      const variants = [
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
        const missing = variants.filter((v) => !v.imagePath && !v.videoPath);
        if (missing.length) {
          throw new Error(
            missing.length === variants.length
              ? `Upload ${format?.media_type === 'video' ? 'a video' : 'an image'} for ${format?.name ?? 'this format'} before running — there's nothing to analyse (and no ad to run) without a creative.`
              : `Variant${missing.length > 1 ? 's' : ''} ${missing.map((m) => m.label).join(', ')} ${missing.length > 1 ? 'are' : 'is'} missing a creative. Add ${format?.media_type === 'video' ? 'a video' : 'an image'} to every variant before running.`,
          );
        }
      }

      // Per-account calibration (Path B): if the user has uploaded their ad
      // history, use THEIR real CTR / CPM for this platform instead of the
      // generic format benchmark — so the forecast reflects their account.
      let calCtr: number | null = null;
      let calCpm: number | null = null;
      let calCvr: number | null = null;
      try {
        const cal = await getLatestCalibration(w.currentCompanyId ?? undefined);
        const pc = cal?.by_platform?.[calibrationPlatformKey(w.platformId)];
        if (pc && pc.real_ctr) {
          calCtr = pc.real_ctr;
          calCpm = pc.real_cpm;
          calCvr = pc.real_cvr;
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
      // can be re-run later against improved backend code.
      const originalRequests = variants.map((v) => ({
        ...commonInputs,
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

      const [results, marketContext] = await Promise.all([
        Promise.all(originalRequests.map((req) => api.simulate(req))),
        marketContextP,
      ]);

      const firstResult = results[0];
      const savedVariants: SavedVariantResult[] = results.map((r, i) => ({
        label: variants[i].label,
        headline: variants[i].headline || `Variant ${variants[i].label}`,
        thumbnailUrl: variants[i].imageUrl,
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
      }));

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

      <div className="flex gap-1 mt-6 mb-8">
        {STEPS.map((label, i) => {
          const n = i + 1;
          const active = w.step === n;
          const done = w.step > n;
          return (
            <div
              key={label}
              onClick={() => done && w.setStep(n)}
              className={clsx(
                'flex-1 flex items-center gap-2.5 py-3.5 px-3 border-b-[3px] text-[13.5px] font-medium transition-colors',
                done && 'cursor-pointer',
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
              {(platform?.formats ?? []).map((f) => (
                <button
                  key={f.id}
                  onClick={() => w.setFormat(f.id)}
                  className={clsx(
                    'text-left border-2 rounded-md p-3.5 transition-all bg-surface',
                    w.formatId === f.id ? 'border-coral bg-coral-soft' : 'border-border hover:border-ink-faint',
                  )}
                >
                  <div className="font-semibold text-[14px]">{f.name}</div>
                  <div className="text-ink-muted text-[12px] mt-0.5">{f.best_for}</div>
                  <div className="mt-2 flex gap-1.5 flex-wrap">
                    <Pill tone="violet">{f.media_type}</Pill>
                    <Pill tone="lime">CTR {(f.benchmarks.ctr * 100).toFixed(2)}%</Pill>
                    {f.benchmarks.cpm > 0 && <Pill tone="muted">CPM ${f.benchmarks.cpm.toFixed(0)}</Pill>}
                  </div>
                </button>
              ))}
            </div>
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
                {m === 'filters' ? 'Build with filters' : m === 'words' ? 'Describe in words' : `Saved audience${w.savedAudiences.length === 0 ? ' · empty' : ''}`}
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
                    onClick={() => w.setAudienceSegment(a.segment)}
                    className={clsx(
                      'text-left border-2 rounded-md p-4 transition-all bg-surface',
                      w.audienceSegment === a.segment ? 'border-coral bg-coral-soft' : 'border-border hover:border-ink-faint',
                    )}
                  >
                    <div className="font-semibold">{a.name}</div>
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
              return (
                <div className="space-y-3">
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
                  Daily reach
                  <HelpHint label="What is daily reach?">
                    The fraction of your audience exposed to the ad on any given day. 0.35 means 35% of your audience sees it daily. Higher reach = more total impressions but more <em>frequency</em> (the same person seeing it repeatedly), which triggers ad fatigue.
                  </HelpHint>
                </label>
                <input className="input" type="number" step={0.05} min={0.1} max={1} value={w.dailyReach} onChange={(e) => w.setDailyReach(+e.target.value)} />
                <div className="help">Fraction of audience exposed/day. Typical: 0.20–0.40.</div>
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
              <div><strong>Audience:</strong> {audienceMethod === 'saved' ? (w.audienceSegment ?? '—') : audienceMethod === 'words' ? (w.audienceDescription ? w.audienceDescription.slice(0, 60) + '…' : '—') : 'filters'}</div>
              <div><strong>Creative:</strong> {w.imagePath ? '✓ uploaded' : '— not uploaded'}</div>
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
// Platform-native filters — data-driven, backed by the store. The chip set
// adapts to platform; chip selections feed audience matching at run time.
// ---------------------------------------------------------------------------

function PlatformFilters({ platformId }: { platformId: string }) {
  const filterSelections = useApp((s) => s.filterSelections);
  const toggleFilter = useApp((s) => s.toggleFilter);
  const clearFilters = useApp((s) => s.clearFilters);
  const setManyFilters = useApp((s) => s.setManyFilters);
  const profile = useApp((s) => s.companyProfile);

  const cards = filtersForPlatform(platformId);
  const selectedCount = Object.keys(filterSelections).length;
  const suggestions = suggestedChips(
    profile?.product_category ?? 'general',
    platformId,
  );

  function applySuggestions() {
    const next = { ...filterSelections };
    for (const id of suggestions) next[id] = true;
    setManyFilters(Object.keys(next));
  }

  return (
    <div className="space-y-3">
      {/* Suggestion bar */}
      {suggestions.length > 0 && (
        <Card className="!bg-coral-soft !border-coral/30 flex items-center gap-3 flex-wrap">
          <span className="text-[13.5px]">
            <strong>Suggested for {profile?.product_category ?? 'your category'}:</strong>{' '}
            {suggestions.length} filters that fit a {profile?.industry || profile?.product_category || 'company like yours'}.
          </span>
          <div className="flex-1" />
          <Button size="sm" variant="secondary" onClick={applySuggestions}>Apply suggested</Button>
          <Button size="sm" variant="ghost" onClick={clearFilters}>Clear all</Button>
        </Card>
      )}
      <div className="text-[12.5px] text-ink-muted px-1">
        {selectedCount === 0
          ? <>No filters selected yet — click chips to build your audience.</>
          : <><strong className="text-ink">{selectedCount}</strong> filter{selectedCount === 1 ? '' : 's'} selected. They'll be sent as the audience description on Run.</>
        }
      </div>

      {cards.map((card) => (
        <FilterCardPanel
          key={card.id}
          card={card}
          selections={filterSelections}
          onToggle={toggleFilter}
        />
      ))}
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
