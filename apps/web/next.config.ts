import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  transpilePackages: ["@nexa/ui", "@nexa/agent-schema", "@nexa/shared-types", "@nexa/workflow-engine"],
  outputFileTracingRoot: new URL("../../", import.meta.url).pathname,
  poweredByHeader: false,
};

export default config;
