-- =============================================================================
-- Migration 072 — generated_content human-edit audit + re-validation gate
-- AA-234 Phần A: HITL reviewer edits a generated_content version IN PLACE
--         (overwrite, no new version), then an async re-validation graph
--         (validate → judge → brand_audit → revalidate, NO flag_fix) re-scores
--         it. Approve-to-gold is gated: a human-edited version may export only
--         after a passing re-validation. These columns track who/when/what was
--         edited and the gate outcome.
-- NOTE: revalidate_passed is intentionally NULLABLE (3-state):
--         NULL  = never re-validated after edit (or never edited)
--         true  = last re-validation passed  → approve allowed
--         false = last re-validation failed  → approve BLOCKED
--       Approve requires NOT (human_edited AND revalidate_passed IS NOT TRUE).
-- Applied: pending
-- =============================================================================
BEGIN;

ALTER TABLE silver_aa_internal.generated_content
    ADD COLUMN IF NOT EXISTS human_edited      boolean      NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS reviewed_by       varchar(128),
    ADD COLUMN IF NOT EXISTS edited_at         timestamptz,
    ADD COLUMN IF NOT EXISTS edit_diff         jsonb        NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS revalidate_passed boolean;

COMMENT ON COLUMN silver_aa_internal.generated_content.human_edited IS
    'AA-234: true once a reviewer edited any scored field on this version in place.';
COMMENT ON COLUMN silver_aa_internal.generated_content.revalidate_passed IS
    'AA-234: 3-state gate. NULL=not revalidated, true=passed, false=failed. Approve requires NOT (human_edited AND revalidate_passed IS NOT TRUE).';

INSERT INTO shared.schema_versions (version, description)
    VALUES ('072', 'generated_content human-edit audit + re-validation gate [AA-234]')
    ON CONFLICT DO NOTHING;

COMMIT;
