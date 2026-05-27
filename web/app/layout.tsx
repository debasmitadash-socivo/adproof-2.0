import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AdProof — score every ad before you ship it',
  description:
    'Agent-based ad forecasting. Upload a creative, pick your platform and audience, get a defensible verdict before you spend.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
