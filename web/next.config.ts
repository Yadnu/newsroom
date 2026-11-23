import type { NextConfig } from "next";

// The browser talks to the API through this app (same origin): no CORS on the backend, and the
// Web Audio analyser can read telecast audio. Server components still call NEWSROOM_API_URL directly.
const API_URL = (process.env.NEWSROOM_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_URL}/:path*` },
      // Telecast audio (task 8.3): same origin, so the Web Audio analyser may read it.
      { source: "/media/:path*", destination: `${API_URL}/media/:path*` },
    ];
  },
};

export default nextConfig;
