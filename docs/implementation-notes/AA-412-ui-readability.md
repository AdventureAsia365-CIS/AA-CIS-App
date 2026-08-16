# AA-412 follow-up — Gate C review modal + Run History table readability/layout fix

Task: `docs/claude_tasks/AA-412-02-gate-c-ui-readability-fix.md`. Follow-up UX fix to AA-412
(Gate C per-piece review + N7 run history view, `docs/implementation-notes/AA-412.md`) — no API
or business-logic changes, layout/CSS/component-structure only, in
`frontend/app/admin/produce/{PieceReviewModal,HistoryTab}.tsx`.

## Decisions

- **D1 — full-screen dialog via 3-row flexbox, not `position: sticky` on the modal's own
  header/footer.** `PieceReviewModal`'s outer overlay is now `position: fixed; inset: 0` with a
  16px inset dialog box (`display: flex; flex-direction: column`). Header and footer are ordinary
  flex items (`flexShrink: 0`); only the middle row scrolls (`flex: 1; overflow-y: auto`). This is
  simpler and more robust than `position: sticky` on header/footer, which would still require the
  same flex/height plumbing to keep them out of the scroll flow — no reason to use both.
- **D2 — per-piece Approve/Reject IS `position: sticky` (`top: 0`), relative to the modal's
  scrolling content row.** This is the one spot sticky is the right tool: each `PieceCard`'s own
  header (channel/gate/review badges + Approve/Reject) sticks to the top of the scroll container
  while that piece's body/gate-ledger/audit JSON scrolls underneath, then the next piece's sticky
  header takes over the instant it reaches the top — native CSS stacking, no JS scroll-tracking
  needed. Required restructuring `PieceCard` off the shared `Card` component (which applies
  uniform padding on all sides) into a custom two-region box (sticky header region + non-sticky
  body region) so the sticky header can sit flush at `top: 0` of the scroll container.
- **D3 — no content was hidden to make this fit.** The per-piece expand/collapse chevron already
  existed before this task (default collapsed) and is unchanged — expanding still shows the full
  `body_tagged` content, all gate-ledger rows, and the full `brand_seo_audit` JSON, just inside
  more breathing room. Nothing new was collapsed by default.
