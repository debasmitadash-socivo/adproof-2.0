import clsx from 'clsx';

export function Card({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={clsx(
        'bg-surface border border-border rounded-md p-5 shadow-soft',
        className
      )}
    >
      {children}
    </div>
  );
}

export function CardTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11.5px] text-ink-muted font-bold uppercase tracking-[0.09em] mb-3">
      {children}
    </div>
  );
}
