'use client';
// The Simulation Lab — watch the agent-based model run. Move a factor, and
// ~600 simulated consumers re-live the campaign in front of you: who saw the
// ad, who clicked, who converted, day by day.
//
// Design: the one dark surface in AdProof — an instrument panel. State colors
// validated for color-vision deficiency (blue → coral → green ladder, ΔE 15.6
// worst pair on the dark surface) with dot SIZE as the secondary encoding so
// color is never the only signal.
//
// Honesty: every default is traceable (calibration / profile / history, each
// chip says which); the creative slider is labelled hypothetical; uncertainty
// is drawn as bands, not footnoted. Numeric-only engine runs — scoring a real
// creative stays the wizard's job.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/lib/api';
import { getLatestCalibration } from '@/lib/db';
import { useApp } from '@/lib/store';
import {
  calibrationPlatformKey, interestsFromText, pickCalibrationAnchor,
} from '@/lib/anchor';
import type { AccountCalibration, LabRunResult, Platform } from '@/lib/types';

// Lab surface + state palette (validated: see header comment).
const LAB = {
  bg: '#14181D', panel: '#1B2127', line: '#2A333B',
  ink: '#E9EDF1', muted: '#93A0AB', faint: '#5E6B76',
  unexposed: '#3A444D', exposed: '#3E86C4', clicked: '#E06B3F', converted: '#4EA06B',
};

const SEGMENTS = [
  ['all', 'Everyone'], ['gen_z', 'Gen Z (≤27)'], ['millennials', 'Millennials (28–43)'],
  ['gen_x', 'Gen X (44–59)'], ['boomers', 'Boomers (60+)'], ['high_income', 'High income'],
  ['budget_conscious', 'Budget-conscious'], ['early_adopters', 'Early adopters'],
  ['socially_influenced', 'Socially influenced'],
] as const;

type Provenance = 'your data' | 'industry' | 'assumption';

function ProvChip({ p }: { p: Provenance }) {
  const tone = p === 'your data' ? 'success' : p === 'industry' ? 'warning' : 'muted';
  return <Pill tone={tone as 'success' | 'warning' | 'muted'}>{p}</Pill>;
}