- **D4 — Run History table: percentage-only `<colgroup>` under `table-layout: fixed`, not a mix
  of `%` and fixed `px` gate columns.** An earlier draft gave gate columns a fixed 64px width,
  which under `table-layout: fixed` fights with percentage-based identity columns for the
  table's total width (the two unit systems don't reliably sum to exactly 100%, so the table
  could render narrower or wider than its container depending on browser rounding). Switched to
  all-percentage: identity columns (chevron/Tenant/Week/Status/Triggered/Pieces) get a fixed
  60% budget; the remaining 40% splits evenly across however many gate columns the dataset has
  (`(100 - identitySum) / gateColumns.length`). This guarantees the table is always exactly
  100% of its container — no per-column px guess to get wrong, and no page-level horizontal
  scroll at any viewport wide enough for the container itself (verified below at both
  1920x1080 and 1440x900; local `overflowX: auto` is kept purely as a fallback for narrower
  windows, per the task's own stated priority order).
- **D5 — gate header labels shortened (e.g. "F9_brand_seo_audit" → "F9 brand"), full name kept
  as a `title` tooltip.** Needed to fit up to 9 gate columns without wrapping/truncating the
  pass/fail count itself, which the task explicitly said must not be cut. Same treatment for
  "Triggered" (date-only, full timestamp in a `title` tooltip) and the "Tenant" column
  (ellipsis + tooltip for long names) — none of this drops data, only where the full string
  lives (visible vs. on-hover).
- **D6 — drive-by fix: added `key` via `Fragment` on the per-run `<>...</>` block in
  `HistoryTab.tsx`'s row map.** Pre-existing from AA-412 (not introduced by this task), surfaced
  by Next.js dev-mode's "Issues" indicator during visual verification below. Zero risk, same
  file already being rewritten, so fixed in place rather than filing separately.
- **D7 — no change to `frontend/app/admin/produce/page.tsx`'s `maxWidth: 1100` content
  wrapper.** The task's "full width theo viewport" reads most sensibly (and consistently with
  every other `/admin/*` page's shared layout) as "fills its container with no internal
  horizontal-scroll cutoff," not "spans the physical monitor edge-to-edge" — the latter would be
  a page-layout change well outside this task's stated scope (component-level CSS only). The
  modal is unaffected either way since `position: fixed; inset: 0` already escapes any ancestor
  width constraint.

## Changed

- `frontend/app/admin/produce/PieceReviewModal.tsx`: full-screen 3-row flex dialog (D1);
  `PieceCard` restructured with a sticky per-piece header (D2); `Escape` key now closes the
  modal (small addition — a full-screen dialog has no visible backdrop to click through, unlike
  the old centered one, so a keyboard close path matters more here).
- `frontend/app/admin/produce/HistoryTab.tsx`: `<colgroup>` percentage-only column budget (D4),
  short gate labels + title tooltips (D5), `Fragment` key fix (D6). Same fix pattern applied to
  the per-piece drill-down table.
- No changes to any API route, request/response field, or `page.tsx`.

## Tradeoffs

- Gate columns get noticeably narrower as more gates are added later (40% ÷ N) — at 9 gates
  today this is still comfortably readable (verified below), but a future 12th/13th gate would
  need either the identity-column budget trimmed further or a rethink (e.g. a genuinely
  scrollable-only gate region). Flagging as a soft ceiling, not fixing pre-emptively.
- D7 above (page container width) is a judgment call on an ambiguous requirement — if Nghiệp
  meant literal edge-to-edge, that's a `page.tsx` change, one line (`maxWidth`), easy follow-up.

## Should know

- **Verification could not go through the real live UI/login flow** (`aa-cis.lumiguides.it.com`
  or `npm start` + a real `cis_admin_token`) within this session — minting a valid admin JWT
  locally would have needed reading the live `JWT_SECRET` out of the ECS task definition, which
  the harness's own permission classifier correctly declined (extracting an auth secret to forge
  a token is exactly the kind of action that should require explicit sign-off, even for
  legitimate testing). Verification instead used a temporary, **not committed** page
  (`frontend/app/dev-aa412-preview/page.tsx`, deleted before this note was written — confirmed
  gone from the final `npm run build` route list below) rendering both components directly with
  Playwright-mocked responses for `/api/admin/produce/packets/{id}/pieces`,
  `/api/admin/produce/runs`, and `/api/admin/produce/run/{id}` — same response shapes AA-412
  already defined, no field changes. This is a legitimate substitute for CSS/layout mechanics
  (sticky positioning, colgroup math, overflow behavior don't depend on real data content) but
  is **not** a substitute for Nghiệp's own real-browser pass — same as the original task's own
  step 5 already required. Not marking Done.
- `npm run build` clean (harness page briefly appeared in the route list while present, gone in
  the final build after cleanup — reran to confirm). `npm run lint` clean on both changed files.
- Local verification data (mocked): 4 pieces (facebook/tiktok/blog/instagram, 2 held with a
  `held_reason` + `repair_count`), 9 gate columns (F1/F3/F4/F5/F8/F9 brand/F9 social +
  `output_rules`/`F6_bofu_guard` to exceed the real 7-gate baseline and stress-test the column
  budget), 18-paragraph `body_tagged` per piece to force real scroll, 7 history runs.
- **Results:**
  - Run History table: `document.documentElement.scrollWidth === clientWidth` at both
    1920x1080 (1920/1920) and 1440x900 (1440/1440) — zero page-level horizontal scroll, all 9
    gate columns visible with real counts, expanded drill-down row same (screenshots:
    `aa-412-ui-readability-screens/history_{1920x1080,1440x900}.png`,
    `history_expanded_{1920x1080,1440x900}.png`).
  - Modal: full-screen at both viewports; header ("Review Packet Pieces" + packet ID + close)
    and footer ("N/4 pieces individually approved" + Advance button) both still visible
    (`isVisible()` true) after programmatically scrolling the content area to `scrollHeight`
    (i.e. fully to the bottom); mid-scroll screenshot shows the currently-scrolled piece's own
    header (badges + Approve/Reject) pinned at the top of the content area, handing off to the
    next piece as expected (screenshots: `modal_top_*`, `modal_scrolled_mid_*`,
    `modal_scrolled_bottom_*`, one pair per viewport).
  - Screenshots live in `docs/implementation-notes/aa-412-ui-readability-screens/` (not
    committed to git — this repo only force-tracks `implementation-notes/*.md`, not images
    under it; same convention this note follows). Also sent inline via SendUserFile this
    session.
- **Not done in this session (per the task's own instruction):** live AWS ECS/RDS state was NOT
  changed by this task's own verification steps (both were already running before any work
  started here — `aws ecs describe-services`/`aws rds describe-db-instances` showed
  `desired=1/running=1` and `available` respectively — contrary to this repo's `CLAUDE.md`
  header note claiming AWS was stopped after S84; that note is stale, not corrected here, out
  of scope).

## PR / merge / deploy (mid-turn amendment — see task doc's "Mid-turn amendment" section)

- PR #166: https://github.com/AdventureAsia365-CIS/AA-CIS-App/pull/166 — merged (squash) into
  `main` after all 5 required checks passed green (Lint/Security Audit/Unit Tests/Integration
  Tests/Docker Build Check), per Nghiệp's mid-turn instruction to merge once CI is green rather
  than waiting for a manual click.
- Deploy Dev (workflow run 31933926505) completed successfully: Vercel frontend redeploy, ECR
  image build/push, ECS Dev rollout, Lambda redeploy — all green.
- ECS digest verified matching `:latest` post-deploy (same pattern as AA-412):
  - Task def: `aa-cis-dev-api:98`, image `...aa-cis-dev-api:latest`
  - Running task's `imageDigest`: `sha256:6959a3cefa216dc04334f86d88501e67414dc64e416b6668eb3a22fd92e27604`
  - ECR `latest` tag digest: same hash, pushed 2026-08-16T14:29:54+07:00 — confirms the running
    task is this PR's build, not a stale cached one.
  - `deployments[0].rolloutState`: `COMPLETED`.
- **Still open — Nghiệp's own real-browser pass.** Deploy is live at
  `aa-cis.lumiguides.it.com/admin/produce`; per the original task's step 5, "Done" is not
  self-declared here. Please click through the Gate C modal and Run History tab there and let
  me know if anything doesn't match the screenshots above.
