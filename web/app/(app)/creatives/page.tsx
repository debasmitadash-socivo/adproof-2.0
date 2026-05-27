'use client';
import Link from 'next/link';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { useApp } from '@/lib/store';

export default function CreativesPage() {
  const campaigns = useApp((s) => s.savedCampaigns);
  const withImages = campaigns.filter((c) => c.thumbnailUrl);
  return (
    <>
      <div className="display-italic text-[38px] leading-[1.05]">
        Your <span className="gradient-text">creatives</span>
      </div>
      <p className="text-ink-muted mt-1.5 text-[14.5px] mb-6">
        Every image you upload during an analysis is saved here. Library uploads independent of a campaign land in v1.1.
      </p>
      {withImages.length === 0 ? (
        <Card className="text-center py-14">
          <div className="text-5xl mb-3">🖼️</div>
          <div className="font-heading text-[17px] font-bold mb-1">No creatives yet</div>
          <p className="text-ink-muted text-[14px] max-w-md mx-auto mb-5">
            Run an analysis and any image you upload will appear here.
          </p>
          <Link href="/new"><Button>Start a new analysis</Button></Link>
        </Card>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
          {withImages.map((c) => (
            <Card key={c.id} className="!p-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={c.thumbnailUrl!} alt="" className="w-full aspect-square object-cover rounded-md border border-border" />
              <div className="mt-2.5 font-semibold text-[13.5px] line-clamp-1">{c.name}</div>
              <div className="text-ink-muted text-[12px] line-clamp-1">{c.platformName} · {c.formatName}</div>
              <div className="text-coral font-mono text-[13px] mt-1.5"><strong>{c.roasP50.toFixed(2)}×</strong> ROAS</div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
