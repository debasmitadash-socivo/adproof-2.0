/** @type {import('next').NextConfig} */
// API backend the frontend proxies /api and /uploads to.
//   1. NEXT_PUBLIC_API_URL  (set this if the backend ever moves)
//   2. else, in a production build → the live Railway backend
//   3. else (local `npm run dev`) → localhost:8000
// Without rule 2, a Vercel deploy with no env var proxied to localhost and
// every /api call 404'd (DNS_HOSTNAME_RESOLVED_PRIVATE).
const PROD_API_URL = 'https://adproof-production.up.railway.app';
const API_URL =
  process.env.NEXT_PUBLIC_API_URL ||
  (process.env.NODE_ENV === 'production' ? PROD_API_URL : 'http://localhost:8000');

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${API_URL}/api/:path*`,
      },
      // FastAPI serves uploaded creatives at /uploads/* via StaticFiles.
      // Without this proxy, every thumbnail (creatives gallery, dashboard
      // table, variant leaderboard) returns 404.
      {
        source: '/uploads/:path*',
        destination: `${API_URL}/uploads/:path*`,
      },
    ];
  },
};
export default nextConfig;
