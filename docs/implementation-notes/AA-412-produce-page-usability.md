# AA-412 follow-up — Trigger form Gate B hints, piece-level Gate C list, collapsed Gate Ledger

Task: `docs/claude_tasks/AA-412-03-produce-page-usability.md`. Follow-up to `docs/
implementation-notes/AA-412.md` (per-piece review + history) and `docs/implementation-notes/
AA-412-ui-readability.md` (PR #166/#167, full-screen modal + full-width history table, both live
and verified by Nghiep).

## Decisions

- **D1 — Phần 2a bug is a real DATA bug, confirmed live, fixed at the schema layer, not display.**
  `acp_deliver.packets` (migration 094) was created with `UNIQUE(tenant_id, year, week)` and no
  `month` column at all — the exact collision pattern migration 103 (AA-410) already fixed for
  `acp_shared.acp_v2_runs`/`acp_v2_slots` ("every calendar month collapses onto the SAME 4 rows"),
  just never applied to `packets`. `_get_or_create_packet()` (admin_produce.py) looks up an
  existing packet by `(tenant_id, year, week)` only, so two different months' Week-1 runs for the
  same tenant silently share one packet row and `assemble_packet()` adds both months' pieces to
  it. Verified live via ECS exec (16/08/2026): the one real `acp_deliver.packets` row
  (`6cadcbaa-ddaf-4ff4-88ef-740a06054733`, tenant `...0001`, year=2026, week=1) holds 4 pieces
  from TWO distinct runs — month=7 and month=9 — all still `review_status='pending'` (nobody had
  reviewed any of them yet, confirmed safe to repair without losing human decisions). Fix: new
  migration adds `packets.month`, changes the UNIQUE constraint to `(tenant_id, year, month,
  week)`, and — since this bug had already corrupted one live row — the migration also repairs
  existing data: a packet whose pieces span more than one month gets SPLIT into one packet per
  month (pieces moved to a newly-created sibling row for each additional month; no piece's
  `review_status`/`reviewed_by`/gate data touched).
- **D2 — Run History table needed NO fix for this bug.** Read `HistoryTab.tsx` before assuming the
  task's "apply same fix to Run History" step applied — it already renders
  `{run.year}-{month} W{run.week}` (both `RunSummary` and the `GET /produce/runs` endpoint already
  carry `month`, since that endpoint reads `acp_shared.acp_v2_runs`, already fixed by migration
  103/AA-410). Only the Gate C packets table (`page.tsx`, backed by `acp_deliver.packets`, which
  had no `month` at all) needed the fix — confirms this was a genuine data-layer gap specific to
  `packets`, not a display convention missed in two places.
- **D3 — Phần 1 (Gate B availability hints) NOT built — stopping per the task's own explicit
  instruction.** Grepped every quarter-plan query in `services/acp_planning/quarter.py` and
  `api/routers/admin.py`: every one of them (`fetch_approved_quarter_plan`, `GET .../{tenant}/
  {year}/{quarter}`, `.../history`) requires year+quarter already known by the caller.
  `GET /admin/quarter-plan/pending` spans tenants but only returns `approval_status='pending'`
  rows, the opposite of what's needed. No endpoint anywhere lists "every approved quarter plan
  for tenant X across all years/quarters" — exactly the case the task said to stop for rather than
  invent new backend logic. Needed endpoint (for Nghiep to confirm before it's built):
  - `GET /admin/quarter-plan/{tenant_id}/approved` — no year/quarter param, returns every
    `approval_status='approved'` version for that tenant: `[{year, quarter, version_id,
    approved_at}]`. Trivial to add (same JOIN `quarter_plan_version`/`quarter_plan` shape as the
    existing `/pending` endpoint, filtered by tenant_id + `approval_status='approved'` instead of
    tenant-agnostic + `'pending'`) — not added here per the task's explicit stop-and-ask instruction.
  - Frontend side (once that endpoint exists): map each approved `(year, quarter)` to its 3
    months (`Q1→1,2,3` etc.); the trigger form's Month/Week selects don't need per-week
    granularity since Gate B approval is quarter-scoped, not week-scoped — any week (1-4) within
    an approved month is eligible.
- **D4 — Phần 2 (piece-level Gate C list) needed no new backend endpoint.** `GET /packets/{id}/
  pieces` (already shipped by AA-412) already returns everything a piece-level row needs
  (`channel`, `status`, `gate_ledger`, `review_status`, ...). The piece-level table fetches this
  once per `status='ready'` packet from `GET /packets` (small N — packet count, not piece count)
  and flattens client-side, instead of adding a new batch endpoint.

- **D5 — Phần 3's focused piece (opened from Phần 2's click-through) force-expands regardless of
  gate outcome**, not just on gate failure. A reviewer who clicked a specific piece from the
  Gate C table clearly wants to look at it now — collapsing it by default (even though it passed
  every gate) would undo the "open thẳng modal đúng vị trí" point of Phần 2's click-through.
  A piece opened via the plain "Open Packet" header button (no specific piece target) still
  follows the gate-failure-only auto-expand rule from D1/Phần 3.

