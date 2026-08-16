# AA-412 follow-up (round 4) — /admin/produce full-width layout + modal-covers-sidebar + copy trim

Task: `docs/claude_tasks/AA-412-04-produce-page-layout-fixes.md`. Follow-up to PR #168 (packet
month-collision fix, piece-level Gate C list, collapsed gate ledger — merged/deployed, verified
live). This round fixes layout bugs that survived that PR: page-level width cap, a modal covering
the sidebar, and a Run History overlap bug — all confirmed via real screenshots at three
breakpoints inside the actual admin layout (sidebar + content), not an isolated component render.

## Decisions

- **D1 — root cause of "not full width" was one line: `page.tsx`'s content wrapper had
  `maxWidth: 1100`.** Every section of the page (trigger form, Gate C table, Run History) lives
  inside that one wrapper, so a single cap explained the whole-page symptom. Checked other
  `/admin/*` pages first: `dashboard/page.tsx` and `tenants/page.tsx` use a plain
  `flex: 1` content column with **no** page-level max-width; `quarter-plan/page.tsx` has the same
  `maxWidth: 1100` (likely copied from/to `produce/page.tsx` at some point) but is out of this
  task's scope, left untouched. Removed the cap on `produce/page.tsx` to match the
  dashboard/tenants pattern — the only pages that don't share this bug.
- **D2 — `minWidth: 0` added to the same wrapper is not cosmetic, it's the actual mechanism behind
  the Run History overlap bug.** A flex item's default `min-width: auto` refuses to shrink below
  its content's intrinsic width. `HistoryTab`'s table sits inside that flex-1 wrapper; without
  `minWidth: 0` the flex item (and everything in it) can be forced wider than the viewport by wide
  table content instead of respecting the available space — `dashboard/page.tsx`/`tenants.tsx`
  both already set this on their own flex-1 wrapper, `produce/page.tsx` never did.
- **D3 — the actual overlap mechanism (once width is respected) is `overflow: visible` as the CSS
  default on table cells.** `AA-412-ui-readability.md`'s D4 already got the colgroup percentage
  math right (verified again this round — always sums to 100%), so `table-layout: fixed` was never
  the bug. The bug: a `<td>`'s box width IS rigid under `table-layout: fixed` regardless of
  content, but CSS table cells don't clip overflowing content by default — a `Badge` (fixed
  padding, `inline-flex`, no `white-space`) or an unwrapped string wider than its column's % share
  doesn't wrap into a taller row, it bleeds sideways past the cell boundary and paints over the
  next column. Fix: `overflow: hidden` (+ `text-overflow: ellipsis`, `white-space: nowrap`) added
  as the BASE style for every `gateTd`/`gateTh` cell in `HistoryTab.tsx`. Cells that are supposed
  to wrap (Held Reason, Gate Detail in the drill-down) already override `whiteSpace: "normal"` and
  are unaffected. This is a strictly safer default than the previous session's isolated-component
  verification could have caught — that check rendered `HistoryTab` standalone, never inside the
  real sidebar+flex layout where the width constraint that triggers this actually exists.
- **D4 — modal fix: change the overlay's `left` offset, not its render location.** The modal was
  never a React portal — it already renders as a normal DOM descendant inside `ProducePage`'s own
  content wrapper. The ONLY reason it covered the sidebar was `position: fixed; inset: 0`, which
  positions relative to the *viewport* regardless of DOM nesting — `AdminSidebar` itself is a
  plain `position: sticky` flex child (never `position: fixed`), so nothing in the page's own
  layout stops a `fixed; inset: 0` element from painting over it. Fix: `left: SIDEBAR_WIDTH`
  instead of `left: 0` (kept `top/right/bottom: 0`). No portal needed, no `getBoundingClientRect`
  measurement needed — the sidebar's width is a static, known constant.
- **D5 — added `SIDEBAR_WIDTH` as a shared constant in `adminUi.tsx`** rather than duplicating the
  literal `220` in the modal. `AdminSidebar.tsx` itself now imports and uses it too (was a bare
  `width: 220` inline) — single source of truth, so a future sidebar-width change can't silently
  desync the modal offset again.
- **D6 — copy trim: kept exactly the two ideas the task asked for, dropped the parenthetical
  `(AA-410)`.** New text: "Requires an approved Quarter Plan (Gate B) for the tenant. Week =
  1st–4th week of the selected month, not an ISO week." — used the task's own suggested wording
  verbatim, no reason to deviate.
- **D7 — verification uses the real `AdminSidebar` + `ProducePage` together** (via a temporary,
  not-committed `frontend/app/dev-aa412d-preview/page.tsx` that renders `ProducePage` directly,
  same constraint as every prior AA-412 session — no live JWT minted this session), unlike the
  previous round's isolated-component check. This is precisely what let this round catch the
  overlap bug the previous round's own verification missed (see D3).

