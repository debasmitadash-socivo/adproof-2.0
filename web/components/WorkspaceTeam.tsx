'use client';
// Team roster + invites for the CURRENT workspace. Lives on the Company
// profile page. Invites are email-matched (no email is actually sent): the
// teammate signs in to AdProof with the invited address and the workspace
// appears in their switcher automatically.
import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Card, CardTitle } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { useApp } from '@/lib/store';
import {
  listMembers, inviteMember, removeMember,
} from '@/lib/db';
import type { WorkspaceMember } from '@/lib/types';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function WorkspaceTeam({
  workspaceId, isOwner,
}: { workspaceId?: string; isOwner: boolean }) {
  const user = useApp((s) => s.user);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (!workspaceId) return;
    let alive = true;
    setLoadErr(null);
    listMembers(workspaceId)
      .then((m) => { if (alive) setMembers(m); })
      .catch((e) => { if (alive) setLoadErr((e as Error).message); });
    return () => { alive = false; };
  }, [workspaceId]);

  async function invite() {
    if (!workspaceId) return;
    const clean = email.trim().toLowerCase();
    setErr(null); setNote(null);
    if (!EMAIL_RE.test(clean)) { setErr('That doesn\'t look like an email address.'); return; }
    if (clean === user?.email?.toLowerCase()) { setErr('That\'s you — no invite needed.'); return; }
    setBusy(true);
    try {
      const m = await inviteMember(workspaceId, clean);
      setMembers((cur) => [...cur, m]);
      setEmail('');
      setNote(`${clean} is invited. Ask them to sign in to AdProof with that email — this workspace will appear in their switcher automatically.`);
    } catch (e) {
      setErr((e as Error).message);
    } finally { setBusy(false); }
  }

  async function remove(m: WorkspaceMember) {
    setErr(null); setNote(null);
    try {
      await removeMember(m.id);
      setMembers((cur) => cur.filter((x) => x.id !== m.id));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  if (!workspaceId) {
    return (
      <Card>
        <CardTitle>Team</CardTitle>
        <div className="text-ink-muted text-[13.5px]">
          Save your company profile first — then you can invite teammates to this workspace.
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle>Team</CardTitle>
      <p className="text-[13px] text-ink-muted -mt-1 mb-4">
        {isOwner
          ? 'Share this workspace with teammates. They\'ll see and run everything in it — campaigns, audiences, results — but can\'t edit the company profile or manage the team.'
          : 'This workspace is shared with you. Only its owner can manage the team.'}
      </p>

      {isOwner && (
        <div className="flex gap-2 mb-4">
          <input
            className="input flex-1"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') invite(); }}
            placeholder="teammate@company.com"
            disabled={busy}
          />
          <Button onClick={invite} disabled={busy || !email.trim()}>
            {busy ? 'Inviting…' : 'Invite'}
          </Button>
        </div>
      )}

      {err && (
        <div className="mb-3 text-[13px] text-danger bg-danger-soft border border-danger/30 rounded-md p-3">{err}</div>
      )}
      {note && (
        <div className="mb-3 text-[13px] bg-violet-soft border border-violet/30 rounded-md p-3">{note}</div>
      )}
      {loadErr && (
        <div className="mb-3 text-[13px] text-danger bg-danger-soft border border-danger/30 rounded-md p-3">{loadErr}</div>
      )}

      <div className="space-y-2">
        {isOwner && (
          <div className="flex items-center gap-2.5 text-[13.5px]">
            <span className="flex-1 truncate">{user?.email || 'You'}</span>
            <Pill tone="coral">owner</Pill>
          </div>
        )}
        {members.map((m) => (
          <div key={m.id} className="flex items-center gap-2.5 text-[13.5px]">
            <span className="flex-1 truncate">{m.email}</span>
            <Pill tone={m.status === 'active' ? 'success' : 'muted'}>
              {m.status === 'active' ? 'active' : 'invited'}
            </Pill>
            {isOwner && (
              <button
                type="button"
                onClick={() => remove(m)}
                className="text-[12px] text-ink-muted hover:text-danger transition-colors"
                title="Remove from workspace"
              >
                Remove
              </button>
            )}
          </div>
        ))}
        {members.length === 0 && !loadErr && (
          <div className="text-ink-muted text-[13px]">
            {isOwner ? 'No teammates yet.' : 'No other members visible.'}
          </div>
        )}
      </div>
    </Card>
  );
}
