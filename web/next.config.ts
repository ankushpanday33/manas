import type { NextConfig } from "next";

const API = process.env.MANAS_API ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  // The browser only talks to Next; Next forwards /api/* to the Python brain engine.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default config;
