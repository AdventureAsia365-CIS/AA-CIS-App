-- Migration 102: acp_deliver.pieces repair_log/repair_budget/initial_failing_gate_count
-- (AA-396 follow-up — dynamic repair budget, option C)
--
-- Context: ADR-2026-029's flat max_repairs=3 (models.py::REPAIR_TOTAL_MAX) starved pieces
-- that started with multiple simultaneous gate failures (real example: piece
-- slot_b09166b7f2fdc28c87fd:blog, F3+F4+F8+F9 all failing at once, docs/implementation-notes/
-- AA-391-report-data.json) -- run_gates() only ever targets ONE gate per round, so 3 rounds
-- can fix at most 3 simultaneous failures. gates.py::compute_repair_budget() now scales the
-- per-piece budget to the piece's own starting failure count (capped at REPAIR_BUDGET_CAP=8,
-- models.py) -- this migration adds the 3 columns run_gates() now populates on Piece
-- (services/acp_produce/models.py) so a human reviewing a held piece has the computed budget
-- and the full per-round repair history in the SAME place they already look
-- (acp_deliver.pieces, alongside the existing gate_ledger/held_reason/repair_count columns),
-- not a separate log store.
--
-- No new table, no new schema -- ALTER TABLE on the existing acp_deliver.pieces (migration
-- 094). repair_log mirrors gate_ledger's own convention (JSONB array, NOT NULL DEFAULT '[]',
-- json.dumps([model.model_dump() for model in list]) from pipeline.py::_persist_piece()).
--
-- Mistake-to-Rule wiring (STEP 0 finding, AA-396 follow-up task): the repo's real
-- Mistake-to-Rule mechanism is services/acp_shared/h3_rule_extractor.py::extract_and_save_rule()
-- (H-3) -- it is keyed on a human reviewer's rejection note tied to a real
-- acp_shared.acp_hitl_requests row, and N7's automated repair-exhaustion holds have neither.
-- Wiring N7 into H-3 (or a variant of it) so a held piece's repair_log can auto-promote into
-- acp_shared.acp_output_rules is NOT built here -- these 3 columns are the minimal structured
-- record a human needs to do that promotion manually today, same as the original 22
-- acp_output_rules seed rows (migration 020) were authored by a human reading real output, not
-- by an automated pipeline.
--
-- Backfill: N/A -- every existing acp_deliver.pieces row predates this fix and has no
-- meaningful initial_failing_gate_count/repair_budget/repair_log to backfill; NULL/'[]'
-- defaults are the correct "unknown, pre-fix" state, not a data-quality gap.

BEGIN;

ALTER TABLE acp_deliver.pieces
    ADD COLUMN IF NOT EXISTS repair_log                  JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS repair_budget                SMALLINT,
    ADD COLUMN IF NOT EXISTS initial_failing_gate_count    SMALLINT;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('102', now(),
        'AA-396 follow-up: acp_deliver.pieces.repair_log/repair_budget/initial_failing_gate_count -- dynamic repair budget per-round history')
ON CONFLICT (version) DO NOTHING;

COMMIT;
