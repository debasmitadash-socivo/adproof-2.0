'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { useApp } from '@/lib/store';
import type { SavedCampaign } from '@/lib/types';

const VERDICT_TONE: Record<SavedCampaign['verdictClass'], 'success' | 'coral' | 'warning' | 'danger'> = {
  strong: 'success',
  positive: 'coral',
  break_even: 'warning',
  underperforming: 'danger',
};
const VERDICT_LABEL: Record<SavedCampaign['verdictClass'], string> = {
  strong: 'Strong',
  positive: 'Positive',
  break_even: 'Break-even',
  underperforming: 'Underperforming',
};

export default function DashboardPage() {
  const router = useRouter();
  const user = useApp((s) => s.user);
  const campaigns = useApp((s) => s.savedCampaigns);
  const audiences = useApp((s) => s.savedAudiences);
  const setResult = useApp((s) => s.setResult);
  const setCurrentCampaign = useApp((s) => s.setCurrentCampaign);

  const greeting = greetingFor();
  const firstName = (user?.name ?? '').trim().split(/\s+/)[0] || '';

  const metrics = computeMetrics(campaigns);

  return (
    <>
      <div className="flex items-end gap-6 mb-2">
        <div>
          <div className="display-italic text-[52px] leading-[1.05]">
            {greeting}{firstName ? <>, <span className="gradient-text">{firstName}.</span></> : <>.</>}
          </div>
          <div className="text-ink-muted mt-1.5 text-[14.5px]">
            {campaigns.length === 0
              ? <>Your workspace is empty. Run your first analysis to start filling it in.</>
              : <>{campaigns.length} campaign{campaigns.length === 1 ? '' : 's'} tested · {audiences.length} audience{audiences.length === 1 ? '' : 's'} saved</>
            }
          </div>
        </div>
        <div className="flex-1" />
        <Link href="/audiences"><Button variant="secondary">+ New audience</Button></Link>
      </div>

      <Link href="/new">
        <div className="relative bg-gradient-sunset text-white rounded-md px-8 py-7 my-4 flex items-center gap-7 overflow-hidden shadow-glow cursor-pointer hover:shadow-[0_24px_56px_rgba(255,94,26,0.40)] transition-shadow">
          <div className="absolute inset-0 mesh-overlay" />
          <div className="absolute -right-20 -top-20 w-[280px] h-[280px] rounded-full pointer-events-none" style={{ background: 'radial-gradient(circle, rgba(190,242,100,0.35), transparent 65%)' }} />
          <div className="relative z-10 flex-1">
            <div className="text-[11.5px] font-bold uppercase tracking-[0.16em] opacity-85">Pre-flight check</div>
            <h2 className="display-italic text-[36px] mt-1.5 mb-1.5">
              {campaigns.length === 0 ? 'Score your first ad.' : 'Score your next ad before you spend a cent.'}
            </h2>
            <p className="opacity-95 text-[14.5px] max-w-[520px]">
              Upload a creative, pick a platform and audience, and get a defensible forecast — CTR, conversions, ROAS bands, and a &ldquo;why this will work&rdquo; written by the model.
            </p>
          </div>
          <Button size="lg" className="relative z-10 bg-white !text-coral hover:!bg-bg shadow-lg !bg-none">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" /></svg>
            Start a new analysis
          </Button>
        </div>
      </Link>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Campaigns tested', value: metrics.count, sub: metrics.countSub, tint: 'from-coral-soft', glyph: '📊' },
          { label: 'Avg forecast ROAS', value: metrics.avgRoas, sub: metrics.avgRoasSub, tint: 'from-magenta-soft', glyph: '✨' },
          { label: 'Best · ROAS', value: metrics.bestFormat, sub: metrics.bestSub, tint: 'from-violet-soft', glyph: '🚀' },
          { label: 'Last analysis', value: metrics.lastWhen, sub: metrics.lastSub, tint: 'from-lime-soft', glyph: '🕒' },
        ].map((m) => (
          <Card key={m.label} className={`relative overflow-hidden bg-gradient-to-br ${m.tint} to-surface`}>
            <div className="absolute right-4 top-4 text-2xl">{m.glyph}</div>
            <div className="text-[11.5px] text-ink-muted uppercase tracking-[0.09em] font-bold">{m.label}</div>
            <div className="display-italic text-[38px] mt-1 leading-none">{m.value}</div>
            <div className="text-[12.5px] text-ink-muted font-semibold mt-2">{m.sub}</div>
          </Card>
        ))}
      </div>

      <div className="flex items-center justify-between mt-8 mb-3.5">
        <h2 className="font-heading text-[18px] font-bold tracking-tight">Recent analyses</h2>
        {campaigns.length > 0 && (
          <Link href="/campaigns" className="text-[13px] font-semibold text-coral">View all →</Link>
        )}
      </div>

      {campaigns.length === 0 ? (
        <Card className="text-center py-12">
          <div className="text-5xl mb-3">📈</div>
          <div className="font-heading text-[17px] font-bold mb-1">No analyses yet</div>
          <p className="text-ink-muted text-[14px] max-w-md mx-auto mb-5">
            Run your first analysis and we&apos;ll start tracking trends, surfacing recommendations, and letting you compare creatives side by side.
          </p>
          <Link href="/new"><Button>Run my first analysis</Button></Link>
        </Card>
      ) : (
        <Card className="!p-0 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-bg-deep">
                {['Creative', 'Platform / Format', 'Audience', 'Budget', 'ROAS (p50)', 'Verdict', 'Updated'].map((h) => (
                  <th key={h} className="text-left text-[11.5px] text-ink-muted font-bold uppercase tracking-[0.07em] px-4 py-3 border-b border-border">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {campaigns.slice(0, 8).map((c) => (
                <tr
                  key={c.id}
                  className="border-b border-border-soft last:border-b-0 hover:bg-coral-soft cursor-pointer transition-colors"
                  onClick={() => { setResult(c.result); setCurrentCampaign(c); router.push('/result'); }}
                >
                  <td className="px-4 py-3.5 text-[13.5px]">
                    <div className="flex items-center gap-2.5">
                      {c.thumbnailUrl ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={c.thumbnailUrl} alt="" className="w-9 h-9 rounded-md object-cover border border-border" />
                      ) : (
                        <div className="w-9 h-9 rounded-md bg-gradient-sunset" />
                      )}
                      <div>
                        <div className="font-semibold">{c.name}</div>
                        <div className="text-ink-muted text-[12px]">{new Date(c.createdAt).toLocaleString()}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3.5 text-[13.5px]">
                    <div>{c.platformName}</div>
                    <div className="text-ink-muted text-[12px]">{c.formatName}</div>
                  </td>
                  <td className="px-4 py-3.5 text-[13.5px]">{c.audienceLabel}</td>
                  <td className="px-4 py-3.5 text-[13.5px]">${c.budget.toLocaleString()}</td>
                  <td className="px-4 py-3.5 text-[13.5px] font-mono"><strong>{c.roasP50.toFixed(2)}×</strong></td>
                  <td className="px-4 py-3.5"><Pill tone={VERDICT_TONE[c.verdictClass]} dot>{VERDICT_LABEL[c.verdictClass]}</Pill></td>
                  <td className="px-4 py-3.5 text-[13.5px] text-ink-muted">{relativeTime(c.createdAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 mt-7">
        <Card>
          <CardTitle>Saved audiences</CardTitle>
          {audiences.length === 0 ? (
            <div className="py-6 text-center">
              <div className="text-ink-muted text-[14px] mb-3">No audiences saved yet.</div>
              <Link href="/audiences"><Button variant="secondary" size="sm">+ Create your first audience</Button></Link>
            </div>
          ) : (
            <div className="flex flex-col gap-2.5">
              {audiences.slice(0, 4).map((a) => (
                <div key={a.id} className="border border-border rounded-md p-3.5 flex items-center gap-3 hover:border-coral hover:shadow-soft transition-all">
                  <div className="w-7 h-7 rounded-full bg-gradient-aurora" />
                  <div className="flex-1">
                    <strong>{a.name}</strong>
                    <div className="text-ink-muted text-[12.5px]">{a.description.slice(0, 80)}{a.description.length > 80 ? '…' : ''}</div>
                  </div>
                  <Link className="text-coral text-[13px] font-semibold" href="/audiences">Edit →</Link>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <CardTitle>Recommendations</CardTitle>
          {campaigns.length === 0 ? (
            <div className="text-ink-muted text-[14px] py-6 text-center">
              Recommendations appear after your first analysis — we look across runs to surface what&apos;s working and what to test next.
            </div>
          ) : (
            <ul className="flex flex-col gap-3 text-[14px]">
              {generateRecommendations(campaigns).map((r, i) => (
                <li key={i} className="flex gap-3 items-start">
                  <Pill tone={r.tone}>{r.glyph}</Pill>
                  <div><strong>{r.title}</strong><div className="text-ink-muted text-[12.5px]">{r.body}</div></div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

// ============================================================================
// Helpers
// ============================================================================

function greetingFor() {
  const h = new Date().getHours();
  if (h < 5) return 'You\'re up late';
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

function relativeTime(t: number): string {
  const diff = Date.now() - t;
  const m = Math.floor(diff / 60_000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function computeMetrics(campaigns: SavedCampaign[]) {
  if (campaigns.length === 0) {
    return {
      count: '—', countSub: 'No analyses yet',
      avgRoas: '—', avgRoasSub: 'Run one to see',
      bestFormat: '—', bestSub: 'No data',
      lastWhen: '—', lastSub: 'No data',
    };
  }
  const count = campaigns.length;
  const avg = campaigns.reduce((s, c) => s + c.roasP50, 0) / count;
  const best = campaigns.reduce((b, c) => (c.roasP50 > b.roasP50 ? c : b));
  const last = campaigns.reduce((b, c) => (c.createdAt > b.createdAt ? c : b));
  return {
    count: String(count),
    countSub: count === 1 ? '1 analysis' : `${count} analyses`,
    avgRoas: `${avg.toFixed(2)}×`,
    avgRoasSub: `across ${count} run${count === 1 ? '' : 's'}`,
    bestFormat: best.formatName,
    bestSub: `${best.roasP50.toFixed(2)}× ROAS`,
    lastWhen: relativeTime(last.createdAt),
    lastSub: last.name,
  };
}

function generateRecommendations(campaigns: SavedCampaign[]) {
  const out: { tone: 'success' | 'warning' | 'violet'; glyph: string; title: string; body: string }[] = [];
  const underperformers = campaigns.filter((c) => c.verdictClass === 'underperforming');
  const strong = campaigns.filter((c) => c.verdictClass === 'strong');
  if (underperformers.length > 0) {
    out.push({
      tone: 'warning', glyph: '!',
      title: `${underperformers.length} campaign${underperformers.length === 1 ? '' : 's'} forecasting below break-even`,
      body: `Review ${underperformers[0].name} — sub-1× ROAS often means audience-fit drag or weak creative cues.`,
    });
  }
  if (strong.length > 0) {
    out.push({
      tone: 'success', glyph: '✓',
      title: `Lean into what's working: ${strong[0].formatName}`,
      body: `Your strongest forecast so far is ${strong[0].roasP50.toFixed(2)}× ROAS on ${strong[0].platformName}.`,
    });
  }
  if (campaigns.length >= 2) {
    out.push({
      tone: 'violet', glyph: '→',
      title: 'Compare your last two creatives side by side',
      body: 'Use Compare on the Result page to see exactly where one outperforms the other.',
    });
  }
  return out.length > 0 ? out : [{
    tone: 'violet' as const, glyph: '→',
    title: 'Run a sensitivity sweep on your strongest format',
    body: 'See whether bigger budgets still scale efficiently before committing real spend.',
  }];
}
