# AA-450 — T9 Content Writing + T10-inline Quality Gates (build)

Follows STEP0 (`docs/claude_audit/AA-450-00-step0-t9-content-writing-investigation.md`, merged
PR #206), Phase 1's retry-loop architecture investigation
(`docs/claude_audit/AA-450-01-t9-t10-retry-loop-investigation.md`), and the T10 gate map
(`docs/claude_audit/AA-450-02-t10-gate-map.md`) — all written/confirmed before this build started,
per the build task's own explicit 2-phase gate.

## Decisions

1. **Single-endpoint architecture, confirmed by Nghiep after Phase 1, overriding Phase 1's own
   initial async-2-endpoint proposal.** `POST /v1/content-writing/requests/{id}/write` runs
   write (T9) → check (T10, 5 gates) → up to 1 rewrite with specific feedback → persist, all in
   one request/response — no background job, no separate T10 endpoint. Chosen so the tenant sees
   exactly one loading state and one final result, at the cost of a slower single request (bounded
   by `MAX_ATTEMPTS = 2`, not N7's 3-8 round range — Phase 1 §2c's real convergence data, 2.5%-
   14.6% for judge-class gates, doesn't support a wider budget for a tenant-facing request).

2. **Every blocking LLM call wrapped in `asyncio.to_thread()` from this module's first version**
   (`generate.py`, `quality_gates.py`'s 2 judge gates) — built in, not patched in after an
   incident the way N7's own AA-416 fix was. Live-verified this session: real Bedrock calls
   (write ~9-31s, judge calls) all ran successfully without needing a restart or exhibiting the
   blocking behavior N7 hit.

3. **T10 = 5 gates, not N7's full 9** (full mapping/reasoning:
   `docs/claude_audit/AA-450-02-t10-gate-map.md`). F5/F3/F4/F7 removed as genuinely inapplicable
   to T9's short single-channel content (same "no target to apply to" reasoning N7's own code
   already documents for short-form channels); F6 split (CTA-missing → immediate non-repairable
   hold, "CTA reflected in body" folded into the F9-equivalent judge's `cta_clear` field); F1/F2
   adjusted to a single-atom, no-citation-tag shape; F8's rubric table extended to cover T8's 4
   goals (SLAP/FAB/BAB/5W1H) N7's own `FRAMEWORK_RUBRICS` never covered, derived mechanically from
   `goals.py`'s own `logic` field, not guessed; F9's rubric fields reuse N7's own real facebook
   rubric (`brand_fit`/`cta_clear`/`human_read`) verbatim as the baseline across all 8 channels —
   flagged, not oversold as final, per the same "extend from real failures" discipline N7's own
   F9-social docstring documents.

4. **A REAL, previously-undocumented gap found while wiring the CTA fix (build task §3)**:
   `services/acp_planning/tenant_pool.py`... no — the real finding is in `v1_planning.py`:
   T7's own tenant-facing endpoint (`GET /v1/planning/slot-grid`) computes a `SlotGrid` and
   returns it directly in the HTTP response — it **never calls `persist_slot_grid()`**. Only
   admin-triggered paths (`admin_atoms.py`/`admin_produce.py`, via `allocate_month_from_db`)
   persist to `acp_shared.acp_v2_slots`. So `create_request()`'s new CTA lookup (joining against
   that table) will realistically find nothing for a real tenant going through the real
   self-service T7→T8 flow — **confirmed live this session**: the real live-verify run's
   `angle_gate_request.cta` was `None` both right after creation and after `choose_angle()`,
   exactly as predicted. This is flagged prominently in migration 114's own header comment and in
   `services/acp_angle_gate/service.py`'s `_fetch_slot_cta()` — not silently discovered and
   dropped.

5. **CTA fallback: T9's write endpoint asks (via an optional `cta` body field), never fabricates
   a generic per-channel CTA.** STEP0's Open Question #2 resolved this way — matches
   `SKILL_v2.md`'s own step 4 ("ask for the specific CTA") and the old, not-reused
   `acp_s4_social/brief.py::ContentBrief.validate_anchors()`'s own hard requirement. Live-
   verified: the real run's `angle_gate_request.cta` was `None`, `write_and_check(...,
   cta_override="Book a consultation with our route designers")` was called explicitly, and the
   real written piece incorporated it correctly.

6. **`content_piece` schema: `attempt_number` scoped by `angle_gate_request_id`, no
   `previous_piece_id` chain** — Phase 1's own recommendation (§3), confirmed unchanged by the
   later single-endpoint architecture decision (attempts still only ever go "forward," never
   branch — the single endpoint's own attempt-1/attempt-2 loop is exactly what `attempt_number`
   was designed to represent).

7. **Frontend: ONE continuous wizard on the EXISTING `/portal/t8-angle-gate` route — mid-build
   addendum from Nghiep, no separate `/portal/t9-write` route was ever built.** T8 and T9 remain
   2 separate backend API surfaces (unchanged) — `AngleGateTab.tsx` now chains the existing T8
   `choose()` call directly into a new `writeContent()` call the instant `status` flips to
   `'approved'`, with one loading state (`writing`) covering the whole T9+T10-inline round trip.
   Sidebar/breadcrumb label changed "Angle Gate" → "Write Content" (one nav entry for the one
   continuous flow, not two). The CTA-missing 422 case surfaces as an inline text input + retry,
   not a dead end — matches Decision 5's backend fallback design exactly.

## Changed

- **New migrations**: `api/migrations/114_angle_gate_request_cta.sql` (adds
  `angle_gate_request.cta`, nullable) + `115_acp_shared_content_piece.sql`
  (`acp_shared.content_piece`). Both **applied live** this session — see Live Verify below.
  Migration 115 was edited mid-session to add `DROP POLICY IF EXISTS` before `CREATE POLICY`
  after a real live re-run hit `DuplicateObjectError` (an SSM session dropped mid-apply; the
  re-run's `CREATE TABLE IF NOT EXISTS` no-op'd correctly but the un-guarded `CREATE POLICY`
  didn't) — the file is now safely re-runnable, matching the idempotence the rest of the file
  already had.
- **Edited**: `services/acp_angle_gate/service.py` (`_fetch_slot_cta()`, wired into
  `create_request()`; `cta` added to every read/return path) + `api/routers/v1_angle_gate.py`
  (`cta` added to the create-request HTTP response).
- **New package**: `services/acp_content_writing/` — `prompts.py`, `generate.py`,
  `framework_rubrics.py`, `quality_gates.py`, `service.py`. No import from
  `services.acp_s4_social` or `services.acp_produce` business-logic modules anywhere (ADR §0.5) —
  `services.acp_produce.judge_client`/`services.acp_produce.brand` ARE imported directly (pure
  LLM-call/DB-fetch plumbing, not N7 business logic — same distinction STEP0 already drew for why
  reusing `channel_style.py`/`goals.py` from T8 isn't a departure from "write fresh").
- **New router**: `api/routers/v1_content_writing.py` (2 endpoints, tenant-JWT-only) + registered
  in `api/main.py`.
- **New frontend**: `frontend/app/(tenant)/portal/_components/AngleGateTab.tsx` extended in place
  (write step + result display + CTA-fallback input, ~160 new lines) — no new page/route file.
  `Sidebar.tsx`/`layout.tsx` label updated.
- **New tests**: `test_aa450_content_writing_generate.py` (7), `test_aa450_quality_gates.py` (20),
  `test_aa450_content_writing_service.py` (10), `test_aa450_v1_content_writing.py` (8),
  `test_aa450_event_loop_not_blocked.py` (2, mirrors AA-416's own positive/negative-control
  shape), `test_aa450_cta_slot_lookup.py` (6) — 53 new tests, all passing. 3 pre-existing
  AA-449 tests updated for the new `cta` field/query
  (`test_aa449_angle_gate_service.py`/`test_aa449_v1_angle_gate.py`). Full suite: 1552 passed,
  1 pre-existing skip, 0 new failures. flake8 clean; `npx tsc --noEmit` + `npx eslint` clean on
  every changed frontend file (the 1 pre-existing `no-explicit-any` in `layout.tsx` confirmed
  against `origin/main` before writing this line, unrelated to this diff — same check AA-448/
  AA-449's own notes already ran for this exact file).

## Tradeoffs

- T10's 5-gate stack (vs. N7's 9) is a real, documented reduction — flagged in the gate map, not
  silently narrower. If real held-piece data later shows a pattern the removed gates would have
  caught (e.g. structural-variance-style AI-uniformity in a longer channel like `landing_page` or
  `blog`), that's a real follow-up, not something this task's own reasoning ruled out for good.
- F9's rubric fields (`brand_fit`/`cta_clear`/`human_read`) are the SAME 3 fields for all 8
  channels, not channel-bespoke — explicitly flagged in the gate map as "may need updating with
  real data," the same caveat N7's own 2-channel version of this choice carries.
- `MAX_ATTEMPTS = 2` is Phase 1's own recommendation from N7's real convergence data, not
  independently re-derived from T9-specific data (none exists yet — 0 real pieces before this
  session). Worth revisiting once real held/approved counts exist for T9.

## Should know

- **Real, load-bearing finding, not a minor caveat**: `angle_gate_request.cta` will realistically
  stay `NULL` for essentially every tenant self-service request today (Decision 4) — this is not
  a rare edge case the CTA-fallback code path handles defensively, it's the COMMON case until
  T7's tenant endpoint (or some other real source) starts persisting slots. The live-verify run
  below confirms this directly, not by inference.
- `services/acp_content_writing/quality_gates.py`'s `_JUDGE_SYSTEM_PROMPT`/gate shape closely
  mirrors `services/acp_produce/gates.py`'s F8/F9 (same isolation guarantee, same binary-1/0-plus-
  evidence contract) but imports NOTHING from that module except `judge_client.invoke_judge`/
  `parse_judge_json` (pure LLM-call plumbing) — every rubric/prompt/failure-code is T9's own,
  written fresh, per ADR §0.5.
- The live-verify run observed `JUDGE_MODEL` resolving to GPT-4.1 (`provider=openai`) for the F9
  gate rather than the Nova Pro default — this is an existing env var on the container from prior
  AA-351 trial work (`JUDGE_MODEL=gpt41`), not something this build changed or a bug in it;
  flagging so a future session doesn't mistake it for new.
- No T10 admin review-queue UI was built (out of scope, task's own explicit exclusion) — a `held`
  piece is fully visible to the tenant themselves (content + `held_reason` + full `gate_ledger` in
  the response/DB row) but has no staff-facing surface yet, same gap the task named upfront.

## Live Verify (real AWS access, `aa365-admin` session already authenticated this session)

Pre-merge — same S3-mediated ECS exec + "overwrite the changed .py files directly onto the
running `aa-cis-dev-api` container's disk" precedent AA-431/AA-448/AA-449 established (does not
restart uvicorn — the new router is NOT reachable via real HTTP pre-merge for this reason, same
documented limitation those 3 tasks' own notes already carry; verified function-level instead,
same as they did). ECS (`aa-cis-dev-cluster`/`aa-cis-dev-api`, task def `:130`) and RDS
(`aa-cis-dev-db`) both confirmed already running before starting (not started by this session).

1. **Migrations 114 + 115 applied live** — `shared.schema_versions` confirms both versions;
   `angle_gate_request.cta` column and `acp_shared.content_piece` table both confirmed present via
   live `information_schema`/`to_regclass` queries. (Migration 115 needed one fix + re-apply — see
   "Changed" above; final state confirmed clean.)
2. **Full lifecycle, real tenant (`test-n1-flow`), real atom (`atom_0e9a4a62ed`, the same real
   Southern Laos waterfall content AA-449's own live-verify used)**:
   - `create_request(atom_id, channel="linkedin")` → `status="pending_goal"`,
     **`cta=None`** — confirmed live, not simulated (Decision 4/"Should know" above).
   - `set_goal_and_generate(goal="trust_building")` → real Bedrock call (acc2→acc3 fallback,
     same documented behavior AA-449 already established) → 3 real angles.
   - `choose_angle(idx=0)` → `status="approved"`, `cta` still `None`.
   - `write_and_check(..., cta_override="Book a consultation with our route designers")` → real
     Sonnet write call (~$0.0078, ~9s) → all 6 T10 gates run
     (`F6_cta_present`/`F1_grounding`/`F2_banned_patterns`/`F4_extreme_length`/`F8_framework`/
     `F9_brand_voice`) → **all passed on attempt 1** → `status="approved"`. Real written content
     specifically and correctly referenced the atom's real facts (Tad E-Tu, Tad Fane, Tad Yuang,
     Champasak Province) — grounded, not generic.
   - Independent `fetch_piece()` call (separate from the mutating call) confirmed the DB agrees
     (`T9_REFETCH_MATCHES: True True`) — the exact AA-448-class stale-response bug class,
     confirmed NOT repeated.
   - `content_piece` row count for the request: exactly 1 (attempt_number=1, no wasted retry —
     the content passed clean on the first attempt).
3. **Cleanup**: the one `angle_gate_request` row created (cascades to its `angle_gate_option` and
   `content_piece` rows via `ON DELETE CASCADE`) deleted in the script's own `finally` block.
   Independent re-check confirmed `0` remaining `content_piece` rows for that request.
4. **Not done this session**: true end-to-end HTTP-through-API-Gateway verification (needs the
   new router registered in a running uvicorn process, i.e. a real deploy) — same documented
   limitation AA-431/AA-448/AA-449's own notes all state for this exact pre-merge situation; a
   post-merge post-deploy step for whoever merges this. The non-blocking-event-loop guarantee
   (Decision 2) was verified in the unit test suite (`test_aa450_event_loop_not_blocked.py`)
   against the real call path, not live this session — live confirms the calls succeed, the unit
   test confirms they don't block the shared event loop while doing so.

## Post-merge / post-deploy record

- **PR #207** (`feature/aa-450-build-t9-content-writing` → `main`): all 5 required CI checks
  green — merged (squash, commit `9512d8a`) on Nghiep's explicit go-ahead ("cu green thì merge").
- **Deploy Dev** (triggered by the #207 merge): green, all 4 jobs (ECR build+push, ECS deploy,
  Lambda deploy, Vercel deploy hook). New task def **`aa-cis-dev-api:131`**, service `1/1`
  running, single `PRIMARY` deployment, `rolloutState: COMPLETED`.
- **Real end-to-end HTTP verify, post-deploy** (first time these endpoints were reachable via the
  actual domain, not just the pre-merge function-level pass) — minted a real tenant JWT for
  `test-n1-flow` and called `https://api-cis.lumiguides.it.com` directly:
  - No `Authorization` header on `POST /v1/content-writing/requests/{id}/write` → **401** — auth
    boundary intact.
  - `POST /v1/angle-gate/requests` `{atom_id: atom_0e9a4a62ed, channel: linkedin}` → **200**,
    response now carries the new `cta` field (`null`) — confirms the migration-114 wiring
    deployed correctly, not just present in code.
  - `POST /v1/angle-gate/requests/{id}/goal` `{goal: trust_building}` → **200**, real Bedrock
    call, 3 real grounded angles (correctly citing only the atom's own facts — Tad E-Tu, Tad
    Fane as Champasak Province's highest waterfall, Tad Yuang).
  - `POST /v1/angle-gate/requests/{id}/choose` `{idx: 0}` → **200**, `status: approved`,
    `cta: null` — **confirms live, through the real deployed HTTP path, the exact gap Decision 4
    predicted**: a real tenant's real angle-gate request has no CTA by the time it reaches T9.
  - `POST /v1/content-writing/requests/{id}/write` `{}` (no override) → **422**, the exact
    `MissingCTAError` diagnostic message — the CTA-ask fallback (Decision 5) confirmed working
    through real HTTP, not just the pre-merge function-level pass.
  - `POST /v1/content-writing/requests/{id}/write` `{cta: "Message our route designers..."}`
    → **200** in ~15.8s (real Sonnet write + all 5 T10 gates, 2 of them real LLM-judge calls) →
    `status: approved`, all 6 gate-ledger entries `passed: true`, real content grounded in the
    atom's facts with the given CTA worked naturally into the closing paragraph — not pasted on.
  - Independent follow-up `GET /v1/content-writing/pieces/{id}` → same `status`/`content_text` —
    confirms no AA-448-class stale-response bug in real HTTP traffic, not just the mocked/
    function-level test.
  - `GET /health` immediately after the ~15.8s write call → **200**, `{"status":"ok",...}` —
    confirms the non-blocking-event-loop guarantee (Decision 2) held under a real request, not
    just the unit test's synthetic timing.
  - Cleanup: deleted the one `angle_gate_request` row this pass created (cascade removed its 3
    `angle_gate_option` rows and its 1 `content_piece` row) — independently re-confirmed `0`
    remaining rows of either kind for that request.
