import clsx from 'clsx';

type Tone = 'success' | 'warning' | 'danger' | 'coral' | 'magenta' | 'violet' | 'lime' | 'muted';

const tones: Record<Tone, string> = {
  success: 'bg-success-soft text-green-800',
  warning: 'bg-warning-soft text-yellow-800',
  danger: 'bg-danger-soft text-red-800',
  coral: 'bg-coral-soft text-coral',
  magenta: 'bg-magenta-soft text-pink-900',
  violet: 'bg-violet-soft text-violet',
  lime: 'bg-lime-soft text-lime-deep',
  muted: 'bg-border-soft text-ink-muted',
};

export function Pill({
  tone = 'muted',
  dot = false,
  children,
}: {
  tone?: Tone;
  dot?: boolean;
  children: React.ReactNode;
}) {
  return (
    <span className={clsx('pill', tones[tone])}>
      {dot && <span className="w-1.5 h-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}
