-- Migration 128: AA-508 — acp_contract.atomize_day_fingerprint.
--
-- STEP0 (docs/claude_audit/AA-508-step0-atom-identity-investigation.md,
-- AA-508-step0b-upsert-vs-new-verification.md) found: run_t5_atomize() atomized a tenant tour
-- version in ONE LLM call over the whole itinerary, keyed to skip-or-not by ONE source_hash over
-- the whole itinerary text — a single-day edit re-atomized (and re-randomized every atom_id of)
-- the entire tour. Reference repo aa-social-media (src/aa_social/stages/atoms.py::_fingerprint())
-- keys skip per DAY instead, on (day text + the decompose instruction + the model) — confirmed
-- live-measured there: 206 days, 69s/$1.44 cold vs. 3s once every day's fingerprint already
-- matches.
--
-- Keyed on (tenant_tour_version_id, day_number), NOT (tour_id, owner_scope, day_number): a new
-- tenant_tour_versions row is a genuinely new rewrite attempt (T4) that can reshuffle every day's
-- wording even where the tenant asked for no change — STEP0b's own measurement on the reference
-- repo (README: forcing a re-read of unchanged content still only kept 41% of atom_ids, the model
-- re-worded the rest) means a fingerprint carried over across versions would UNDER-count how much
-- actually changed. Scoping to the version this fingerprint was read under keeps the row's meaning
-- exact: "this day, in THIS version, read clean as of this fingerprint" — a fresh version starts
-- with no rows here and reads every day once, same as a brand-new tour would.
--
-- fingerprint_hash is computed in Python (services/acp_shared/atom_extraction.py::
-- day_fingerprint()), sha256 over (day_title + day_body + SYSTEM_PROMPT + model tier) — same 3-part
-- shape the reference repo's own _fingerprint() uses (prompt/day text, the instruction, the model),
-- so a prompt or model change invalidates every day's cache exactly like a re-worded day would.
--
-- Role: this table is what BLOCKS the LLM call, not just a log written after one — run_t5_atomize()
-- checks it before calling invoke_claude() for a given day and skips the day entirely on a hash
-- match. tour_atoms.source_hash (migration 084) is UNCHANGED and kept — still written per atom, now
-- purely as a whole-tour fallback/audit value, no longer the mechanism that decides skip-or-not.
--
-- No FK to gold_aa_internal.tenant_tour_versions(id): STEP0 addendum (build-task's own mandatory
-- pre-migration grep, docs/implementation-notes/AA-508.md) confirmed there is NO existing FK
-- constraint anywhere in this schema pointing at tour_atoms.atom_id either — this repo's own
-- established convention for atom-adjacent tables (acp_shared.angle_gate_request.atom_id, migration
-- 113, is TEXT NOT NULL with no FK) is app-level joins, not DB-enforced FKs. Matched here
-- deliberately, not by oversight — adding one is a separate decision, not made in this migration.

BEGIN;

CREATE TABLE IF NOT EXISTS acp_contract.atomize_day_fingerprint (
    tenant_tour_version_id  UUID NOT NULL,
    day_number              INT NOT NULL,
    fingerprint_hash        TEXT NOT NULL,
    atomized_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_tour_version_id, day_number)
);

COMMENT ON TABLE acp_contract.atomize_day_fingerprint IS
    'AA-508 — per-day skip-cache for run_t5_atomize(). A row means "day day_number of '
    'tenant_tour_version_id was atomized with fingerprint_hash" — a matching fingerprint on the '
    'next atomize call skips that day''s LLM call entirely and leaves its acp_contract.tour_atoms '
    'rows untouched. See atom_extraction.py::day_fingerprint() for the hash inputs.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('128', now(),
    'AA-508: acp_contract.atomize_day_fingerprint — per-day skip-cache, replaces whole-tour '
    'source_hash as T5''s primary re-atomize gate (source_hash kept as fallback/audit)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