// ---------------------------------------------------------------------------
// Population field — the hero canvas
// ---------------------------------------------------------------------------
function PopulationField({ frames, agents }: { frames: string[]; agents: number }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [day, setDay] = useState(0);
  const [playing, setPlaying] = useState(true);
  const reduced = typeof window !== 'undefined'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  useEffect(() => { setDay(0); setPlaying(!reduced); }, [frames, reduced]);

  useEffect(() => {
    if (!playing || frames.length === 0) return;
    const t = setInterval(() => setDay((d) => (d + 1) % frames.length), 600);
    return () => clearInterval(t);
  }, [playing, frames.length]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || frames.length === 0) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const frame = frames[Math.min(day, frames.length - 1)];
    const cols = Math.ceil(Math.sqrt(agents * (canvas.width / canvas.height)));
    const rows = Math.ceil(agents / cols);
    const cw = canvas.width / cols; const ch = canvas.height / rows;
    const r = Math.min(cw, ch) * 0.30;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (let i = 0; i < agents && i < frame.length; i++) {
      const s = frame.charCodeAt(i) - 48;  // '0'..'3'
      const x = (i % cols + 0.5) * cw;
      const y = (Math.floor(i / cols) + 0.5) * ch;
      ctx.beginPath();
      // Size ladder = secondary encoding: converted > clicked > exposed.
      ctx.arc(x, y, s === 3 ? r * 1.5 : s === 2 ? r * 1.25 : r, 0, Math.PI * 2);
      ctx.fillStyle = s === 3 ? LAB.converted : s === 2 ? LAB.clicked
        : s === 1 ? LAB.exposed : LAB.unexposed;
      ctx.fill();
    }
  }, [day, frames, agents]);

  if (frames.length === 0) return null;
  return (
    <div>
      <canvas ref={canvasRef} width={760} height={340}
        style={{ width: '100%', height: 'auto', borderRadius: 10, background: LAB.bg }}
        aria-label={`Simulated audience of ${agents} people, day ${day + 1} of ${frames.length}`} />
      <div className="flex items-center gap-3 mt-2.5 flex-wrap">
        <button type="button" onClick={() => setPlaying((p) => !p)}
          className="px-3 py-1.5 rounded-md text-[12px] font-bold"
          style={{ background: LAB.clicked, color: '#fff' }}>
          {playing ? '⏸ Pause' : '▶ Play'}
        </button>
        <input type="range" min={0} max={frames.length - 1} value={day}
          onChange={(e) => { setPlaying(false); setDay(Number(e.target.value)); }}
          className="flex-1 min-w-[120px]" style={{ accentColor: LAB.clicked }}
          aria-label="Campaign day" />
        <span className="text-[12px] font-mono" style={{ color: LAB.muted }}>
          day {day + 1}/{frames.length}
        </span>
      </div>
      <div className="flex gap-4 flex-wrap mt-2 text-[11px]" style={{ color: LAB.muted }}>
        {[[LAB.unexposed, "hasn't seen it"], [LAB.exposed, 'saw it'],
          [LAB.clicked, 'clicked'], [LAB.converted, 'converted']].map(([c, l]) => (
          <span key={l}><span className="inline-block w-[9px] h-[9px] rounded-full mr-1.5 align-[0px]"
            style={{ background: c }} />{l}</span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Flight path — daily clicks with the p10–p90 band drawn, plus hover readout
// ---------------------------------------------------------------------------
function FlightPath({ daily }: { daily: LabRunResult['daily'] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (daily.length < 2) return null;
  const W = 760; const H = 190; const PAD = { l: 44, r: 10, t: 12, b: 22 };
  const maxY = Math.max(...daily.map((d) => d.clicks.p90 ?? d.clicks.p50 ?? 0), 1);
  const x = (i: number) => PAD.l + (i / (daily.length - 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - v / maxY) * (H - PAD.t - PAD.b);
  const line = daily.map((d, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(d.clicks.p50 ?? 0).toFixed(1)}`).join(' ');
  const band = daily.map((d, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(d.clicks.p90 ?? 0).toFixed(1)}`).join(' ')
    + ' ' + [...daily].reverse().map((d, i) =>
      `L${x(daily.length - 1 - i).toFixed(1)},${y(d.clicks.p10 ?? 0).toFixed(1)}`).join(' ') + ' Z';
  const h = hover != null ? daily[hover] : null;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }} role="img"
        aria-label="Daily clicks with uncertainty band"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = ((e.clientX - rect.left) / rect.width) * W;
          const i = Math.round(((px - PAD.l) / (W - PAD.l - PAD.r)) * (daily.length - 1));
          setHover(Math.max(0, Math.min(daily.length - 1, i)));
        }}>
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(maxY * f)} y2={y(maxY * f)}
              stroke={LAB.line} strokeWidth="1" />
            <text x={PAD.l - 6} y={y(maxY * f) + 3.5} textAnchor="end"
              fontSize="9.5" fill={LAB.faint} fontFamily="ui-monospace, monospace">
              {Math.round(maxY * f).toLocaleString()}
            </text>
          </g>
        ))}
        <path d={band} fill={LAB.clicked} opacity="0.16" />
        <path d={line} fill="none" stroke={LAB.clicked} strokeWidth="2" strokeLinejoin="round" />
        {hover != null && h && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={H - PAD.b}
              stroke={LAB.muted} strokeWidth="1" strokeDasharray="3 3" />
            <circle cx={x(hover)} cy={y(h.clicks.p50 ?? 0)} r="4"
              fill={LAB.clicked} stroke={LAB.bg} strokeWidth="2" />
          </g>
        )}
        <text x={W - PAD.r} y={PAD.t + 8} textAnchor="end" fontSize="10" fill={LAB.muted}>
          clicks / day · band = p10–p90 across runs
        </text>
        {daily.map((d, i) => (i % Math.ceil(daily.length / 7) === 0 || i === daily.length - 1) && (
          <text key={d.day} x={x(i)} y={H - 7} textAnchor="middle" fontSize="9.5"
            fill={LAB.faint} fontFamily="ui-monospace, monospace">d{d.day}</text>
        ))}
      </svg>
      <div className="text-[11.5px] font-mono h-[18px]" style={{ color: LAB.muted }}>
        {h ? <>day {h.day}: {Math.round(h.clicks.p50 ?? 0).toLocaleString()} clicks
          (range {Math.round(h.clicks.p10 ?? 0).toLocaleString()}–{Math.round(h.clicks.p90 ?? 0).toLocaleString()})
          · {Math.round(h.conversions.p50 ?? 0)} conversions</> : ' '}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Forces — the engine's click-logit decomposition, as signed bars
