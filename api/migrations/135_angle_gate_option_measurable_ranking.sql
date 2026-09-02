-- Migration 135: AA-512 — angle_gate_option gains measurable-ranking evidence.
--
-- STEP0 (docs/claude_audit/AA-512-step0-investigation.md) confirmed AA-511 already shipped
-- everything else AA-512 asked for (subject_id, channel-fixed-from-subject, migration 133/134) —
-- the one real remaining gap is ranking the 3 angles by ADR 0004's measurable formula (Segment/
-- Route Score + PAA-answered count + channel avoid-list violations) instead of LLM opinion.
--
-- `answers`/`violations` are the SERVER-VERIFIED evidence behind that ranking (never the LLM's
-- raw claim — see services/acp_angle_gate/ranking.py), persisted so the API/frontend can read
-- back exactly what was counted, not just a final count. NULL for every row written before this
-- migration, and for any row generated while `channel` was still unknown at generation time (the
-- legacy atom-picker path, channel picked only at step 8, AFTER angles are generated — avoid-list
-- violations cannot be computed without a known channel, so ranking does not run for that path;
-- see the same investigation doc §2). The frontend badge is simply omitted when both are NULL —
-- not rendered as "0 answers, 0 violations", which would misrepresent "never ranked" as "ranked
-- and clean".

BEGIN;

ALTER TABLE acp_shared.angle_gate_option
    ADD COLUMN IF NOT EXISTS answers JSONB NULL,
    ADD COLUMN IF NOT EXISTS violations JSONB NULL;

COMMENT ON COLUMN acp_shared.angle_gate_option.answers IS
    'AA-512 — real PAA questions (verbatim, from this request''s dfs_paa_snapshot) this angle '
    'was verified to answer, per services/acp_angle_gate/ranking.py::rank_angles(). NULL = never '
    'ranked (pre-migration row, or generated before channel was known).';
COMMENT ON COLUMN acp_shared.angle_gate_option.violations IS
    'AA-512 — channel avoid-list phrases matched in this angle''s name+why_it_works text, per '
    'services/acp_angle_gate/ranking.py::rank_angles(). NULL = never ranked (see answers comment).';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('135', now(),
    'AA-512: angle_gate_option.answers/violations — measurable angle-ranking evidence '
    '(ADR 0004: Atom/Segment/Route Score + PAA-answered + avoid-list violations, not LLM opinion)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
