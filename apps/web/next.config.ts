import type { NextConfig } from "next";

// The browser talks to the API through this app's own origin (/api/*), so it works on any host/port
// without CORS or a baked-in public API address. API_INTERNAL_URL is where the Next.js server finds the API.
const apiInternalUrl = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");

const config: NextConfig = {
  output: "standalone",
  transpilePackages: ["@nexa/ui", "@nexa/agent-schema", "@nexa/shared-types", "@nexa/workflow-engine"],
  outputFileTracingRoot: new URL("../../", import.meta.url).pathname,
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiInternalUrl}/:path*` }];
  },
};

export default config;
