'use client';
import { ButtonHTMLAttributes, forwardRef } from 'react';
import clsx from 'clsx';

type Variant = 'primary' | 'secondary' | 'ghost' | 'dark';
type Size = 'sm' | 'md' | 'lg';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const VARIANT: Record<Variant, string> = {
  primary:
    'bg-gradient-sunset text-white shadow-glow hover:-translate-y-px hover:shadow-[0_12px_36px_rgba(255,94,26,0.35)]',
  secondary:
    'bg-surface text-ink border border-border hover:bg-coral-soft hover:border-coral',
  ghost:
    'bg-transparent text-ink-muted hover:bg-coral-soft hover:text-coral',
  dark: 'bg-ink text-white hover:bg-black',
};
const SIZE: Record<Size, string> = {
  sm: 'px-3 py-1.5 text-[12.5px]',
  md: 'px-4 py-2.5 text-[14px]',
  lg: 'px-6 py-3 text-[15px]',
};

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = 'primary', size = 'md', className, ...props },
  ref
) {
  return (
    <button
      ref={ref}
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded-full font-semibold transition-all',
        'disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0',
        VARIANT[variant],
        SIZE[size],
        className
      )}
      {...props}
    />
  );
});
