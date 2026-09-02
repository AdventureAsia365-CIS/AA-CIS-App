# AA-512 STEP0 — investigation record (2026-09-02)

## §1. `create_request()` real current state — Linear description is stale

Linear's AA-512 description assumes ONE `create_request()` that needs `subject_id` added. Live
code (`services/acp_angle_gate/service.py`) shows the picture is more advanced than that:

- **AA-511 (Slate, PR #273/#274, merged, migration 133+134) already built a SECOND, parallel entry
  point**: `services/acp_shared/slate.py::pick_subject()`. It flips a Subject `proposed->picked`
  and inserts `angle_gate_request` directly with `channel` copied from `subject.channel` — exactly
  the "channel already fixed from Subject" behaviour AA-512 asks for. Wired to
  `POST /v1/planning/subjects/{subject_id}/pick` (`api/routers/v1_planning.py`).
- The OLD `create_request()` (AA-449, atom-picker, no subject, channel starts NULL, needs a later
  `set_channel()` call = step 8) is **explicitly, deliberately kept unchanged** — migration 133's
  own header: *"the pre-existing admin/tenant atom-picker entry point ... is NOT being retired by
  this build"* — i.e. AA-511 anticipated a later build (this one) would be the one to actually
  retire it.
- **Confirmed by grep, the atom-picker UI path is already dead in practice**: `SlotPickerPanel.tsx`
  (the only file that ever navigates to `/portal/t8-angle-gate?atom_id=...`, i.e. triggers
  `create_request()`) is imported nowhere except by itself/AngleGateTab's type defs — `PlanningTab.tsx`
  (T7's real tenant page) explicitly says: *"AA-511 — the Slate replaces SlotPickerPanel.tsx (Weekly
  Slots) on this render path. The old component/file is deliberately left in place, unused, per the
  epic's own 'giữ code cũ, chỉ ngưng dùng, không xoá' rule."* `SlateTab.tsx` is the only live caller
  into T8 today, via `resume_request_id` (not `atom_id`).
- **`AngleGateTab.tsx`'s `choose()` already conditionally skips the Channel step** when
  `d.channel` is already truthy after choosing an angle (line ~419): `if (d.status === "approved"
  && d.channel) writeContent(d.request_id)` — i.e. a Subject-driven request (channel non-NULL from
  creation) already never shows the Channel card in the live UI. The Channel-card code
  (`submitChannel()`, step 4 UI) only ever fires for a legacy atom-picker request, which is
  unreachable from any live link today.

**Decision (not a stop-worthy contradiction — resolved by evidence, not guessed):** this is a
deliberate two-phase rollout already visible in the repo's own comments, not an accidental gap.
AA-512's real remaining scope, given AA-511 already shipped the Subject-driven skip-channel path:
- Do **not** delete/retire `create_request()`/`set_channel()`/the Channel-picker UI code — keep
  following the epic's own "keep old code, stop using it, don't delete" convention (same one
  `PlanningTab.tsx` already documents for `SlotPickerPanel.tsx`). No migration needed for
  `subject_id` either — already added by migration 133.
- The one thing genuinely NOT built yet by AA-511: **measurable angle ranking** (ADR 0004).
  `generate_angles()` still returns an LLM-chosen `recommended_index` (opinion, not counted).
  This is AA-512's real, remaining, unbuilt scope.

## §2. ADR 0004 (Ms. Thư repo) — exact formula, read verbatim

`docs/AI-gent-for automation works/aa-soscial-media-main/docs/adr/0004-...md`: *"Angles are
ranked by measurable criteria — Atom Score, how many People Also Ask questions the angle answers,
and channel avoid-list violations — not by LLM opinion."*

Ported reference implementation, `src/aa_social/angles.py`:
- LLM proposes 3 angles, each claims `answers: list[str]` (quoted PAA questions it believes it
  answers) and `walks: bool` (only meaningful when a journey/Route was supplied).
- `rank()` **re-verifies** the model's claims — never trusts them: `_plain()`-normalizes (lowercase,
  strip non-alnum, collapse whitespace) both the model's claimed answer and the Subject's real
  harvested PAA pool; only a claim that normalizes to a real question counts.
- `violations` = each channel/brand avoid-list phrase, compiled as `\b<escaped phrase>\b`
  (word-boundary, case-insensitive), matched against `f"{headline} {about}"`.
- **Sort key** (best/lowest first): `(len(violations), -len(answers), 0 if walks else 1)` — i.e.
  violations dominate, then answer-count, then walk-completeness as a tiebreaker only.
- **"Atom Score" is NOT actually in this per-angle sort tuple.** It's constant across all 3 angles
  of the same Subject (it decided which Subject got proposed/picked via the Slate — AA-511's own
  job), so it cannot differentiate 3 angles of the SAME subject. Confirmed by reading the actual
  ranking code, not just the ADR's summary prose.

