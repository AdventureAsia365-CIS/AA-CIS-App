-- Migration 124: AA-494 Step 2 — schema for Decisions 1-3 of docs/claude_tasks/
-- AA-494-design-atom-angle-piece-reuse.md (atom/angle/piece N:N reuse model).
--
-- Live-verified before writing this file (29/08/2026, direct RDS read via the standard
-- S3-mediated ECS-exec pattern): neither `angle_gate_option_id` nor `channel` nor
-- `content_summary` nor `content_embedding` exist on `acp_shared.content_piece` yet — none of
-- this is a re-add. `angle_gate_option.option_id` (the FK target, migration 113) IS the real PK
-- name, confirmed live, not assumed from the design doc's prose. pgvector extension is already
-- installed (v0.8.1, from migration 041 / AA-62) — no `CREATE EXTENSION` needed here.
--
-- Decision 1 (channel moves to content_piece, chosen at write time instead of request
-- creation) — schema-only in this migration. `content_piece.channel` is added so a future write
-- can populate it per Decision 2's denormalization; `angle_gate_request.channel` is
-- DEPRECATED-IN-PLACE, not dropped: `create_request()` (services/acp_angle_gate/service.py)
-- still requires it as a mandatory param and `start_write()`/T9's CTA lookup
-- (`_fetch_slot_cta(tenant_id, atom_id, channel, pool)`) still reads it live today — the actual
-- "tenant picks channel at write time" UX/API flip is explicitly deferred (design doc build
-- order step 5: "this will need its own small design pass... not assumed complete by this
-- document"). Dropping the column now would break the live T8/T9 request flow for no reason;
-- revisit dropping it only once AngleGateTab.tsx's write-time-channel redesign actually ships
-- and nothing reads angle_gate_request.channel anymore.
--
-- Decision 2 (content_piece keeps 3 FKs: angle_gate_request_id (existing) + angle_gate_option_id
-- (new) + channel (new), denormalized, not JOINed) — `angle_gate_option_id` nullable: existing
-- rows (pre-this-migration) have no option to backfill from without re-deriving it via a
-- best-effort join to angle_gate_option.chosen=true at the time, which could be wrong for any
-- request where chosen was re-picked after the row was written (impossible before this migration
-- since choose_angle() couldn't be called twice until Decision 3 ships, so NULL is honest and
-- harmless for all pre-existing rows either way) — left NULL rather than backfilled.
--
-- Decision 3 (angle_gate_request.status gains a new value after 'approved', Kịch bản A — extend
-- the CHECK, don't remove the column) — new value name: 'reusable' (matches the design doc's own
-- proposed name verbatim, docs/claude_tasks/AA-494-design-atom-angle-piece-reuse.md Decision 3;
-- no conflicting existing status-value convention found in this table or `content_piece`'s own
-- status set to avoid). Recommended trigger condition (design doc: "recommend the former" —
-- flip to 'reusable' on the request's FIRST successful (status='approved') content_piece, not
-- immediately after choose_angle()) is documented here for the next session but NOT implemented
-- as code in this migration/PR — the write-time application wiring (widening
-- acp_content_writing/service.py::start_write()'s `status == 'approved'` guard, adding the
-- transition itself, and the AngleGateTab.tsx UX to actually let a tenant return to a
-- 'reusable' request) is out of THIS build task's explicit Step 2 scope (schema migration
-- only) and — as importantly — the current `content_piece` UNIQUE(angle_gate_request_id,
-- attempt_number) constraint models "one write session per request" (attempt_number 1-2 inside
-- ONE row's lifecycle, see migration 115/118's own header comments); a second real write on a
-- 'reusable' request would need a second content_piece row for the SAME angle_gate_request_id,
-- which collides with that UNIQUE constraint as it stands today. That is a genuine, separate
-- schema question (not answered by Decisions 1-3's own text) flagged for the next session rather
-- than silently patched here — adding 'reusable' to the CHECK constraint is additive/inert until
-- something actually sets it, so it's safe to ship now without resolving that question.
--
-- Decision 4/5 (prior-piece prompt history + pgvector similarity) — `content_summary`/
-- `content_embedding` columns added here (same migration as Decision 2's `angle_gate_option_id`,
-- per the design doc's own "Cross-decision dependencies" #3: same table, avoid a second ALTER
-- TABLE pass) but population/consumption (the LLM prompt change, the embedding call, the
-- similarity-check function) is NOT built in this migration — explicitly out of this build
-- task's Step 2-5 scope (see docs/implementation-notes/AA-494.md for the running scope record).
-- vector(1536) matches the ONE existing precedent in this codebase (migration 041 / AA-62,
-- Bedrock Titan Embed Text v2 output dimension) — kept consistent rather than guessing a
-- different embedding model's dimension.

BEGIN;

ALTER TABLE acp_shared.content_piece
    ADD COLUMN IF NOT EXISTS angle_gate_option_id UUID
        REFERENCES acp_shared.angle_gate_option(option_id),
    ADD COLUMN IF NOT EXISTS channel TEXT,
    ADD COLUMN IF NOT EXISTS content_summary TEXT,
    ADD COLUMN IF NOT EXISTS content_embedding vector(1536);

COMMENT ON COLUMN acp_shared.content_piece.angle_gate_option_id IS
    'AA-494 Decision 2 — which of the 3 angle_gate_option rows this specific piece was written '
    'from. Denormalized (not derived via angle_gate_request.status/chosen, which is mutable and '
    'can be re-picked) so a piece''s history stays accurate even after a later re-choice. NULL '
    'on rows written before this migration.';
COMMENT ON COLUMN acp_shared.content_piece.channel IS
    'AA-494 Decision 1/2 — denormalized copy of the channel this piece was written for. Not yet '
    'populated by application code as of migration 124 (angle_gate_request.channel remains the '
    'live source until the write-time-channel UX ships — see this migration''s header).';
COMMENT ON COLUMN acp_shared.content_piece.content_summary IS
    'AA-494 Decision 4 — 1-2 sentence summary of this piece, meant to be generated by the same '
    'LLM call that writes the piece (near-zero marginal cost) and fed into future angle-gen '
    'prompts as "prior pieces from this atom" context. Not yet populated as of migration 124.';
COMMENT ON COLUMN acp_shared.content_piece.content_embedding IS
    'AA-494 Decision 5 — embedding of this piece''s full text, for within-tenant/cross-tenant '
    'similarity checks (shared mechanism, two call sites). vector(1536) matches migration 041''s '
    'Bedrock Titan Embed Text v2 precedent. Not yet populated as of migration 124 — no embedding '
    'call is wired anywhere in this codebase yet (confirmed by STEP0 grep, 0 results).';

ALTER TABLE acp_shared.angle_gate_request
    DROP CONSTRAINT IF EXISTS angle_gate_request_status_check;
ALTER TABLE acp_shared.angle_gate_request
    ADD CONSTRAINT angle_gate_request_status_check
    CHECK (status IN ('pending_goal', 'pending_choice', 'approved', 'reusable'));

COMMENT ON COLUMN acp_shared.angle_gate_request.status IS
    'AA-449: pending_goal -> pending_choice -> approved (tenant has chosen an angle). '
    'AA-494 Decision 3 adds reusable (approved + at least one successful content_piece written '
    '— recommended trigger: first content_piece.status=''approved'' for this request, see '
    'migration 124''s header) but no code sets this value yet as of migration 124.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('124', now(),
    'AA-494: content_piece gains angle_gate_option_id/channel/content_summary/content_embedding '
    '(Decisions 2/4/5, columns only); angle_gate_request.status CHECK gains reusable '
    '(Decision 3, value only, no trigger code yet)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
