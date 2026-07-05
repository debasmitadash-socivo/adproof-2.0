'use client';
// The Simulation Lab v2 — "Mission Control + The Street".
//
// Watch the agent-based model run: a population field of simulated consumers
// re-living the campaign, a narrated event ticker (every line traces to a
// simulated number), a scenario tray with ghost overlays, and — the point —
// an audience that is YOURS: the population is reshaped to match the real
// age × gender delivery mix pulled from your ad account.
//
// State palette CVD-validated (blue → coral → green ladder, worst pair
// ΔE 15.6 on the dark surface) with dot size as secondary encoding.
// Every number carries provenance; the creative slider is labelled
// hypothetical; bands are drawn, not footnoted.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Pill } from '@/components/ui/Pill';
import { api } from '@/lib/api';
import { getLatestCalibration, listBreakdowns } from '@/lib/db';
import { useApp } from '@/lib/store';
import {
  calibrationPlatformKey, interestsFromText, pickCalibrationAnchor,
} from '@/lib/anchor';
import type {
  AccountCalibration, LabEvent, LabRunResult, Platform,
} from '@/lib/types';

const LAB = {
  bg: '#14181D', panel: '#1B2127', panelUp: '#20272E', line: '#2A333B',
  ink: '#E9EDF1', muted: '#93A0AB', faint: '#5E6B76',
  unexposed: '#3A444D', exposed: '#3E86C4', clicked: '#E06B3F', converted: '#4EA06B',
  wom: '#A78BE8', warn: '#E3B65C',
};
const GHOST_COLORS = ['#6FA8DC', '#A78BE8'];

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

type MixCell = { age: string; gender: string; share: number };

// ---------------------------------------------------------------------------
// The Living Market — the audience as demographic districts (squarified
// treemap). District area = how much of the simulated population that
// age × gender cell holds; heat = the fraction of that district the
// campaign has actually reached BY THE CURRENT DAY of playback. Clicks and
// purchases per district come straight from the per-agent frames, so a
// district that genuinely responds better in the sim visibly runs hotter.
// ---------------------------------------------------------------------------
type Rect = { x: number; y: number; w: number; h: number };

function squarify(values: number[], W: number, H: number): Rect[] {
  // Classic squarified treemap; expects values sorted descending.
  const total = values.reduce((a, b) => a + b, 0) || 1;
  const scaled = values.map((v) => (v / total) * W * H);
  const out: Rect[] = new Array(values.length);
  let x = 0, y = 0, w = W, h = H, i = 0;
  const worst = (row: number[], side: number) => {
    const s = row.reduce((a, b) => a + b, 0);
    const mx = Math.max(...row), mn = Math.min(...row);
    return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn));
  };
  while (i < scaled.length) {
    const side = Math.min(w, h);
    let row = [scaled[i]]; let j = i + 1; let best = worst(row, side);
    while (j < scaled.length) {
      const cand = [...row, scaled[j]];
      const wr = worst(cand, side);
      if (wr > best) break;
      row = cand; best = wr; j++;
    }
    const sum = row.reduce((a, b) => a + b, 0);
    const thick = sum / side;
    if (w >= h) {
      let yy = y;
      row.forEach((v, k) => { const hh = v / thick; out[i + k] = { x, y: yy, w: thick, h: hh }; yy += hh; });
      x += thick; w -= thick;
    } else {
      let xx = x;
      row.forEach((v, k) => { const ww = v / thick; out[i + k] = { x: xx, y, w: ww, h: thick }; xx += ww; });
      y += thick; h -= thick;
    }
    i = j;
  }
  return out;
}

function cellTitle(cell: string): string {
  const [age, gender] = cell.split('|');
  const g = gender === 'male' ? 'Men' : gender === 'female' ? 'Women' : 'People';
  return `${g} ${age === '?' ? '' : age}`.trim();
}

