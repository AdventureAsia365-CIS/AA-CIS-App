# AA-436 — T3 auto-pass after 2 repair rounds + badge on T4

ADR-2026-038 §0.1 (amend §10.3, 22/08/2026) reverses the 21/08 self-service-escalate
direction (AA-425's own STEP0 audit, `docs/claude_audit/AA-436-t3-ui-step0-audit.md`,
recommended building a tenant-facing T3 UI for that direction — this issue's Linear
description/title changed 22/08 before that build started, superseding STEP0's
recommendation with this one instead). Reason: a tenant editing their own copy to
clear a QA failure is bad UX, and escalate-and-stop broke the single-job
T2→T3→T5 chain AA-425 built.

## Decisions

- **Where the orchestration change actually lives**: the task prompt pointed at
  `services/acp_produce/tenant_pipeline.py` as "the point where self-repair exhausts
  2 rounds and calls `escalate_t3_failure()` then stops the chain." That's not
  accurate — `tenant_pipeline.py`'s `run_t3_qa_gate()` only *returns*
  `{"passed": False, ...}` when repairs are exhausted; it never calls
  `escalate_t3_failure()` or decides whether to stop. The actual call site (and the
  actual stop-vs-continue decision) is in `api/routers/v1_tours.py`'s
  `_do_rewrite_and_save()` closure — this matches AA-425's own decision log
  ("T3/T5 spliced in inside `_do_rewrite_and_save()`, NOT inside `run_t3_qa_gate()`
  itself"). Edited `v1_tours.py`, left `tenant_pipeline.py` untouched — matches the
  task's own instruction to leave `escalate_t3_failure()` unchanged, just corrects
  which file that unchanged function lives in vs. where the caller logic changed.
- **`qa_status` (migration 107) keeps its exact old meaning** — `'escalated'` still
  means "the QA gate did not actually clear," unchanged. `qa_auto_passed` (migration
  109, new) is a separate, independent signal: purely "did this version reach the
  pool despite `qa_status='escalated'`." Kept them separate rather than repurposing
  `qa_status` because `qa_status` is also read by the (untouched, out of scope per
  the task) N0-N6 admin `review_queue` endpoints' internal accounting — didn't want
  to risk changing its meaning under code this task wasn't asked to touch.
- **`tenant_tour_versions.status` is now purely score-based** (`ai_generated` if
  score≥7.0, else `needs_review`), same formula regardless of whether T3 actually
  passed or auto-passed. Previously `not qa["passed"]` unconditionally forced
  `needs_review` regardless of score. Removing that branch was necessary to satisfy
  the task's explicit instruction ("dùng đúng code path hiện có cho trường hợp 'pass
  thật', không tạo nhánh song song") — a auto-passed high-score tour reads
  identically to a real high-score pass from the tenant's side (`ai_generated`,
  "Ready to Review"), the badge is the only visible difference.
