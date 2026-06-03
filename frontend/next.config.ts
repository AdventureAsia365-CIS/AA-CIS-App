import type { NextConfig } from "next";
import path from "path";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default withSentryConfig(nextConfig, {
  org: "dk-0ql",
  project: "aa-cis-frontend",
  silent: true,
  widenClientFileUpload: true,
  hideSourceMaps: true,
  disableLogger: true,
});