## Changed

- `frontend/app/admin/_components/adminUi.tsx`: new `SIDEBAR_WIDTH = 220` export.
- `frontend/app/admin/_components/AdminSidebar.tsx`: `width: 220` → `width: SIDEBAR_WIDTH`.
- `frontend/app/admin/produce/page.tsx`: content wrapper `maxWidth: 1100` removed, `minWidth: 0`
  added (D1/D2); trigger-form helper copy trimmed (D6).
- `frontend/app/admin/produce/PieceReviewModal.tsx`: overlay `inset: 0` → `top: 0; left:
  SIDEBAR_WIDTH; right: 0; bottom: 0` (D4/D5). No change to anything inside the dialog — sticky
  header/footer/per-piece action (PR #166) and unconditional Gate Ledger + collapsed content/audit
  (PR #168) are untouched.
- `frontend/app/admin/produce/HistoryTab.tsx`: `gateTd`/`gateTh` base styles gain `overflow:
  hidden` (+ ellipsis/nowrap on `gateTd`) (D3).

## Tradeoffs

- None of these fixes touch API calls, request/response shapes, or business logic — pure
  layout/CSS, matching the task's own scope.
- D3's clip-on-overflow is a deliberate downgrade from "always show full text" to "show full text
  when there's room, clip gracefully when there isn't" — the task explicitly said this tradeoff
  (local scroll/clip) beats overlap, and confirmed via screenshot that nothing clips at 1920x1080
  or 1440x900 with real data; only 1280x800 with an intentionally long tenant name clips anything.

## Should know

- **Verification ran inside the real admin layout this time (D7)**, not an isolated component —
  same temporary/not-committed preview-page pattern as prior sessions, deleted before the final
  commit (confirmed gone from `npm run build`'s route list below).
- Playwright against a real `next build && next start` production server (port 3011, not
  `next dev`), at all three required viewports (1920×1080, 1440×900, 1280×800). For each viewport,
  captured: (1) the page overall, (2) the modal open, (3) Run History, (4) Run History with a row
  expanded (drill-down table) — 12 screenshots total in
  `docs/implementation-notes/aa-412-produce-page-layout-fixes-screens/`.
- **Programmatic checks (not just visual), all three viewports, all passed:**
  - `document.documentElement.scrollWidth <= clientWidth` (no page-level horizontal scroll): true
    at 1920×1080, 1440×900, 1280×800.
  - Sidebar (`<aside>`) `isVisible()`: true at every viewport, BOTH before and while the modal is
    open.
  - Modal's bounding box `x` == sidebar's bounding box `x + width` (220) at every viewport — the
    modal starts exactly at the sidebar's right edge, never before it.
  - `document.elementFromPoint()` on the "Dashboard" sidebar nav item while the modal is open
    returns the nav item itself (not the modal's overlay) at every viewport — confirms the sidebar
    is not just visually present but actually clickable/not covered by the overlay's hit-testing
    area.
  - Cell-overlap check (compare every adjacent `<td>` pair's `getBoundingClientRect()` — first data
    row of the Run History table AND the expanded drill-down table): `NO OVERLAP` at every
    viewport, both tables.
  - Mock data was deliberately adversarial: a long tenant name ("Horizon Voyages White-Label B2B
    Partner Co.") and a wider-than-usual status word ("PRODUCING") specifically to stress-test the
    columns most likely to overflow, not just the easy case.
- Full verification data/screenshots:
  - `{viewport}_1_page_overall.png` — Trigger & Gate C tab, full page.
  - `{viewport}_2_modal_open.png` — Review Packet Pieces modal open, sidebar visible alongside it.
  - `{viewport}_3_run_history.png` — Run History tab, collapsed rows.
  - `{viewport}_4_run_history_expanded.png` — Run History with one row's gate-ledger drill-down
    open.
  - `1280x800_4_run_history_expanded.png` is the clearest evidence shot: long tenant name and long
    status word both clip cleanly with an ellipsis/cutoff instead of bleeding into the next column,
    and the table's own local horizontal scroll (not a page-level one) handles the last gate column
    running past the visible edge at this narrowest width.
- `npm run build` clean; `npx eslint` clean on every file touched in this task (one pre-existing,
  unrelated `react-hooks/set-state-in-effect` warning in `AdminSidebar.tsx:86` — confirmed via
  `git stash` against unmodified `main` that it predates this task, not touched by this diff).
- No Python/backend files changed this round — `pytest`/`flake8` re-run only as a sanity check,
  unaffected.

## PR / merge / deploy

(filled in after PR is opened)
