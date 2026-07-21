-- Migration 084: AA-299 — acp_contract.tour_atoms.source_hash (idempotency)
--
-- Context: migration 079 shipped tour_atoms with no source_hash column, so
-- the first cut of _decompose_inline() (AA-299, same PR, pre-migration)
-- could only key idempotency on tour_id — "already has any atom row" — which
-- never notices when the source itinerary text changes. This column lets
-- the idempotency check compare (tour_id, source_hash) instead: same hash ⇒
-- skip, different hash (or no prior row) ⇒ decompose again.
--
-- source_hash = sha256 over _build_user_prompt(row)'s own output (the same
-- string sent to the model) — computed in Python (api/routers/v1_atoms.py),
-- not in SQL. That string already concatenates name/aa_summary/aa_highlights/
-- itinerary_source/inclusions/exclusions in _build_user_prompt()'s exact
-- order, so hashing it directly guarantees the hash always matches what was
-- actually decomposed, with no separate field-concatenation logic to drift
-- out of sync.
--
-- Nullable, no backfill: rows inserted before this migration (none expected
-- in prod — tour_atoms had zero INSERTs before this PR, verified via
-- repo-wide grep) get NULL, which the Python-side comparison treats as
-- "different from any real hash" ⇒ re-decompose, never a false skip.
--
-- This PR does NOT delete or supersede old atom rows when source_hash
-- changes — it only adds new ones alongside them. Whether to soft-delete
-- (tour_atoms.deleted) stale-source atoms on a hash mismatch is an open
-- question left for a follow-up, not decided here.
--
-- Not indexed: (tour_id, source_hash) lookups at this call's volume (<100
-- tours/request, inline path only) don't need one yet.

BEGIN;

ALTER TABLE acp_contract.tour_atoms
    ADD COLUMN source_hash TEXT;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('084', now(), 'AA-299: acp_contract.tour_atoms.source_hash — content-hash idempotency key')
ON CONFLICT (version) DO NOTHING;

COMMIT;
