import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'flightops — rotation cascades',
  description:
    'Which delay is actually costing the day, where it lands next, and what a recovery buys. ' +
    'Built on US BTS On-Time Performance data.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
