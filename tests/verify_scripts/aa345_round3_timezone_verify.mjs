// AA-345 round 3, Việc 2 — regression check for the "Atomized on <date>"
// timezone bug (frontend/app/admin/atomize/page.tsx and
// frontend/app/admin/curation/page.tsx's formatDate()).
//
// This repo has no JS/TS unit-test runner (no jest/vitest, package.json's
// only scripts are dev/build/start/lint — confirmed by grep before writing
// this) and CI's "Lint" job only runs flake8 on Python (.github/workflows/
// ci.yml). This is a plain Node assertion script, not wired into any
// automated suite — run manually: `node tests/verify_scripts/
// aa345_round3_timezone_verify.mjs`. Documented as a real gap in the PR
// rather than silently skipped or papered over with a new framework as a
// side effect of a 2-line bug fix.
//
// Reproduces formatDate() verbatim (kept in sync by hand — each page's copy
// is the source of truth; this script is not imported by the app).
function formatDate(iso) {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric", month: "short", day: "numeric", timeZone: "Asia/Ho_Chi_Minh",
  });
}

function formatDateBuggy(iso, tz) {
  // The pre-fix behavior: no explicit timeZone, so the result depends on
  // whatever zone the runtime happens to be in. Simulated here via process
  // env TZ (Node respects it) rather than the removed no-timeZone call
  // directly, so this script's own result doesn't depend on ITS runtime.
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric", month: "short", day: "numeric", timeZone: tz,
  });
}

let failures = 0;
function assertEqual(actual, expected, label) {
  if (actual !== expected) {
    console.error(`FAIL: ${label} — got "${actual}", expected "${expected}"`);
    failures++;
  } else {
    console.log(`PASS: ${label} — "${actual}"`);
  }
}

// ── The exact boundary case the issue called out: a tour atomized between
// 00:00-06:59 VN time is 17:00-23:59 UTC the PREVIOUS calendar day — the
// case most likely to disagree between UTC/US-timezone rendering and the
// real VN date. ────────────────────────────────────────────────────────────
assertEqual(
  formatDate("2026-08-12T17:00:00Z"), "Aug 13, 2026",
  "00:00 VN time (17:00 UTC previous day) -> correct VN calendar day",
);
assertEqual(
  formatDate("2026-08-12T23:59:00Z"), "Aug 13, 2026",
  "06:59 VN time (23:59 UTC previous day) -> correct VN calendar day",
);
assertEqual(
  formatDate("2026-08-12T16:59:00Z"), "Aug 12, 2026",
  "23:59 VN time previous day (16:59 UTC) -> correctly stays on Aug 12, not pulled forward",
);

// ── Prove the regression is real, not hypothetical: the exact scenario
// live-reported (Nghiep saw "Aug 12" for a tour really atomized "Aug 13" VN
// time) reproduces under a plausible non-VN runtime zone (e.g. a US-hosted
// Vercel serverless region) with the OLD no-timeZone behavior, confirming
// why the explicit timeZone fix — not a coincidence of some other cause —
// is what actually matters here. ────────────────────────────────────────────
const liveTimestamp = "2026-08-13T02:41:59.329390Z"; // real tour_atoms.created_at, verified live in DB
assertEqual(
  formatDateBuggy(liveTimestamp, "America/Los_Angeles"), "Aug 12, 2026",
  "(regression proof) old no-timeZone behavior under a US runtime zone reproduces the exact live bug",
);
assertEqual(
  formatDate(liveTimestamp), "Aug 13, 2026",
  "fixed formatDate() on the same real timestamp -> correct VN date regardless of runtime zone",
);

if (failures > 0) {
  console.error(`\n${failures} assertion(s) failed.`);
  process.exit(1);
}
console.log("\nAll assertions passed.");
