import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#FBF8F3',
        'bg-deep': '#F5EFE6',
        surface: '#FFFFFF',
        border: { DEFAULT: '#E8DFCF', soft: '#F1EADC' },
        ink: { DEFAULT: '#1C1917', muted: '#78716C', faint: '#A8A29E' },
        coral: { DEFAULT: '#FF5E1A', hover: '#E54A0A', soft: '#FFEDDD' },
        magenta: { DEFAULT: '#E0218A', soft: '#FCE7F3' },
        violet: { DEFAULT: '#7C3AED', soft: '#EDE9FE' },
        lime: { DEFAULT: '#BEF264', deep: '#65A30D', soft: '#F0FDDB' },
        sky: '#38BDF8',
        success: { DEFAULT: '#16A34A', soft: '#DCFCE7' },
        warning: { DEFAULT: '#EAB308', soft: '#FEF9C3' },
        danger: { DEFAULT: '#DC2626', soft: '#FEE2E2' },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        display: ['"Instrument Serif"', 'Georgia', 'serif'],
        heading: ['"Bricolage Grotesque"', 'Inter', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      backgroundImage: {
        'gradient-sunset':
          'linear-gradient(135deg, #FF5E1A 0%, #E0218A 45%, #7C3AED 100%)',
        'gradient-aurora':
          'linear-gradient(135deg, #FFB347 0%, #FF5E1A 35%, #E0218A 65%, #5B21B6 100%)',
        'gradient-fresh':
          'linear-gradient(135deg, #BEF264 0%, #16A34A 100%)',
        'gradient-night': 'linear-gradient(135deg, #1C1917 0%, #5B21B6 100%)',
      },
      boxShadow: {
        glow:
          '0 8px 32px rgba(255,94,26,0.25), 0 2px 8px rgba(224,33,138,0.15)',
        soft: '0 2px 8px rgba(28,25,23,0.06), 0 1px 3px rgba(28,25,23,0.04)',
        lift: '0 24px 48px rgba(28,25,23,0.10), 0 6px 16px rgba(28,25,23,0.06)',
      },
      borderRadius: {
        DEFAULT: '12px',
        md: '16px',
        lg: '22px',
        xl: '32px',
      },
    },
  },
  plugins: [],
};
export default config;