## Changed

- **Migration `106_acp_deliver_packets_month.sql`**: adds `acp_deliver.packets.month`, repairs
  existing data (splits any packet whose pieces span >1 month), replaces
  `UNIQUE(tenant_id, year, week)` with `UNIQUE(tenant_id, year, month, week)`. Applied live to dev
  RDS 16/08/2026 — see "Should know" below for the real before/after.
- `services/acp_produce/packets.py`: `create_packet()` signature gains a required `month` param
  (inserted between `year` and `week`, matching the DB column order).
- `api/routers/admin_produce.py`: `_get_or_create_packet()` and `_produce_slots_background()` now
  thread `month` through; `get_produce_run()`'s packet lookup, `list_pending_packets()`
  (`GET /packets`) now select/return `month`.
- Test call sites updated for the new `create_packet()` signature / packets schema:
  `tests/unit/test_aa364_packets.py`, `tests/verify_scripts/aa367_real_piece_chain.py`,
  `tests/verify_scripts/aa391_e2e_orchestrator.py`,
  `tests/integration/test_aa412_produce_history_piece_review.py`.
- `frontend/app/admin/produce/page.tsx`: `PendingPacket` gains `month`; new `slotLabel()` helper
  (always `YYYY-MM WN`, never year+week alone); Gate C section rewritten from one packet-level row
  to one PIECE-level row per `PacketPieceRow` (new type), grouped under a packet header row
  (`PacketPieceGroup` component) showing packet id/tenant/week/x-of-y-approved — the "one point
  into the packet overview" the task asked to keep. `loadPendingPackets()` now also fetches each
  ready packet's pieces (`GET /packets/{id}/pieces`, no new endpoint). Clicking a piece row opens
  `PieceReviewModal` with a new `focusPieceId` prop instead of the old bare `reviewingPacketId`.
- `frontend/app/admin/produce/PieceReviewModal.tsx`: `PieceCard` — Gate Ledger now renders
  unconditionally (was gated behind `expanded`); Content + Brand/SEO Audit stay behind `expanded`,
  now auto-expanded when the piece has any failed gate OR is the `autoFocus` target (D5). New
  `focusPieceId` prop scrolls to and highlights (red border) that piece on modal open
  (`scrolledRef` guards it to once per modal open, so a later reload from an approve/reject click
  doesn't yank scroll position back).
- Phần 1 (Gate B availability hints): **not built** — see D3.

## Tradeoffs

- D3 (Phần 1 not built) means the trigger form still can't show which tenant/year/month/week
  combos are Gate-B-approved — the original "chọn mù" complaint is unresolved until the
  `GET /admin/quarter-plan/{tenant_id}/approved` endpoint described in D3 is confirmed and added.
  The existing safety net (a clear error message on an unapproved run attempt) is unchanged and
  still the only guard today.
- D1's live repair (splitting the one corrupted packet into two) is a real data mutation, not just
  a schema change — flagging explicitly even though it was low-risk (all 4 pieces were still
  `review_status='pending'`, confirmed live before writing the migration; no packet had ever been
  advanced past `propose_only`/`ready`).
- Piece-level Gate C table does N+1 fetches (one `GET /packets/{id}/pieces` per ready packet) —
  fine at today's scale (Gate C review queue, a handful of packets at a time, not the full
  history), same shape `PieceReviewModal` already used per-packet; would need batching if the
  ready-packet count ever grows into the dozens.

