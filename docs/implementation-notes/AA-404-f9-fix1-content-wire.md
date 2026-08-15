# AA-404 F9 fix #1 — real brand-rules content + DB cleanup + wiring

**Supplement to `AA-404.md`, not a replacement.** `AA-404.md` has an in-progress uncommitted
section from a concurrent session (LLM cost investigation) at the time this branch was created —
deliberately not touched here to avoid clobbering or entangling unrelated work in this PR's diff.
This file covers only this session's scope: the final piece of F9 fix #1 (real per-tenant brand
content wired into the judge, replacing the hardcoded `AA_BRAND_IDENTITY_PROMPT` fallback).

## Context (recap, not re-investigated here)

Two prior sessions already did the real work this session builds on:
- **Persona-row investigation** (`AA-404.md`, "F9 fix #1+#2+#3" section) — confirmed 6 of 7
  `shared.tenant_brand_rules` rows for `aa_internal` are mis-attached demo/test data for other
  (fictional B2B demo) tenants, and the 7th (`'default'`, id `262dea1c...`) is real but empty.
- **Content draft session** — drafted `system_prompt`/`style_guide`/`forbidden_words`/
  `good_examples` for the `'default'` row, reviewed and approved by Nghiep (good_example #4 —
  "different register of engagement" — dropped as a borderline judge call, not confidently a
  false positive; the remaining 3 are all either the team's own already-live PR #155 anchor
  sentence, or a real sentence a real F9 run quoted verbatim as GENERIC_AI_WORDING evidence).

This session: persists that approved content, removes the 6 mis-attached rows, and wires
`slot_runner.py` to actually read it.

## Decisions

- **One migration (104) for both the cleanup and the content write.** Both operations only make
  sense applied together — writing the real content while 6 mis-attached rows for the SAME
  brand_name-adjacent tenant still clutter the table would leave the row set in a confusing
  half-fixed state for the next person querying it.