function MarketMap({ frames, cells, day }: {
  frames: string[]; cells: string[]; day: number;
}) {
  // Group agent indices by district once per result.
  const districts = useMemo(() => {
    const by = new Map<string, number[]>();
    cells.forEach((c, i) => { (by.get(c) ?? by.set(c, []).get(c)!).push(i); });
    return [...by.entries()]
      .map(([cell, idx]) => ({ cell, idx }))
      .sort((a, b) => b.idx.length - a.idx.length);
  }, [cells]);

  const W = 760; const H = 330; const GAP = 3;
  const rects = useMemo(
    () => squarify(districts.map((d) => d.idx.length), W, H), [districts]);

  const frame = frames[Math.min(day, frames.length - 1)] ?? '';
  return (
    <div className="relative" style={{ width: '100%', aspectRatio: `${W}/${H}`, borderRadius: 10, background: LAB.bg, overflow: 'hidden' }}
      role="img" aria-label={`Market districts by age and gender, day ${day + 1}`}>
      {districts.map((d, i) => {
        const r = rects[i];
        let reached = 0, clicked = 0, bought = 0;
        for (const a of d.idx) {
          const s = frame.charCodeAt(a) - 48;
          if (s >= 1) reached++;
          if (s >= 2) clicked++;
          if (s === 3) bought++;
        }
        const frac = d.idx.length ? reached / d.idx.length : 0;
        const pw = (r.w / W) * 100, ph = (r.h / H) * 100;
        const big = r.w > 130 && r.h > 72;
        return (
          <div key={d.cell} className="absolute transition-all duration-500"
            style={{
              left: `${(r.x / W) * 100}%`, top: `${(r.y / H) * 100}%`,
              width: `calc(${pw}% - ${GAP}px)`, height: `calc(${ph}% - ${GAP}px)`,
              margin: GAP / 2, borderRadius: 8,
              background: `linear-gradient(150deg, rgba(62,134,196,${(0.08 + frac * 0.42).toFixed(3)}), rgba(62,134,196,${(frac * 0.22).toFixed(3)}))`,
              border: `1px solid ${frac > 0.02 ? 'rgba(62,134,196,0.45)' : LAB.line}`,
              boxShadow: bought > 0 ? `inset 0 0 ${Math.min(10 + bought * 3, 34)}px rgba(78,160,107,0.30)` : 'none',
              padding: big ? '9px 11px' : '5px 7px', overflow: 'hidden',
            }}>
            <div className="font-bold leading-tight" style={{ color: LAB.ink, fontSize: big ? 12.5 : 10 }}>
              {cellTitle(d.cell)}
            </div>
            <div className="font-mono" style={{ color: LAB.muted, fontSize: big ? 10.5 : 9 }}>
              {((d.idx.length / cells.length) * 100).toFixed(0)}% of audience
            </div>
            <div className="font-mono mt-1" style={{ color: frac > 0 ? LAB.exposed : LAB.faint, fontSize: big ? 11 : 9 }}>
              {(frac * 100).toFixed(0)}% reached
            </div>
            {big && (clicked > 0 || bought > 0) && (
              <div className="font-mono" style={{ fontSize: 10.5 }}>
                {clicked > 0 && <span style={{ color: LAB.clicked }}>{clicked} clicked</span>}
                {clicked > 0 && bought > 0 && <span style={{ color: LAB.faint }}> · </span>}
                {bought > 0 && <span style={{ color: LAB.converted }}>{bought} bought</span>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Population field — the hero
// ---------------------------------------------------------------------------
function PopulationField({ frames, agents, cells, onDay }: {
  frames: string[]; agents: number; cells?: string[]; onDay?: (d: number) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [day, setDay] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [view, setView] = useState<'people' | 'market'>('people');
  const hasMap = !!cells && cells.length > 0;
  const reduced = typeof window !== 'undefined'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  useEffect(() => { setDay(0); setPlaying(!reduced); }, [frames, reduced]);
  useEffect(() => { onDay?.(day); }, [day, onDay]);

  useEffect(() => {
    if (!playing || frames.length === 0) return;
    const t = setInterval(() => setDay((d) => (d + 1) % frames.length), 620);
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
      const s = frame.charCodeAt(i) - 48;
      const x = (i % cols + 0.5) * cw;
      const y = (Math.floor(i / cols) + 0.5) * ch;
      // Converted agents get a soft glow — the "magic" is earned, not decor.
      if (s === 3) {
        ctx.beginPath();
        ctx.arc(x, y, r * 2.4, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(78,160,107,0.18)';
        ctx.fill();
      }
      ctx.beginPath();
      ctx.arc(x, y, s === 3 ? r * 1.5 : s === 2 ? r * 1.25 : r, 0, Math.PI * 2);
      ctx.fillStyle = s === 3 ? LAB.converted : s === 2 ? LAB.clicked
        : s === 1 ? LAB.exposed : LAB.unexposed;
      ctx.fill();
    }
  }, [day, frames, agents, view]);   // view: canvas remounts when toggling back

  if (frames.length === 0) return null;
  return (
    <div>
      {hasMap && (
        <div className="flex items-center gap-1 mb-2.5 rounded-lg p-1 w-fit" style={{ background: LAB.panelUp }}>
          {([['people', '◦◦ People'], ['market', '▦ Living market']] as const).map(([v, label]) => (
            <button key={v} type="button" onClick={() => setView(v)}
              className="px-3 py-1 rounded-md text-[11px] font-bold transition-colors"
              style={view === v
                ? { background: 'linear-gradient(120deg,#FF5E1A,#E8366B)', color: '#fff' }
                : { color: LAB.muted }}>
              {label}
            </button>
          ))}
          {view === 'market' && (
            <span className="text-[10px] pl-2 pr-1" style={{ color: LAB.faint }}>
              districts sized by audience share · heat = reach on this day
            </span>
          )}
        </div>
      )}
      {view === 'market' && hasMap ? (
        <MarketMap frames={frames} cells={cells!} day={day} />
      ) : (
        <canvas ref={canvasRef} width={760} height={330}
          style={{ width: '100%', height: 'auto', borderRadius: 10, background: LAB.bg }}
          aria-label={`Simulated audience of ${agents} people, day ${day + 1} of ${frames.length}`} />
      )}
      <div className="flex items-center gap-3 mt-2.5 flex-wrap">
        <button type="button" onClick={() => setPlaying((p) => !p)}
          className="px-3.5 py-1.5 rounded-md text-[12px] font-bold transition-transform active:scale-95"
          style={{ background: 'linear-gradient(120deg,#FF5E1A,#E8366B)', color: '#fff', boxShadow: '0 4px 14px rgba(232,80,15,0.35)' }}>
          {playing ? '⏸ Pause' : '▶ Play'}
        </button>
        <input type="range" min={0} max={frames.length - 1} value={day}
          onChange={(e) => { setPlaying(false); setDay(Number(e.target.value)); }}
          className="flex-1 min-w-[120px]" style={{ accentColor: LAB.clicked }}
          aria-label="Campaign day" />
        <span className="text-[12px] font-mono" style={{ color: LAB.muted }}>day {day + 1}/{frames.length}</span>
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
// Flight path with ghost overlays (pinned scenarios)
// ---------------------------------------------------------------------------
type Ghost = { label: string; color: string; p50: number[] };

function FlightPath({ daily, ghosts }: { daily: LabRunResult['daily']; ghosts: Ghost[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (daily.length < 2) return null;
  const W = 760; const H = 190; const PAD = { l: 44, r: 10, t: 12, b: 22 };
  const maxY = Math.max(
    ...daily.map((d) => d.clicks.p90 ?? d.clicks.p50 ?? 0),
    ...ghosts.flatMap((g) => g.p50), 1);
  const x = (i: number, n = daily.length) => PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - v / maxY) * (H - PAD.t - PAD.b);
  const line = daily.map((d, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(d.clicks.p50 ?? 0).toFixed(1)}`).join(' ');
  const band = daily.map((d, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(d.clicks.p90 ?? 0).toFixed(1)}`).join(' ')
    + ' ' + [...daily].reverse().map((d, i) =>
      `L${x(daily.length - 1 - i).toFixed(1)},${y(d.clicks.p10 ?? 0).toFixed(1)}`).join(' ') + ' Z';
  const h = hover != null ? daily[hover] : null;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }} role="img"
        aria-label="Daily clicks with uncertainty band and pinned-scenario overlays"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = ((e.clientX - rect.left) / rect.width) * W;
          const i = Math.round(((px - PAD.l) / (W - PAD.l - PAD.r)) * (daily.length - 1));
          setHover(Math.max(0, Math.min(daily.length - 1, i)));
        }}>
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(maxY * f)} y2={y(maxY * f)} stroke={LAB.line} strokeWidth="1" />
            <text x={PAD.l - 6} y={y(maxY * f) + 3.5} textAnchor="end" fontSize="9.5"
              fill={LAB.faint} fontFamily="ui-monospace, monospace">{Math.round(maxY * f).toLocaleString()}</text>
          </g>
        ))}
        <path d={band} fill={LAB.clicked} opacity="0.16" />
        {ghosts.map((g) => (
          <path key={g.label} fill="none" stroke={g.color} strokeWidth="1.5" strokeDasharray="5 4" opacity="0.85"
            d={g.p50.map((v, i) => `${i ? 'L' : 'M'}${x(i, g.p50.length).toFixed(1)},${y(v).toFixed(1)}`).join(' ')} />
        ))}
        <path d={line} fill="none" stroke={LAB.clicked} strokeWidth="2.2" strokeLinejoin="round" />
        {hover != null && h && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={H - PAD.b}
              stroke={LAB.muted} strokeWidth="1" strokeDasharray="3 3" />
            <circle cx={x(hover)} cy={y(h.clicks.p50 ?? 0)} r="4" fill={LAB.clicked} stroke={LAB.bg} strokeWidth="2" />
          </g>
        )}
        <text x={W - PAD.r} y={PAD.t + 8} textAnchor="end" fontSize="10" fill={LAB.muted}>
          clicks / day · ribbon = p10–p90 · dashed = pinned scenarios
        </text>
        {daily.map((d, i) => (i % Math.ceil(daily.length / 7) === 0 || i === daily.length - 1) && (
          <text key={d.day} x={x(i)} y={H - 7} textAnchor="middle" fontSize="9.5"
            fill={LAB.faint} fontFamily="ui-monospace, monospace">d{d.day}</text>
        ))}
      </svg>
      <div className="text-[11.5px] font-mono h-[18px]" style={{ color: LAB.muted }}>
        {h ? <>day {h.day}: {Math.round(h.clicks.p50 ?? 0).toLocaleString()} clicks
          ({Math.round(h.clicks.p10 ?? 0).toLocaleString()}–{Math.round(h.clicks.p90 ?? 0).toLocaleString()})
          · {Math.round(h.conversions.p50 ?? 0)} conversions</> : ' '}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The Street — narrated event ticker (every line traces to a sim number)
// ---------------------------------------------------------------------------
const EV_COLOR: Record<LabEvent['kind'], string> = {
  reach: LAB.muted, click: LAB.clicked, convert: LAB.converted,
  wom: LAB.wom, fatigue: LAB.warn, summary: LAB.ink,
};
const EV_ICON: Record<LabEvent['kind'], string> = {
  reach: '◉', click: '↗', convert: '✓', wom: '⇄', fatigue: '▽', summary: '∎',
};

function EventTicker({ events, currentDay }: { events: LabEvent[]; currentDay: number }) {
  if (!events.length) return null;
  return (
    <div className="space-y-0">
      {events.map((e, i) => {
        const live = e.day <= currentDay + 1;
        return (
          <div key={i} className="flex gap-2.5 items-baseline py-[7px] transition-opacity duration-500"
            style={{ opacity: live ? 1 : 0.28, borderBottom: `1px solid ${LAB.line}` }}>
            <span className="font-mono text-[10.5px] w-[26px] shrink-0" style={{ color: LAB.faint }}>d{e.day}</span>
            <span style={{ color: EV_COLOR[e.kind] }} className="text-[11px] shrink-0">{EV_ICON[e.kind]}</span>
            <span className="text-[12px] leading-snug" style={{ color: e.kind === 'summary' ? LAB.ink : LAB.muted }}>
              {e.text}
            </span>
          </div>
        );
      })}
      <div className="text-[10px] pt-2" style={{ color: LAB.faint }}>
        Narrated from one representative run — every line is a simulated number, not a script.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Forces panel
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
          <span className="w-[118px] shrink-0 text-right" style={{ color: LAB.muted }}>
            {FACTOR_LABEL[k] ?? k.replace(/_/g, ' ')}
          </span>
          <div className="flex-1 relative h-[13px]">
            <div className="absolute inset-y-0 left-1/2 w-px" style={{ background: LAB.line }} />
            <div className="absolute inset-y-[2px] rounded-[3px] transition-all duration-300" style={{
              background: v >= 0 ? LAB.converted : LAB.clicked,
              left: v >= 0 ? '50%' : `${50 - (Math.abs(v) / maxAbs) * 48}%`,
              width: `${(Math.abs(v) / maxAbs) * 48}%`,
            }} />
          </div>
          <span className="w-[52px] font-mono text-[10.5px]" style={{ color: LAB.ink }}>
            {v >= 0 ? '+' : ''}{v.toFixed(3)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------
type Pinned = {
  id: number; label: string; color: string;
  kpis: LabRunResult['kpis']; p50: number[];
};

export default function LabPage() {
  const router = useRouter();
  const profile = useApp((s) => s.companyProfile);
  const campaigns = useApp((s) => s.savedCampaigns);
  const savedAudiences = useApp((s) => s.savedAudiences);
  const currentCompanyId = useApp((s) => s.currentCompanyId);
  const setPlatform = useApp((s) => s.setPlatform);
  const setFormat = useApp((s) => s.setFormat);
  const setStoreBudget = useApp((s) => s.setBudget);
  const setStoreDays = useApp((s) => s.setDays);
  const setStoreObjective = useApp((s) => s.setObjective);
  const cur = profile?.currency || 'GBP';
  const companyName = profile?.company_name || 'your company';

  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [cal, setCal] = useState<AccountCalibration | null>(null);
  const [yourMix, setYourMix] = useState<MixCell[] | null>(null);
  const [ready, setReady] = useState(false);

  // Controls.
  const [objective, setObjective] = useState<'awareness' | 'consideration' | 'conversion'>('conversion');
  const [platformId, setPlatformId] = useState('meta_instagram');
  const [formatId, setFormatId] = useState('meta_ig_reels');
  const [audiencePick, setAudiencePick] = useState('seg:all');   // 'yours' | 'aud:<id>' | 'seg:<id>'
  const [budget, setBudget] = useState(5000);
  const [days, setDays] = useState(14);
  const [quality, setQuality] = useState(55);
  const [fatigue, setFatigue] = useState(10);
  const [aov, setAov] = useState<number | ''>('');

  const [result, setResult] = useState<LabRunResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldDay, setFieldDay] = useState(0);
  const [pinned, setPinned] = useState<Pinned[]>([]);
  const pinSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const [defaultsNote, setDefaultsNote] = useState<Record<string, Provenance>>({});

  // ---- Personalised bootstrap ------------------------------------------------
  useEffect(() => {
    let alive = true;
    Promise.all([
      api.platforms().catch(() => ({ platforms: [] as Platform[] })),
      getLatestCalibration(currentCompanyId ?? undefined).catch(() => null),
      listBreakdowns(currentCompanyId ?? undefined).catch(() => []),
    ]).then(([p, c, bds]) => {
      if (!alive) return;
      setPlatforms(p.platforms);
      setCal(c);
      // YOUR BUYERS: real age × gender delivery shares from the breakdowns.
      const cells = new Map<string, { age: string; gender: string; imp: number }>();
      let totalImp = 0;
      for (const b of bds) {
        if (b.age === 'unknown' && b.gender === 'unknown') continue;
        const k = `${b.age}::${b.gender}`;
        const cell = cells.get(k) ?? { age: b.age, gender: b.gender, imp: 0 };
        cell.imp += b.impressions; totalImp += b.impressions;
        cells.set(k, cell);
      }
      const mix = totalImp > 0
        ? [...cells.values()]
          .map((cc) => ({ age: cc.age, gender: cc.gender, share: cc.imp / totalImp }))
          .sort((a, b) => b.share - a.share).slice(0, 10)
        : null;
      setYourMix(mix);
      if (mix) setAudiencePick('yours');

      const notes: Record<string, Provenance> = {};
      notes.audience = mix ? 'your data' : 'assumption';
      if (profile?.conversion_goal === 'awareness') setObjective('awareness');
      if (profile?.avg_order_value) { setAov(profile.avg_order_value); notes.aov = 'your data'; }
      else notes.aov = 'assumption';
      const budgets = campaigns.map((cc) => cc.budget)
        .filter((b): b is number => typeof b === 'number' && b > 0).sort((a, b) => a - b);
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

  // Resolve the audience pick → segment + optional mix.
  const audience = useMemo(() => {
    if (audiencePick === 'yours' && yourMix) {
      return { segment: 'all', mix: yourMix, label: `${companyName}'s buyers` };
    }
    if (audiencePick.startsWith('aud:')) {
      const a = savedAudiences.find((x) => x.id === audiencePick.slice(4));
      if (a) return { segment: a.segment || 'all', mix: null, label: a.name };
    }
    const segId = audiencePick.replace(/^seg:/, '');
    const seg = SEGMENTS.find(([id]) => id === segId);
    return { segment: segId, mix: null, label: seg?.[1] ?? 'Everyone' };
  }, [audiencePick, yourMix, savedAudiences, companyName]);

  const anchor = useMemo(() => {
    if (!cal || !format) return null;
    const interests = interestsFromText(
      [profile?.product_category, profile?.industry, profile?.value_proposition].join(' '));
    const pick = pickCalibrationAnchor(
      cal, audience.segment === 'all' ? null : audience.segment, interests,
      calibrationPlatformKey(platformId),
      { ctr: format.benchmarks.ctr, cpm: format.benchmarks.cpm });
    let cpm = pick.cpm;
    const season = cal.auction?.cpm_seasonality;
    if (cpm != null && season?.usable) {
      const f = season.factors[String(new Date().getMonth() + 1)];
      if (f && f > 0) cpm = cpm * f;
    }
    return { ...pick, cpm };
  }, [cal, format, audience.segment, platformId, profile]);

  // ---- Debounced auto-run ------------------------------------------------------
  const run = useCallback(() => {
    if (!format) return;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setRunning(true); setError(null);
    api.labRun({
      platform_id: platformId, format_id: format.id, objective,
      budget, days, daily_reach: 0.35, n_runs: 6, segment: audience.segment,
      creative_quality: quality / 100,
      target_ctr: anchor?.ctr ?? null,
      cpm_override: anchor?.cpm ?? null,
      target_conversion_rate: anchor?.cvr ?? null,
      aov: aov === '' ? null : Number(aov),
      fatigue_per_exposure: fatigue / 100,
      reachable_audience: null,
      audience_mix: audience.mix, currency: cur,
    }).then((r) => { if (!ac.signal.aborted) { setResult(r); setRunning(false); } })
      .catch((e) => {
        if (ac.signal.aborted) return;
        setError((e as Error).message); setRunning(false);
      });
  }, [format, platformId, objective, budget, days, audience, quality, fatigue, aov, anchor, cur]);

  useEffect(() => {
    if (!ready || !format) return;
    const t = setTimeout(run, 700);
    return () => clearTimeout(t);
  }, [ready, run, format]);

  // ---- Scenario tray -----------------------------------------------------------
  function pinCurrent() {
    if (!result || pinned.length >= 2) return;
    pinSeq.current += 1;
    setPinned((cur0) => [...cur0, {
      id: pinSeq.current,
      label: `${cur} ${(budget / 1000).toFixed(budget >= 10000 ? 0 : 1)}k · ${days}d · q${quality} · ${audience.label.slice(0, 14)}`,
      color: GHOST_COLORS[cur0.length % GHOST_COLORS.length],
      kpis: result.kpis,
      p50: result.daily.map((d) => d.clicks.p50 ?? 0),
    }]);
  }
  const baseline = pinned[0] ?? null;
  const delta = (now: number, was: number | undefined, invert = false) => {
    if (was == null || was === 0) return null;
    const d = now - was;
    const good = invert ? d < 0 : d > 0;
    return { text: `${d > 0 ? '+' : ''}${Math.abs(d) >= 100 ? Math.round(d).toLocaleString() : d.toFixed(Math.abs(d) < 3 ? 2 : 0)}`, good };
  };

  function runForReal() {
    setStoreObjective(objective);
    setPlatform(platformId);
    if (format) setFormat(format.id);
    setStoreBudget(budget);
    setStoreDays(days);
    router.push('/new');
  }

  // ---- Goal-aware heroes ---------------------------------------------------------
  const heroes = useMemo(() => {
    if (!result) return [];
    const k = result.kpis;
    const money = (v: number) => `${cur} ${Math.round(v).toLocaleString()}`;
    if (objective === 'awareness') {
      return [
        { label: 'Impressions', v: k.impressions.toLocaleString(), sub: `${cur} ${k.cpm?.toFixed(2)} CPM`, d: null },
        { label: 'CPM', v: k.cpm != null ? `${cur} ${k.cpm.toFixed(2)}` : '—', sub: 'cost per 1k views', d: delta(k.cpm ?? 0, baseline?.kpis.cpm ?? undefined, true) },
        { label: 'Clicks', v: Math.round(k.clicks.p50).toLocaleString(), sub: 'secondary signal', d: delta(k.clicks.p50, baseline?.kpis.clicks.p50) },
      ];
    }
    if (objective === 'consideration') {
      return [
        { label: 'Clicks', v: Math.round(k.clicks.p50).toLocaleString(), sub: `${Math.round(k.clicks.p10).toLocaleString()}–${Math.round(k.clicks.p90).toLocaleString()}`, d: delta(k.clicks.p50, baseline?.kpis.clicks.p50) },
        { label: 'CTR', v: `${(k.ctr * 100).toFixed(2)}%`, sub: 'simulated audience', d: null },
        { label: 'Cost / click', v: money(k.spend / Math.max(k.clicks.p50, 1)), sub: 'at p50', d: delta(k.spend / Math.max(k.clicks.p50, 1), baseline ? baseline.kpis.spend / Math.max(baseline.kpis.clicks.p50, 1) : undefined, true) },
      ];
    }
    return [
      { label: 'Conversions', v: Math.round(k.conversions.p50).toLocaleString(), sub: `${Math.round(k.conversions.p10)}–${Math.round(k.conversions.p90)}`, d: delta(k.conversions.p50, baseline?.kpis.conversions.p50) },
      { label: 'Cost / conversion', v: k.conversions.p50 > 0 ? money(k.spend / k.conversions.p50) : '—', sub: 'at p50', d: delta(k.spend / Math.max(k.conversions.p50, 0.01), baseline ? baseline.kpis.spend / Math.max(baseline.kpis.conversions.p50, 0.01) : undefined, true) },
      { label: 'ROAS', v: `${k.roas.p50.toFixed(2)}×`, sub: `${k.roas.p10.toFixed(2)}–${k.roas.p90.toFixed(2)}×`, d: delta(k.roas.p50, baseline?.kpis.roas.p50) },
    ];
  }, [result, objective, cur, baseline]);

  const ctl = 'block text-[10px] font-bold uppercase tracking-[0.09em] mb-1.5';
  const selStyle = { background: LAB.panel, color: LAB.ink } as const;

  return (
    <div className="max-w-6xl">
      <div className="flex items-end gap-4 flex-wrap mb-1">
        <h1 className="display-italic text-[34px]">The <span className="gradient-text">simulation lab</span></h1>
        <Pill tone="violet">the real forecasting engine, live</Pill>
      </div>
      <p className="text-ink-muted text-[14.5px] mb-5 max-w-2xl">
        Move a factor — watch {result?.meta.audience_personas ?? 600} simulated consumers,
        shaped like <strong>{companyName}&apos;s real buyers</strong>, re-live the campaign.
        Ready to score a real creative? <Link href="/new" className="text-violet underline font-semibold">New analysis</Link>.
      </p>

      {/* THE INSTRUMENT PANEL */}
      <div className="rounded-2xl p-5 sm:p-6 relative overflow-hidden"
        style={{ background: LAB.bg, color: LAB.ink, boxShadow: '0 24px 64px rgba(0,0,0,0.28)' }}>
        {/* Brand aurora — one quiet signature, top-left */}
        <div className="absolute -left-24 -top-32 w-[420px] h-[420px] rounded-full pointer-events-none"
          style={{ background: 'radial-gradient(circle, rgba(255,94,26,0.14), transparent 65%)' }} />
        <div className="relative grid grid-cols-1 lg:grid-cols-[252px_1fr] gap-6">

          {/* CONTROL RAIL */}
          <div className="space-y-4">
            <div>
              <span className={ctl} style={{ color: LAB.faint }}>Goal</span>
              <div className="flex rounded-lg p-1 gap-1" style={{ background: LAB.panel }}>
                {(['awareness', 'consideration', 'conversion'] as const).map((o) => (
                  <button key={o} type="button" onClick={() => setObjective(o)}
                    className="flex-1 px-1 py-1.5 rounded-md text-[10.5px] font-bold capitalize transition-colors"
                    style={objective === o
                      ? { background: 'linear-gradient(120deg,#FF5E1A,#E8366B)', color: '#fff' }
                      : { color: LAB.muted }}>
                    {o === 'consideration' ? 'clicks' : o}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <span className={ctl} style={{ color: LAB.faint }}>
                Audience <ProvChip p={defaultsNote.audience ?? 'assumption'} />
              </span>
              <select value={audiencePick} onChange={(e) => setAudiencePick(e.target.value)}
                className="w-full rounded-md px-2.5 py-2 text-[12.5px] border-0" style={selStyle}>
                {yourMix && (
                  <option value="yours">✨ {companyName}&apos;s buyers — real delivery mix</option>
                )}
                {savedAudiences.length > 0 && (
                  <optgroup label="Your saved audiences">
                    {savedAudiences.map((a) => (
                      <option key={a.id} value={`aud:${a.id}`}>{a.name}</option>
                    ))}
                  </optgroup>
                )}
                <optgroup label="Explore other audiences">
                  {SEGMENTS.map(([id, label]) => <option key={id} value={`seg:${id}`}>{label}</option>)}
                </optgroup>
              </select>
              {audiencePick === 'yours' && yourMix && (
                <div className="text-[10px] mt-1" style={{ color: LAB.faint }}>
                  population reshaped to your top cells: {yourMix.slice(0, 3)
                    .map((m) => `${m.gender === 'male' ? 'M' : m.gender === 'female' ? 'W' : '?'} ${m.age} ${(m.share * 100).toFixed(0)}%`).join(' · ')}…
                </div>
              )}
            </div>

            <div>
              <span className={ctl} style={{ color: LAB.faint }}>Platform · format</span>
              <select value={platformId}
                onChange={(e) => {
                  setPlatformId(e.target.value);
                  const p = platforms.find((x) => x.id === e.target.value);
                  if (p?.formats[0]) setFormatId(p.formats[0].id);
                }}
                className="w-full rounded-md px-2.5 py-2 text-[12.5px] mb-1.5 border-0" style={selStyle}>
                {platforms.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <select value={format?.id ?? ''} onChange={(e) => setFormatId(e.target.value)}
                className="w-full rounded-md px-2.5 py-2 text-[12.5px] border-0" style={selStyle}>
                {platform?.formats.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </div>

            <div>
              <span className={ctl} style={{ color: LAB.faint }}>
                Budget · <ProvChip p={defaultsNote.budget ?? 'assumption'} />
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
                Fatigue · <ProvChip p={defaultsNote.fatigue ?? 'assumption'} />
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
                className="w-full rounded-md px-2.5 py-2 text-[13px] font-mono border-0" style={selStyle} />
            </div>

            <div className="pt-2 space-y-2">
              <button type="button" onClick={pinCurrent} disabled={!result || pinned.length >= 2}
                className="w-full py-2 rounded-lg text-[12px] font-bold transition-colors disabled:opacity-40"
                style={{ background: LAB.panelUp, color: LAB.ink, border: `1px solid ${LAB.line}` }}>
                ⊕ Pin this scenario {pinned.length > 0 && `(${pinned.length}/2)`}
              </button>
              <button type="button" onClick={runForReal}
                className="w-full py-2.5 rounded-lg text-[12.5px] font-bold text-white transition-transform active:scale-[0.98]"
                style={{ background: 'linear-gradient(120deg,#FF5E1A,#E8366B)', boxShadow: '0 6px 20px rgba(232,80,15,0.35)' }}>
                Run this for real →
              </button>
            </div>
          </div>

          {/* THE STAGE */}
          <div className="min-w-0">
            {/* Scenario tray */}
            {pinned.length > 0 && (
              <div className="flex gap-2 mb-3 flex-wrap">
                {pinned.map((p) => (
                  <div key={p.id} className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-[11px]"
                    style={{ background: LAB.panel, borderTop: `3px solid ${p.color}` }}>
                    <span className="font-mono" style={{ color: LAB.muted }}>{p.label}</span>
                    <span className="font-mono font-bold">{Math.round(p.kpis.conversions.p50)} conv</span>
                    <button type="button" onClick={() => setPinned((cur0) => cur0.filter((x) => x.id !== p.id))}
                      className="hover:opacity-70" style={{ color: LAB.faint }} aria-label={`Unpin ${p.label}`}>✕</button>
                  </div>
                ))}
                <div className="flex items-center text-[10.5px]" style={{ color: LAB.faint }}>
                  deltas below compare live vs first pin
                </div>
              </div>
            )}

            {/* Hero metrics */}
            <div className="grid grid-cols-3 gap-3 mb-4">
              {(heroes.length ? heroes : [1, 2, 3].map(() => null)).map((m, i) => (
                <div key={i} className="rounded-xl px-4 py-3 transition-opacity duration-200"
                  style={{ background: LAB.panel, opacity: running ? 0.55 : 1 }}>
                  {m ? (
                    <>
                      <div className="text-[9.5px] font-bold uppercase tracking-[0.1em]" style={{ color: LAB.faint }}>{m.label}</div>
                      <div className="font-mono font-bold text-[22px] leading-tight mt-0.5">{m.v}</div>
                      <div className="text-[10.5px] flex items-center gap-2" style={{ color: LAB.muted }}>
                        {m.sub}
                        {m.d && (
                          <span className="font-mono font-bold" style={{ color: m.d.good ? LAB.converted : LAB.clicked }}>
                            {m.d.text}
                          </span>
                        )}
                      </div>
                    </>
                  ) : <div className="h-[52px] text-[11px] flex items-center" style={{ color: LAB.faint }}>simulating…</div>}
                </div>
              ))}
            </div>

            {error && (
              <div className="rounded-lg px-4 py-3 mb-4 text-[12.5px]" style={{ background: '#3A1F17', color: '#F0A088' }}>
                {error}
              </div>
            )}

            {result && (
              <>
                <div className="rounded-xl p-4 mb-4" style={{ background: LAB.panel }}>
                  <div className="flex items-baseline justify-between flex-wrap gap-2 mb-2.5">
                    <span className="text-[10.5px] font-bold uppercase tracking-[0.1em]" style={{ color: LAB.faint }}>
                      The population — {result.timeline.agents} of {audience.label}
                    </span>
                    <span className="text-[10.5px]" style={{ color: running ? LAB.clicked : LAB.faint }}>
                      {running ? '● re-simulating…' : result.meta.audience_source}
                    </span>
                  </div>
                  <PopulationField frames={result.timeline.frames} agents={result.timeline.agents}
                    cells={result.timeline.cells} onDay={setFieldDay} />
                </div>

                <div className="grid grid-cols-1 xl:grid-cols-[1fr_330px] gap-4">
                  <div className="space-y-4 min-w-0">
                    <div className="rounded-xl p-4" style={{ background: LAB.panel }}>
                      <span className="text-[10.5px] font-bold uppercase tracking-[0.1em] block mb-2" style={{ color: LAB.faint }}>
                        The flight path
                      </span>
                      <FlightPath daily={result.daily}
                        ghosts={pinned.map((p) => ({ label: p.label, color: p.color, p50: p.p50 }))} />
                    </div>
                    <div className="rounded-xl p-4" style={{ background: LAB.panel }}>
                      <span className="text-[10.5px] font-bold uppercase tracking-[0.1em] block mb-2.5" style={{ color: LAB.faint }}>
                        The forces on this scenario
                      </span>
                      <Forces factors={result.factors} />
                    </div>
                  </div>
                  <div className="rounded-xl p-4 self-start" style={{ background: LAB.panel }}>
                    <span className="text-[10.5px] font-bold uppercase tracking-[0.1em] block mb-1.5" style={{ color: LAB.faint }}>
                      The street — campaign diary
                    </span>
                    <EventTicker events={result.events ?? []} currentDay={fieldDay} />
                  </div>
                </div>

                <div className="flex flex-wrap gap-x-4 gap-y-1 mt-4 text-[10.5px]" style={{ color: LAB.faint }}>
                  <span>{result.meta.n_runs} Monte-Carlo runs · {result.meta.sim_days} days · {result.meta.audience_personas} personas</span>
                  <span>audience: {result.meta.audience_source}</span>
                  <span>creative: {result.meta.creative}</span>
                  <span>fatigue: {result.meta.fatigue_source}</span>
                  <span>bands show run-to-run spread, not full real-world uncertainty</span>
                </div>
              </>
            )}
            {!result && !error && (
              <div className="rounded-xl p-10 text-center text-[13px]" style={{ background: LAB.panel, color: LAB.muted }}>
                Warming up the simulator…
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
