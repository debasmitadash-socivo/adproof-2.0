/** @type {import('next').NextConfig} */
// In production, set NEXT_PUBLIC_API_URL on Vercel to the Railway URL of the
// FastAPI backend (e.g. https://adproof-api.up.railway.app). In dev we
// default to localhost:8000 so `npm run dev` works without any env vars.
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
