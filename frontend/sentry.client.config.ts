import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_ENV || "dev",
  tracesSampleRate: 0.1,
  release: process.env.NEXT_PUBLIC_BUILD_SHA,
});