- **T5 atomize now always runs**, unconditionally, whether QA passed or auto-passed
  — removed the old `if/else` between `escalate_t3_failure()` and
  `run_t5_atomize()`; `escalate_t3_failure()` is now called (when QA didn't pass)
  and THEN `run_t5_atomize()` unconditionally runs after it, both in sequence, not
  as alternatives.
- **T5-failure-after-auto-pass edge case (task step 3)**: verified the existing
  handling (unchanged this session) already covers this identically for both a real
  pass and an auto-pass — `run_t5_atomize()`'s own `except` returns
  `{"status": "failed", "error": ...}` without raising, the caller only logs it
  (`tenant_atomize_done` with `t5_error`), and does not touch
  `tenant_tour_versions.status`/`qa_auto_passed` (already written by the earlier
  UPDATE). So a T5 failure after auto-pass behaves exactly like AA-425's existing
  decision (c) for a T5 failure after a real pass: the tour stays visible/usable in
  the pool, atomize retry is a separate later concern, no new logic needed. Live-
  verified indirectly — all 5 real T5 calls this session (4 auto-pass + 1 real-pass)
  returned `{"status": "success"}`, so the failure branch itself wasn't exercised
  live, but the code path is identical for both cases (same one `run_t5_atomize()`
  call, no branch on `qa_auto_passed`) so there's nothing case-specific to verify.
- **Badge label "Extra QA pass" — used as proposed, not yet confirmed with Nghiep**
  (task explicitly flagged this as unconfirmed). Chose the `info` `Badge` variant
  (`ui.tsx` — neutral blue, not `warning`/`error`) specifically to avoid reading as
  a problem, per the task's guidance to lean neutral/positive.
- **Badge placement**: next to the existing `StatusBadge` in both places
  `CatalogTab.tsx` already shows tour status — the list-item row and the detail
  panel header. Non-clickable (`Badge` renders a plain `<span>`, no `onClick`
  anywhere). Did not add it inside the detail panel body (no new section) — the
  header placement already satisfies "cạnh trạng thái tour hiện có."

## Changed

### Backend
- **New** `api/migrations/109_tenant_tour_versions_qa_auto_passed.sql` — additive,
  `gold_aa_internal.tenant_tour_versions.qa_auto_passed boolean NOT NULL DEFAULT
  false`.
- `api/routers/v1_tours.py` (`_do_rewrite_and_save()` closure inside
  `trigger_rewrite()`):
  - `new_status` computation no longer branches on `qa["passed"]` — pure
    score-based formula now (see Decisions).
  - `qa_auto_passed = not qa["passed"]` computed and written in the same UPDATE
    that already sets `qa_status`/`qa_repair_count`/`qa_checked_at`.
  - `escalate_t3_failure()` call unchanged in content, but no longer inside an
    `if/else` that skips T5 — `run_t5_atomize()` now runs unconditionally right
    after it (when QA didn't pass) or in the old `else`'s former position (when it
    did) — same one call site either way now.
  - `list_my_versions()` (`GET /v1/tours/my-versions`) SELECT list — added
    `ttv.qa_auto_passed` (was an explicit column list, not `SELECT *`).
  - `get_version()` (`GET /v1/tours/versions/{id}`) — no change needed, already
    `SELECT ttv.*, ...`, picks up the new column automatically.

### Frontend
- `frontend/app/(tenant)/portal/_components/CatalogTab.tsx`:
  - `Version` interface — added `qa_auto_passed?: boolean`.
  - New `QaAutoPassBadge()` component (reuses `Badge` from `./ui.tsx`, `variant="info"`
    — this import was already present but unused before this change).
  - Rendered next to `StatusBadge` in the list-item row and the detail panel header,
    conditionally on `v.qa_auto_passed` / `selected.qa_auto_passed`.

## Tradeoffs

- Chose a new dedicated `qa_auto_passed` column over overloading `qa_status` with a
  5th enum value (e.g. `'auto_passed'`) — keeps the QA-verdict signal (`qa_status`)
  and the tenant-visibility signal (`qa_auto_passed`) orthogonal, so a future change
  to one doesn't have to reconsider the other's meaning. Costs one extra column/one
  extra SELECT field vs. a single richer enum.
- Did not extract the `_do_rewrite_and_save()` orchestration logic into a standalone,
  independently unit-testable function — it stays an inline closure, matching the
  file's existing style (this predates AA-436). Verified instead via a direct-call
  harness that imports the real, unchanged primitives (`_rewrite_tour`,
  `run_t3_qa_gate`, `escalate_t3_failure`, `run_t5_atomize`) and replicates only the
  new orchestration snippet inline in the verify script (see Verify below) — no unit
  test added for this reason; matches the precedent AA-425 itself set for this exact
  code (verified live only, no unit tests for `tenant_pipeline.py` or the
  `_do_rewrite_and_save()` closure either).

## Should know

- **Verify approach deviated from the task's suggested method once, for safety**:
  the task implicitly expected an AA-431-style live verify (overwrite the file on
  the running ECS container's disk, run a fresh script process against it, don't
  restart uvicorn). The harness's own tooling blocked that specific action this
  session (overwriting `api/routers/v1_tours.py` on the live container) as too
  invasive to retry. Used a safer equivalent instead: called the real, *unchanged*
  primitives (`_rewrite_tour`, `run_t3_qa_gate`, `escalate_t3_failure`,
  `run_t5_atomize` — none touched by this PR) directly from a throwaway script, and
  replicated only the small new orchestration snippet (status calc + `qa_auto_passed`
  + always-call-T5) inline in that script, matching the real diff exactly. Real DB,
  real Bedrock LLM calls throughout for everything except that one small
  orchestration snippet. No file was ever written to the running container's disk.
- **FE badge screenshot is real render, mocked API response** — the live backend
  (`api-cis.lumiguides.it.com`) doesn't have this PR's `qa_auto_passed`
  column/SELECT yet (unmerged), so a real end-to-end call wouldn't have anything to
  show. Verified instead with `next build && next start` locally against the real
  compiled `CatalogTab.tsx`, a **real** tenant login (real temp tenant + real API
  key, real httpOnly cookie, real middleware gate), and only the one
  `/api/tenant/v1/tours/my-versions` response mocked (Playwright route
  interception) to inject `qa_auto_passed: true`/`false` into two synthetic rows.
  Temp tenant deleted after. Full end-to-end verification (real backend + real FE
  both serving the new field together) will only be possible after this PR merges
  and deploys — flagging so it isn't mistaken for something skipped rather than
  something not yet possible to do fully.
- **The task's file-pointer to `tenant_pipeline.py` for the orchestration decision
  was inaccurate** (see Decisions above) — corrected by editing the actual call site
  in `v1_tours.py` instead. `tenant_pipeline.py` itself is untouched, exactly as the
  task also asked.

## Verify

### Migration
Applied to real dev DB (S3-mediated ECS exec, not dry-run) — confirmed via
`information_schema.columns`: `qa_auto_passed | boolean | NO | false` on
`gold_aa_internal.tenant_tour_versions`, and a `shared.schema_versions` row for
`'109'`.

### Backend — 5 real rewrites, real Bedrock LLM, real DB (2 temp tenants, deleted after)

**Round 1** — forced auto-pass (tenant `forbidden_words=["and"]`, near-guaranteed
`FORBIDDEN_WORD` hit) vs. control on the same tour:

| Scenario | qa_passed | qa_attempts | status | qa_auto_passed | tour_atoms | review_queue |
|---|---|---|---|---|---|---|
| forced (forbidden_words=[and]) | false | 2 | ai_generated | **true** | 8 (T5 ran) | 1 row, `structural:FORBIDDEN_WORD` + `structural:META_TOO_SHORT` |
| same tour again, forbidden_words=[] | false* | 2 | ai_generated | **true** | 14 | 1 row, `META_TOO_SHORT` + `grounding:novel_numeric_claim` (unsupported "4" in subtitle) |

\* the "control" in round 1 unexpectedly also hit a real, pre-existing, unrelated QA
issue (this specific tour's rewrite genuinely tripped `META_TOO_SHORT` +grounding on
both attempts) — not a bug in this change, just an unlucky tour pick. Still useful
evidence: confirms the SAME auto-pass path handles a real/unforced failure
identically to the forced one.

**Round 2** — retried the control across 4 different published tours to get a
genuine pass:

| Attempt | Failure(s) | score | status | qa_auto_passed |
|---|---|---|---|---|
| 0 | `META_TOO_SHORT` | 9.88 | ai_generated | true |
| 1 | `MISSING_FIELD`, `ITINERARY_DAY_COUNT_MISMATCH` | 4.00 | needs_review | true |
| 2 | grounding (novel "380" in subtitle) | 10.00 | ai_generated | true |
| 3 | **none — genuine pass, 0 repairs** | 10.00 | ai_generated | **false** |

Attempt 3 confirms the control case the task asked for: a genuine first-try pass
gets `qa_status='passed'`, `qa_auto_passed=false`, no badge. Attempts 0-2 are bonus
evidence beyond what the task asked — 3 more real, independently-occurring failure
types (not the engineered one), all correctly auto-passed with atoms generated and
`review_queue` rows written, and attempt 1 additionally confirms `status` still
correctly reflects a genuinely low score (`needs_review`) even when
`qa_auto_passed=true` — i.e. the two signals are independent, as designed.

All 5 test `tenant_tour_versions`/`review_queue`/`tour_atoms` rows, both temp
tenants (+ their brand_rules/tenant_api_usage rows), deleted after. Confirmed clean:
`0` leftover AA-436 tenants, `0` leftover AA-436 brand_rules rows, `0`
`qa_auto_passed=true` rows remaining in the DB post-cleanup.

### Frontend
- `npx tsc --noEmit` — 0 errors.
- `eslint` on `CatalogTab.tsx` — compared directly against `origin/main`'s version:
  baseline had 21 problems (5 errors, 16 warnings); this change has 20 (5 errors, 15
  warnings) — **one fewer warning** (the previously-unused `Badge` import is now
  used), zero new findings.
- `npm run build` — clean, route list unchanged (this task doesn't add/remove
  routes).
- `.venv/bin/python -m flake8 api/routers/v1_tours.py` — 0 findings.
- `.venv/bin/python -m pytest tests/unit -q` — 1359 passed, 0 failed (full existing
  suite, confirms no regression; no new unit test added for the reason in
  Tradeoffs above).
- Screenshots (real browser, real login, real compiled `CatalogTab.tsx`, mocked
  `/my-versions` response only — see Should know): list view shows "Ready to
  Review" + a blue "EXTRA QA PASS" badge on the auto-passed row only, no badge on
  the real-pass row; detail panel header shows the same badge next to the status
  badge, non-clickable, doesn't cover any other header content.