**Decision**: port `rank()`'s real 2-axis tie-break exactly (violations, then answers) for ordering
the 3 angles against each other. Show Segment/Route Score (`subject.score`) in the fixed header
next to Subject+Channel (constant context, not a differentiator) rather than folding a constant
into a 3-way sort — this satisfies AA-512's literal ask ("3 Angle rank bằng: Segment/Route Score +
PAA + avoid-list") by displaying all 3 numbers, while the actual ORDER between the 3 cards is
driven by the 2 that vary. Not building "walks" — AA-512's own text lists only 3 axes (no walks),
and T8 angle-generation still only sees ONE representative atom's text today (Route-aware context
is AA-513's job, not built yet) — nothing to check "walks the whole journey" against yet.

**Second structural difference confirmed**: Ms. Thư's `ChannelSpec.avoid` is `list[str]` (already
split, individual short phrases). AA-CIS's own `channel_style.py::CHANNEL_STYLES[...]["avoid"]` is
ONE free-text comma-joined Vietnamese string (e.g. `"emoji nhiều, travel copy chung chung, hard
sell, ..."`). Adapting: split AA-CIS's string on `,` and strip, to get an equivalent phrase list —
this only adapts the DATA SHAPE the same algorithm reads from, not the algorithm itself.

**Scope narrowing vs. the reference** (deliberate, matches AA-512's own literal text): Ms. Thư's
`Rules.load()` folds in BOTH the channel's own avoid-list AND the brand's own banned phrases.
AA-512's text says only *"số vi phạm avoid-list của Channel"* — channel-only. Not folding in
brand-wide banned phrases here (that's a separate, cross-cutting config this ticket doesn't own) —
flagged as a real, intentional narrowing, not an oversight.

**Real structural reason the legacy atom-picker path CANNOT get measurable ranking (confirms §1's
decision, not just convention):** avoid-list violations are channel-scoped — computing them
requires a real, known channel. In `create_request()`'s flow, channel is unknown until AFTER the
angle is already chosen (step 8). Measurable ranking is therefore only computable when channel is
known AT GENERATION time — true for every Subject-driven request (channel fixed at creation),
never true for the legacy atom-picker path. `generate_angles()`/ranking falls back to the existing
LLM-`recommended_index` behaviour when `channel` is still NULL (backward-compatible, no regression
on the dead-but-present legacy path).

## §3. `tenant_pool.py` / `v1_publish.py` — already correct, no fix needed

Both already read `COALESCE(cp.channel, agr.channel)` (content_piece's own denormalized channel
first, falling back to the request's), a fix AA-469 Việc 4 Pass 2 already made generically — it
doesn't care WHEN or via which code path (`set_channel()` at step 8, or `pick_subject()` at
creation) `agr.channel` got set. Confirmed by reading both files: no assumption anywhere that
channel is set at a specific step. **No code change needed here** — STEP0 confirms Linear's
worry (Việc 4 Pass 2 might have missed the new order) does not apply; already generalized.

## §4. `content_piece` (migration 124) — role confirmed correct, no change needed

`content_piece.channel`/`angle_gate_option_id` were added by migration 124 but explicitly NOT
populated by app code as of that migration. A LATER session (AA-469 Việc 4, per `tenant_pool.py`'s
own comment) DID wire population into `_insert_placeholder_piece()` — confirmed live in current
code, not stale. Both columns still play exactly the role migration 124 designed them for. No
migration, no code change needed for this point.

## §5. `subject` schema (AA-511, migration 133) — confirmed

`acp_shared.subject.channel` (`TEXT NOT NULL`) exists and is the copy source `pick_subject()`
already uses. `angle_gate_request.subject_id` (migration 133) and `.route_segment_ids` (migration
134) both already exist. **No new migration needed for AA-512** — confirmed by reading the
migrations directory (latest is 134) and the live column list in `fetch_request()`'s own SELECT.

## Net STEP0 conclusion — real remaining build scope for AA-512

1. No new migration for `subject_id`/`channel` copy (already shipped by AA-511). **One small new
   migration IS needed**: `angle_gate_option` gains `answers`/`violations` (jsonb arrays) to
   persist the measurable-ranking evidence per angle, for the API/frontend to read back.
2. `services/acp_angle_gate/ranking.py` (new) — port `angles.py::rank()`'s real 2-axis sort
   (violations, then answers), scoped to channel avoid-list only (not brand-wide).
3. `generate.py`/`prompts.py` — LLM must additionally claim `answers: list[str]` per angle (server
   re-verifies against the real PAA pool, per ADR 0004 — never trusts the claim).
4. `service.py::set_goal_and_generate()` — when `channel` is already known (Subject-driven),
   compute+persist measurable ranking + overwrite `recommended`; when NULL (legacy atom-picker),
   keep existing LLM-recommended behaviour unchanged (no regression).
5. `fetch_request()` — return `answers`/`violations` per angle + a joined Subject
   place/action/hub_name + `score` for the frontend header, when `subject_id` is set.
6. `tenant_pool.py`/`v1_publish.py` — confirmed correct, no change.
7. Frontend — see `AA-512-fe-wireframe.md` (written before touching `.tsx`, per the build
   prompt's own FE rule).