- **Archive table (`shared.tenant_brand_rules_deleted_aa404`), not just relying on this
  migration file's own INSERT VALUES as the historical record.** A file recording what SHOULD
  have existed isn't proof of what the live row actually contained at delete time. `CREATE TABLE
  ... LIKE shared.tenant_brand_rules INCLUDING ALL` + a snapshot INSERT (deduped via `NOT
  EXISTS` so re-running the migration is a safe no-op, not a duplicate-row error against the
  inherited PK) gives an exact, queryable copy.
- **Narrow DELETE match** (`tenant_id = aa_internal AND brand_name IN (4 specific names)`), never
  a bare "everything except default" clause — matches the task's own explicit ask, and means a
  future 8th mis-attached row with a different `brand_name` wouldn't be silently swept up if this
  migration were ever misread as a template for a similar cleanup.
- **Dry-run before real apply.** Stripped the migration's own `BEGIN`/`COMMIT` and ran the body
  inside a manually-controlled transaction that deliberately raised after inspecting the
  post-DELETE/UPDATE state, forcing a ROLLBACK — caught any SQL error (quoting, column
  mismatches) before touching real data. Confirmed clean, then applied for real (see Verify).
- **`fetch_brand_rubric_text()` lives in `slot_runner.py`, not a new query embedded in
  `gates.py`.** `gate_brand_seo_audit()`/`gate_brand_seo_audit_social()` (`gates.py`) already
  take `brand_rubric_text` as a pre-fetched string parameter and explicitly do no DB I/O
  themselves (same convention `gate_grounding()` already uses for `valid_ids`/`text_by_id`) —
  keeping that contract unchanged means only the one real caller (`slot_runner.py`) needed to
  change, not the gate functions' own signatures or tests.
- **Reused `admin_pipeline.py::_resolve_brand_rule()`'s exact query shape** (`tenant_id` +
  `brand_name = 'default'` + `is_active = true`) rather than importing that function directly —
  `api.routers.*` is a higher layer than `services.acp_produce.*`; importing downward would
  invert every other module's dependency direction in this package and risks the same
  `api/__init__.py` import-cycle trap `admin_produce.py`'s own module docstring already
  documents for `slot_runner`. Same convention, independent implementation.
- **Fetched once per slot, not once per piece.** `run_slot_production()` produces up to 3 pieces
  (blog + facebook + tiktok) per slot, all the same tenant — one query, reused for every
  `run_piece_through_produce_gates()` call in the loop, not 3 identical queries.
- **Fallback to `AA_BRAND_IDENTITY_PROMPT` kept, not removed.** A tenant with no populated
  `'default'` row (any future B2B tenant before its own content is drafted) still gets a
  reasonable generic rubric instead of an empty string reaching the judge. Logged as a warning
  (`brand_rubric_fallback_generic`) — a silently-generic tenant is a real gap a human should
  notice, matching this pipeline's existing L6 "hold visible, never silent" convention.
- **`gate_brand_seo_audit()`'s docstring corrected a second time.** It has now stated 3 different
  things about its own rubric source across 3 sessions (originally wrong — claimed DB-sourced
  before any wiring existed; corrected to hardcoded-only after the persona-row investigation;
  now genuinely DB-sourced with a documented fallback). Left a short history in the docstring
  itself so a future reader isn't confused by old comments/PRs claiming either prior state.

## Changed

- `api/migrations/104_aa_internal_brand_rules_content.sql` — new. Archives + deletes the 6
  mis-attached rows, writes the approved content onto the `'default'` row.
- `services/acp_produce/slot_runner.py` — new `fetch_brand_rubric_text(db, tenant_id) -> str`
  (exported via `__all__`); `run_slot_production()`'s piece loop now calls it once and passes
  the real result instead of the hardcoded `AA_BRAND_IDENTITY_PROMPT` constant.
- `services/acp_produce/gates.py` — `gate_brand_seo_audit()`'s docstring corrected (see
  Decisions above). No behavior change in this file — it already took `brand_rubric_text` as a
  parameter; only the caller's value changed.
- `tests/unit/test_aa404_brand_rubric_wire.py` — new, 8 tests: real content formats correctly;
  the query shape (table/columns/WHERE clause) is right; falls back to the generic constant when
  no active `'default'` row exists, when `system_prompt` is empty, and when it's whitespace-only;
  `forbidden_words` parses whether it arrives as a JSON string (the real asyncpg behavior, no
  jsonb codec registered) or an already-decoded list; optional sections (`style_guide`/
  `forbidden_words`/`good_examples`) are omitted cleanly, not left as dangling empty headers.
- `tests/unit/test_aa375_slot_runner.py` — the 2 existing tests that reach the piece-production
  loop (`test_happy_path_fans_out_blog_plus_channel_pieces_through_gates`,
  `test_no_trip_id_passes_none_tour_id`) now also patch `fetch_brand_rubric_text` (same "mock
  the DB, exercise the orchestrator" convention this file's own docstring already states) and
  assert every piece in a slot receives the SAME fetched value. The other 3 tests short-circuit
  before the loop and needed no change — confirmed by running them unmodified first.

## Tradeoffs

- **Existing 6 archived rows' original `id`s are preserved** in the archive table (not
  regenerated) — lets anyone cross-reference back to e.g. old log lines or screenshots that
  might reference a specific row id.
- **The fallback path is not covered by a live-DB test** (only mocked-`db.fetchrow` unit tests)
  — a live-DB verify of the fallback would require temporarily deactivating `aa_internal`'s real
  row, which risks leaving the tenant on the generic prompt if the test script fails partway.
  Judged not worth the risk for this fix; the unit tests exercise the real fallback *logic*
  directly instead.

## Should know

- `admin_pipeline.py::_resolve_brand_rule()` itself was NOT touched — it's a separate resolver
  used by different admin routes (S1 rewrite, brand-picker UI) with its own
  `brand_identity_id`/`brand_name` override support that `slot_runner.py`'s N7 path doesn't need
  (N7 always wants the tenant's one `'default'` brand, never a caller-chosen alternate). Two
  independent, intentionally-simple implementations of the same query shape, not a shared
  abstraction — extracting one now would be speculative given N7 has exactly one caller.
- This migration's DELETE is **not reversible via a simple UNDO** — the archive table lets a
  human manually re-INSERT a row if one of the 6 turns out to matter later, but nothing in this
  PR automates that. Flagged in case Nghiep wants a "these were EXACTLY confirmed unrelated to
  aa_internal, not a maybe" gut-check before merge — the confidence level here is "confirmed" per
  the task's own framing (brand_name collision with 4 real other tenants + Sigiriya/Sri Lanka
  content vs. aa_internal's real South Korea/Sapa catalog), not "probably."
