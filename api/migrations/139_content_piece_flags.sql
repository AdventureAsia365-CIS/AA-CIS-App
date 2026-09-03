-- Migration 139: AA-519 Việc 5 -- content_piece.flags
--
-- ADR 0023 (Ms. Thư repo, "A Gate flags rather than blocks") + ADR 0026 ("An offered moment is
-- ranked, and never promised"): a Piece with a gate violation a HUMAN must judge (not a writer
-- rewrite) still SHIPS -- it carries the violation as a flag + note, not a hold. AA-514 ported
-- `promises_an_option` as `repairable=False`, which this codebase's own T10 loop (service.py::
-- run_write_background()) treats as an immediate hold -- i.e. a block, the exact thing ADR 0023
-- rejects (see that ADR's own "Rejected: block on the world, flag on the shape"). AA-519 fixes
-- the mechanism (quality_gates.py gains a `blocking` field, `promises_an_option` is the first
-- gate to set it False) and this column is where the resulting flag is persisted so T10 can show
-- it to the tenant.
--
-- Deliberately NOT part of gate_ledger (that column stays admin-only, AA-501 STEP0 §4's own
-- exposure boundary for the other 8 gates) -- `flags` only ever holds failed-but-non-blocking
-- gate results, which are safe to show a tenant by construction (ADR 0023's whole point: the note
-- is FOR the person reading the piece). NULL/empty for every piece with no flag, and for every
-- pre-AA-519 row.

BEGIN;

ALTER TABLE acp_shared.content_piece
    ADD COLUMN IF NOT EXISTS flags JSONB NULL;

COMMENT ON COLUMN acp_shared.content_piece.flags IS
    'AA-519 -- failed-but-non-blocking gate results (ADR 0023 flag-not-block, Ms. Thư repo),
    e.g. promises_an_option. Deliberately tenant-safe to expose, unlike gate_ledger. NULL/empty
    when no gate flagged this piece.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('139', now(),
    'AA-519 Việc 5: content_piece.flags -- tenant-safe non-blocking gate flags (ADR 0023),
    starting with promises_an_option')
ON CONFLICT (version) DO NOTHING;

COMMIT;
