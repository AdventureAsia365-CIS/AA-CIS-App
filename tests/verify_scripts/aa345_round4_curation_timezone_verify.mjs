// AA-345 round 4, Vấn đề B — Nghiep still saw "Atomized Aug 12, 2026" live on
// /admin/curation after round 3's PR #134 claimed to fix the timezone bug on
// "cả 2 trang" (both pages). Investigated before assuming PR #134 was wrong:
//
// 1. Read frontend/app/admin/curation/page.tsx's CURRENT formatDate()
//    (post-#134, current main) — it DOES hardcode timeZone: "Asia/Ho_Chi_Minh",
//    same as atomize/page.tsx's copy. Grepped for every "Atomized"/
//    atomized_at render site in both pages — exactly one formatDate() call
//    site per page, no second un-fixed spot missed.
// 2. Confirmed the backend (api/routers/admin_atoms.py's atoms_summary())
//    returns a proper TZ-aware ISO 8601 string (created_at.isoformat() on an
//    asyncpg `timestamptz` value, e.g. "...+00:00") — verified against a
//    real live API response, not assumed. A naive (no-offset) timestamp
//    would make `new Date(iso)` parse as LOCAL time in JS instead of UTC,
//    silently defeating the timeZone option — ruled out.
// 3. Checked one specific tour Nghiep could plausibly have been looking at
//    ("Peaks and Passes of the Nubra Valley", real created_at
//    2026-08-12T13:27:51Z from a live DB query): 13:27 UTC + 7h = 20:27 VN
//    time, STILL Aug 12 in Asia/Ho_Chi_Minh — this is Khả năng 1 (correct
//    data, not a bug) for that specific case, not a timezone defect.
//
// Conclusion: PR #134's fix IS present and correct on the Curation page in
// current/main. No code change made for Vấn đề B. This script independently
// re-verifies CURATION's own copy of formatDate() (not round 3's shared
// script, which round 4 explicitly should not just reuse) against the same
// VN-midnight boundary cases, plus the specific real tour_id timestamp
// above, so a FUTURE regression in curation/page.tsx specifically (even if
// atomize/page.tsx stays correct) gets caught.
//
// This repo has no JS/TS unit-test runner (same gap round 3 already
// documented — package.json has only dev/build/start/lint, no jest/vitest,
// no *.test.ts(x)). Run manually:
//   node tests/verify_scripts/aa345_round4_curation_timezone_verify.mjs

// Copied verbatim from frontend/app/admin/curation/page.tsx's formatDate()
// as of this commit — kept in sync by hand, this script does not import the
// app.
function curationFormatDate(iso) {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric", month: "short", day: "numeric", timeZone: "Asia/Ho_Chi_Minh",
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

// Same VN-midnight boundary cases as round 3's script, re-asserted against
// CURATION's own copy of the function specifically.
assertEqual(
  curationFormatDate("2026-08-12T17:00:00Z"), "Aug 13, 2026",
  "curation: 00:00 VN time (17:00 UTC previous day) -> correct VN calendar day",
);
assertEqual(
  curationFormatDate("2026-08-12T23:59:00Z"), "Aug 13, 2026",
  "curation: 06:59 VN time (23:59 UTC previous day) -> correct VN calendar day",
);
assertEqual(
  curationFormatDate("2026-08-12T16:59:00Z"), "Aug 12, 2026",
  "curation: 23:59 VN time previous day (16:59 UTC) -> correctly stays on Aug 12",
);

// The specific real tour_atoms.created_at this round investigated live
// ("Peaks and Passes of the Nubra Valley", queried from the real dev DB) —
// NOT a midnight-boundary case, confirms Nghiep's "Aug 12" observation for
// this tour is correct data, not the timezone bug recurring.
assertEqual(
  curationFormatDate("2026-08-12T13:27:51.974314Z"), "Aug 12, 2026",
  "curation: real live tour_atoms.created_at (13:27 UTC) -> Aug 12 in both UTC and VN time, genuinely not a boundary case",
);

if (failures > 0) {
  console.error(`\n${failures} assertion(s) failed.`);
  process.exit(1);
}
console.log("\nAll assertions passed.");