// ---------------------------------------------------------------------------
const FACTOR_LABEL: Record<string, string> = {
  visual: 'Creative strength', persona_match: 'Audience fit',
  psychology: 'Persuasion cues', word_of_mouth: 'Word of mouth',
  fatigue: 'Creative fatigue', plausibility_cap: 'Plausibility guard',
};

function Forces({ factors }: { factors: Record<string, number> }) {
  const rows = Object.entries(factors)
    .filter(([k, v]) => k !== 'base' && Math.abs(v) > 0.0005)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  if (!rows.length) return null;
  const maxAbs = Math.max(...rows.map(([, v]) => Math.abs(v)));
  return (
    <div className="space-y-1.5">
      {rows.map(([k, v]) => (
        <div key={k} className="flex items-center gap-2.5 text-[12px]">
          <span className="w-[128px] shrink-0 text-right" style={{ color: LAB.muted }}>
            {FACTOR_LABEL[k] ?? k.replace(/_/g, ' ')}
          </span>
          <div className="flex-1 relative h-[14px]">
            <div className="absolute inset-y-0 left-1/2 w-px" style={{ background: LAB.line }} />
            <div className="absolute inset-y-[2px] rounded-[3px]" style={{
              background: v >= 0 ? LAB.converted : LAB.clicked,
              left: v >= 0 ? '50%' : `${50 - (Math.abs(v) / maxAbs) * 48}%`,
              width: `${(Math.abs(v) / maxAbs) * 48}%`,
            }} />
          </div>
          <span className="w-[56px] font-mono text-[11px]" style={{ color: LAB.ink }}>
            {v >= 0 ? '+' : ''}{v.toFixed(3)}
          </span>
        </div>
      ))}
      <div className="text-[10.5px] pt-1" style={{ color: LAB.faint }}>
        The simulator&apos;s own decomposition of what pushed click probability up or down (logit units).
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------
export default function LabPage() {
  const profile = useApp((s) => s.companyProfile);
  const campaigns = useApp((s) => s.savedCampaigns);
  const currentCompanyId = useApp((s) => s.currentCompanyId);
  const cur = profile?.currency || 'GBP';

  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [cal, setCal] = useState<AccountCalibration | null>(null);
  const [ready, setReady] = useState(false);

  // Controls.
  const [objective, setObjective] = useState<'awareness' | 'consideration' | 'conversion'>('conversion');
  const [platformId, setPlatformId] = useState('meta_instagram');
  const [formatId, setFormatId] = useState('meta_ig_reels');
  const [segment, setSegment] = useState('all');
  const [budget, setBudget] = useState(5000);
  const [days, setDays] = useState(14);
  const [quality, setQuality] = useState(55);
  const [fatigue, setFatigue] = useState(10);       // % per exposure
  const [aov, setAov] = useState<number | ''>('');

  const [result, setResult] = useState<LabRunResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // ---- Personalised defaults, each traceable --------------------------------
  const [defaultsNote, setDefaultsNote] = useState<Record<string, Provenance>>({});
  useEffect(() => {
    let alive = true;
    Promise.all([
      api.platforms().catch(() => ({ platforms: [] as Platform[] })),
      getLatestCalibration(currentCompanyId ?? undefined).catch(() => null),
    ]).then(([p, c]) => {
      if (!alive) return;
      setPlatforms(p.platforms);
      setCal(c);
      const notes: Record<string, Provenance> = {};
      if (profile?.conversion_goal === 'awareness') setObjective('awareness');
      if (profile?.avg_order_value) { setAov(profile.avg_order_value); notes.aov = 'your data'; }
      else notes.aov = 'assumption';
      const budgets = campaigns.map((cc) => cc.budget).filter((b): b is number => typeof b === 'number' && b > 0)
        .sort((a, b) => a - b);
      if (budgets.length >= 3) { setBudget(Math.round(budgets[Math.floor(budgets.length / 2)])); notes.budget = 'your data'; }
      else notes.budget = 'assumption';
      const fat = c?.auction?.fatigue;
      if (fat?.usable && fat.lambda_per_exposure != null) {
        setFatigue(Math.round(fat.lambda_per_exposure * 100)); notes.fatigue = 'your data';
      } else notes.fatigue = 'assumption';
      notes.market = c?.usable ? 'your data' : 'industry';
      setDefaultsNote(notes);
      setReady(true);
    });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentCompanyId]);

  const platform = platforms.find((p) => p.id === platformId);
  const format = platform?.formats.find((f) => f.id === formatId) ?? platform?.formats[0];

  // The same personalised anchor path the wizard uses (shrinkage + seasonality).
  const anchor = useMemo(() => {
    if (!cal || !format) return null;
    const interests = interestsFromText(
      [profile?.product_category, profile?.industry, profile?.value_proposition].join(' '));
    const pick = pickCalibrationAnchor(
      cal, segment === 'all' ? null : segment, interests,
      calibrationPlatformKey(platformId),
      { ctr: format.benchmarks.ctr, cpm: format.benchmarks.cpm });
    let cpm = pick.cpm;
    const season = cal.auction?.cpm_seasonality;
    if (cpm != null && season?.usable) {
      const f = season.factors[String(new Date().getMonth() + 1)];
      if (f && f > 0) cpm = cpm * f;
    }
    return { ...pick, cpm };
  }, [cal, format, segment, platformId, profile]);

  // ---- Debounced auto-run ----------------------------------------------------
  const run = useCallback(() => {
    if (!format) return;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setRunning(true); setError(null);
    api.labRun({
      platform_id: platformId, format_id: format.id, objective,
      budget, days, daily_reach: 0.35, n_runs: 6, segment,
      creative_quality: quality / 100,
      target_ctr: anchor?.ctr ?? null,
      cpm_override: anchor?.cpm ?? null,
      target_conversion_rate: anchor?.cvr ?? null,
      aov: aov === '' ? null : Number(aov),
      fatigue_per_exposure: fatigue / 100,
      reachable_audience: null,
    }).then((r) => { if (!ac.signal.aborted) { setResult(r); setRunning(false); } })
      .catch((e) => {
        if (ac.signal.aborted) return;
        setError((e as Error).message); setRunning(false);
      });
  }, [format, platformId, objective, budget, days, segment, quality, fatigue, aov, anchor]);

  useEffect(() => {
    if (!ready || !format) return;
    const t = setTimeout(run, 700);
    return () => clearTimeout(t);
  }, [ready, run, format]);

  // ---- Goal-aware hero metrics ------------------------------------------------
  const heroes = useMemo(() => {
    if (!result) return [];
    const k = result.kpis;
    const money = (v: number) => `${cur} ${Math.round(v).toLocaleString()}`;
    const freq = k.reach_agents > 0 && k.impressions > 0
      ? k.impressions / Math.max(k.reach_agents, 1) : null;
    if (objective === 'awareness') {
      return [
        { label: 'Impressions', v: k.impressions.toLocaleString(), sub: `at ${cur} ${k.cpm?.toFixed(2)} CPM` },
        { label: 'CPM', v: k.cpm != null ? `${cur} ${k.cpm.toFixed(2)}` : '—', sub: 'cost per 1k views' },
        { label: 'Est. frequency', v: freq ? `${Math.min(freq / 40, 9.9).toFixed(1)}×` : '—', sub: 'views per person' },
      ];
    }
    if (objective === 'consideration') {
      return [
        { label: 'Clicks', v: Math.round(k.clicks.p50).toLocaleString(), sub: `range ${Math.round(k.clicks.p10).toLocaleString()}–${Math.round(k.clicks.p90).toLocaleString()}` },
        { label: 'CTR', v: `${(k.ctr * 100).toFixed(2)}%`, sub: 'simulated audience' },
        { label: 'Cost / click', v: money(k.spend / Math.max(k.clicks.p50, 1)), sub: 'at p50 clicks' },
      ];
    }
    return [
      { label: 'Conversions', v: Math.round(k.conversions.p50).toLocaleString(), sub: `range ${Math.round(k.conversions.p10)}–${Math.round(k.conversions.p90)}` },
      { label: 'Cost / conversion', v: k.conversions.p50 > 0 ? money(k.spend / k.conversions.p50) : '—', sub: 'at p50' },
      { label: 'ROAS', v: `${k.roas.p50.toFixed(2)}×`, sub: `band ${k.roas.p10.toFixed(2)}–${k.roas.p90.toFixed(2)}×` },
    ];
  }, [result, objective, cur]);

  const ctl = 'block text-[10px] font-bold uppercase tracking-[0.09em] mb-1.5';

  return (
    <div className="max-w-6xl">
      <div className="flex items-end gap-4 flex-wrap mb-1">
        <h1 className="display-italic text-[34px]">The <span className="gradient-text">simulation lab</span></h1>
        <Pill tone="violet">runs the real forecasting engine</Pill>
      </div>
      <p className="text-ink-muted text-[14.5px] mb-5 max-w-2xl">
        Move a factor — watch {result?.meta.audience_personas ?? 600} simulated consumers re-live the
        campaign. Same engine as every forecast, without spending a cent. Score a real creative in{' '}
        <Link href="/new" className="text-violet underline font-semibold">New analysis</Link> when you&apos;re ready.
      </p>

      {/* THE INSTRUMENT PANEL — the one dark surface in AdProof */}
      <div className="rounded-xl p-5 sm:p-6" style={{ background: LAB.bg, color: LAB.ink }}>
        <div className="grid grid-cols-1 lg:grid-cols-[250px_1fr] gap-6">
          {/* CONTROL RAIL */}
          <div className="space-y-4">
            <div>
              <span className={ctl} style={{ color: LAB.faint }}>Goal</span>
              <div className="flex rounded-lg p-1 gap-1" style={{ background: LAB.panel }}>
                {(['awareness', 'consideration', 'conversion'] as const).map((o) => (
                  <button key={o} type="button" onClick={() => setObjective(o)}
                    className="flex-1 px-1 py-1.5 rounded-md text-[10.5px] font-bold capitalize"
                    style={objective === o
                      ? { background: LAB.clicked, color: '#fff' }
                      : { color: LAB.muted }}>
                    {o === 'consideration' ? 'clicks' : o}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <span className={ctl} style={{ color: LAB.faint }}>Platform · format</span>
              <select value={platformId}
                onChange={(e) => {
                  setPlatformId(e.target.value);
                  const p = platforms.find((x) => x.id === e.target.value);
                  if (p?.formats[0]) setFormatId(p.formats[0].id);
                }}
                className="w-full rounded-md px-2.5 py-2 text-[12.5px] mb-1.5 border-0"
                style={{ background: LAB.panel, color: LAB.ink }}>
                {platforms.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <select value={format?.id ?? ''} onChange={(e) => setFormatId(e.target.value)}
                className="w-full rounded-md px-2.5 py-2 text-[12.5px] border-0"
                style={{ background: LAB.panel, color: LAB.ink }}>
                {platform?.formats.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </div>
            <div>
              <span className={ctl} style={{ color: LAB.faint }}>Audience</span>
              <select value={segment} onChange={(e) => setSegment(e.target.value)}
                className="w-full rounded-md px-2.5 py-2 text-[12.5px] border-0"
                style={{ background: LAB.panel, color: LAB.ink }}>
                {SEGMENTS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
              </select>
            </div>
            <div>
              <span className={ctl} style={{ color: LAB.faint }}>
                Budget · {defaultsNote.budget === 'your data' ? 'from your history' : 'edit me'}
              </span>
              <input type="range" min={500} max={50000} step={250} value={budget}
                onChange={(e) => setBudget(Number(e.target.value))}
                className="w-full" style={{ accentColor: LAB.clicked }} />
              <span className="font-mono text-[13px]">{cur} {budget.toLocaleString()}</span>
            </div>
            <div>
              <span className={ctl} style={{ color: LAB.faint }}>Flight length</span>
              <input type="range" min={3} max={30} value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                className="w-full" style={{ accentColor: LAB.clicked }} />
              <span className="font-mono text-[13px]">{days} days</span>
            </div>
            <div>
              <span className={ctl} style={{ color: LAB.faint }}>Creative quality · hypothetical</span>
              <input type="range" min={10} max={95} value={quality}
                onChange={(e) => setQuality(Number(e.target.value))}
                className="w-full" style={{ accentColor: LAB.clicked }} />
              <span className="font-mono text-[13px]">{quality} / 100</span>
            </div>
            <div>
              <span className={ctl} style={{ color: LAB.faint }}>
                Fatigue · {defaultsNote.fatigue === 'your data' ? 'fitted from your ads' : 'default'}
              </span>
              <input type="range" min={0} max={30} value={fatigue}
                onChange={(e) => setFatigue(Number(e.target.value))}
                className="w-full" style={{ accentColor: LAB.clicked }} />
              <span className="font-mono text-[13px]">−{fatigue}% per repeat view</span>
            </div>
            <div>
              <span className={ctl} style={{ color: LAB.faint }}>Order value</span>
              <input type="number" min={0} value={aov}
                onChange={(e) => setAov(e.target.value === '' ? '' : Number(e.target.value))}
                placeholder="e.g. 65"
                className="w-full rounded-md px-2.5 py-2 text-[13px] font-mono border-0"
                style={{ background: LAB.panel, color: LAB.ink }} />
            </div>
            <div className="pt-1 flex flex-wrap gap-1.5 text-[10px]" style={{ color: LAB.faint }}>
              <span>market anchor:</span><ProvChip p={defaultsNote.market ?? 'industry'} />
              <span>· AOV:</span><ProvChip p={defaultsNote.aov ?? 'assumption'} />
            </div>
          </div>

          {/* THE STAGE */}
          <div className="min-w-0">
            {/* Hero metrics */}
            <div className="grid grid-cols-3 gap-3 mb-4">
              {(heroes.length ? heroes : [1, 2, 3].map(() => null)).map((m, i) => (
                <div key={i} className="rounded-lg px-4 py-3"
                  style={{ background: LAB.panel, opacity: running ? 0.55 : 1, transition: 'opacity 200ms' }}>
                  {m ? (
                    <>
                      <div className="text-[9.5px] font-bold uppercase tracking-[0.1em]" style={{ color: LAB.faint }}>{m.label}</div>
                      <div className="font-mono font-bold text-[22px] leading-tight mt-0.5">{m.v}</div>
                      <div className="text-[10.5px]" style={{ color: LAB.muted }}>{m.sub}</div>
                    </>
                  ) : <div className="h-[52px] text-[11px] flex items-center" style={{ color: LAB.faint }}>simulating…</div>}
                </div>
              ))}
            </div>

            {error && (
              <div className="rounded-lg px-4 py-3 mb-4 text-[12.5px]"
                style={{ background: '#3A1F17', color: '#F0A088' }}>
                {error}
              </div>
            )}

            {result && (
              <>
                <div className="rounded-lg p-4 mb-4" style={{ background: LAB.panel }}>
                  <div className="flex items-baseline justify-between flex-wrap gap-2 mb-2.5">
                    <span className="text-[10.5px] font-bold uppercase tracking-[0.1em]" style={{ color: LAB.faint }}>
                      The population — {result.timeline.agents} simulated consumers
                    </span>
                    {running && <span className="text-[10.5px]" style={{ color: LAB.clicked }}>re-simulating…</span>}
                  </div>
                  <PopulationField frames={result.timeline.frames} agents={result.timeline.agents} />
                </div>

                <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-4">
                  <div className="rounded-lg p-4" style={{ background: LAB.panel }}>
                    <span className="text-[10.5px] font-bold uppercase tracking-[0.1em] block mb-2" style={{ color: LAB.faint }}>
                      The flight path
                    </span>
                    <FlightPath daily={result.daily} />
                  </div>
                  <div className="rounded-lg p-4" style={{ background: LAB.panel }}>
                    <span className="text-[10.5px] font-bold uppercase tracking-[0.1em] block mb-2.5" style={{ color: LAB.faint }}>
                      The forces on this scenario
                    </span>
                    <Forces factors={result.factors} />
                  </div>
                </div>

                <div className="flex flex-wrap gap-x-4 gap-y-1 mt-4 text-[10.5px]" style={{ color: LAB.faint }}>
                  <span>{result.meta.n_runs} Monte-Carlo runs · {result.meta.sim_days} days · {result.meta.audience_personas} personas</span>
                  <span>creative: {result.meta.creative}</span>
                  <span>fatigue: {result.meta.fatigue_source}</span>
                  <span>bands show run-to-run spread, not full real-world uncertainty</span>
                </div>
              </>
            )}
            {!result && !error && (
              <div className="rounded-lg p-10 text-center text-[13px]" style={{ background: LAB.panel, color: LAB.muted }}>
                Warming up the simulator…
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