## Should know

- **D1's bug was not hypothetical — live-verified via ECS exec before any code was written.**
  `SELECT ... FROM acp_deliver.packets` showed exactly ONE row
  (`6cadcbaa-ddaf-4ff4-88ef-740a06054733`, tenant `00000000-...-0001`, year=2026, week=1) while
  `acp_shared.acp_v2_runs` had 3 separate runs for that same tenant/year/week across month=7/8/9.
  Joining `pieces.run_id -> acp_v2_runs.month` confirmed the packet held 4 pieces from BOTH
  month=7 and month=9 (month=8's run produced 0 passed pieces, never got assembled in). All 4
  pieces were `review_status='pending'`. Migration 106 applied live 16/08/2026, split into
  `6cadcbaa...` (month=7, 2 pieces) + new `f9f62bac-bb25-492b-a2fe-bc31adff63ad` (month=9, 2
  pieces) — verified post-migration every piece's `packet_id` now points to a packet whose
  `month` matches its own run's `month`.
- **Run History (`HistoryTab.tsx`) needed no code change** — it already read `month` from
  `GET /produce/runs` (backed by `acp_v2_runs`, already fixed by AA-410/migration 103) and already
  rendered `YYYY-MM WN`. Confirmed by reading the file before touching anything, not assumed.
- Verification method (same constraint as `AA-412-ui-readability.md`): could not go through the
  real `aa-cis.lumiguides.it.com` login/JWT flow this session — used a temporary, **not
  committed** `frontend/app/dev-aa412c-preview/page.tsx` rendering `ProducePage` directly against
  `next build && next start` (real production build, not `next dev`), with Playwright mocking
  `/api/admin/tenants`, `/api/admin/produce/packets`, `/api/admin/produce/packets/{id}/pieces`,
  `/api/admin/produce/runs` — mock data intentionally mirrors the REAL post-migration packet
  split (`6cadcbaa...` month=7, `f9f62bac...` month=9) for authenticity. Deleted before the final
  commit — confirmed gone from `npm run build`'s route list. Screenshots in
  `docs/implementation-notes/aa-412-produce-page-usability-screens/` (not committed, same
  convention as the prior session):
  - `1_gate_c_piece_level_list.png` — Gate C table showing `2026-07 W1` and `2026-09 W1` as two
    visibly distinct packet groups, each with piece-level rows (Channel/Status/Gate/Review).
  - `2_modal_focused_passed_piece.png` — clicking a piece opens the modal scrolled to it
    (red-bordered); an all-pass sibling piece above shows Gate Ledger visible + content collapsed
    behind "Show content & brand/SEO audit".
  - `3_modal_focused_held_piece_autoexpanded.png` — a piece with a failed gate (F1_grounding)
    auto-expands content + audit without any click.
  - Confirmed programmatically (not just visually): page text contains both `2026-07 W1` and
    `2026-09 W1` (`true`/`true`); modal shows "Gate Ledger" label unconditionally; collapsed piece
    shows "Show content" link; failed-gate piece shows "Hide content" (i.e. pre-expanded) + a
    "FAIL" badge.
  - **Still open — Nghiệp's own real-browser pass** against real (not mocked) data, same as every
    prior AA-412 session's own stated limitation. Not marking Done.
- `npm run build` clean, `npx eslint` clean on every file touched in this task. Full
  `pytest tests/unit/` (1322 tests) passes. `flake8 api/ services/ shared/` (CI's actual scope,
  confirmed by reading `.github/workflows/ci.yml` — `tests/` is NOT linted in CI) is clean; a few
  pre-existing `E402`/`F541` warnings in `tests/verify_scripts/*.py` predate this task (confirmed
  via `git stash` against unmodified `main`) and are outside CI's scope regardless.
