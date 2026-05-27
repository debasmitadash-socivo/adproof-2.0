'use client';
import { useState } from 'react';

export function HelpHint({ children, label = 'What is this?' }: { children: React.ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span
      className="relative inline-flex items-center align-middle ml-1.5"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onClick={() => setOpen((o) => !o)}
    >
      <button
        type="button"
        aria-label={label}
        className="w-4 h-4 rounded-full bg-border text-ink-muted text-[10px] font-bold leading-4 text-center hover:bg-coral hover:text-white transition-colors cursor-help"
      >?</button>
      {open && (
        <span
          role="tooltip"
          className="absolute z-30 left-5 top-1/2 -translate-y-1/2 w-[280px] bg-ink text-white text-[12px] leading-snug p-2.5 rounded-md shadow-lift"
          style={{ pointerEvents: 'none' }}
        >
          {children}
        </span>
      )}
    </span>
  );
}
