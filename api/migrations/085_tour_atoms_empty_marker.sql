-- Migration 085: AA-299 — acp_contract.tour_atoms.is_empty_marker (zero-atom idempotency)
--
-- Context: migration 084 keyed idempotency on the source_hash of the tour's most
-- recent tour_atoms row. That works when a decompose attempt inserts >=1 real
-- atom, but a tour whose source is thin enough to legitimately yield ZERO atoms
-- (the "never pad" case) leaves no row behind at all -- the idempotency SELECT
-- finds nothing, latest_hash is NULL, and the tour is re-sent to Bedrock on
-- every subsequent call, forever, with no cost-savings from the hash check.
-- Confirmed live (2026-07-21, AA-299 Group A sample): Yaksa Trek returned 0
-- atoms on call #1 and was NOT skipped on call #2.
--
-- Fix: _decompose_inline() (same PR) now writes one marker row when a tour's
-- atom list is empty, purely to carry source_hash forward so the next call's
-- idempotency check has something to compare against.
--
-- is_empty_marker distinguishes a marker row from a real atom. It is a
-- SEPARATE column from `deleted`, not a reuse of it: `deleted` means "a real
-- atom existed and was removed" (audit/GDPR/veto-stats meaning) -- a marker
-- row was never a real atom in the first place, a different fact entirely.
-- Marker rows are therefore inserted with deleted=false, is_empty_marker=true.
--
-- Consequence: every place that filters "real, currently displayable atoms"
-- must exclude is_empty_marker explicitly -- it is NOT covered by existing
-- "NOT deleted" filters. Fixed in this PR: the pending-tours LEFT JOIN in
-- POST /v1/atoms/decompose now reads `AND NOT ta.deleted AND NOT
-- ta.is_empty_marker`. Migration 079's two partial indexes
-- (idx_tour_atoms_tour_id, idx_tour_atoms_distinctiveness), both `WHERE NOT
-- deleted`, are deliberately NOT altered here -- neither is UNIQUE, and
-- Postgres can still use a `WHERE NOT deleted` partial index for a query that
-- additionally filters `AND NOT is_empty_marker` (the extra predicate is
-- simply applied as a residual filter after the index scan); at current/
-- expected atom volumes per tour, narrowing the index predicate further is a
-- speculative optimization with no measured need, consistent with this
-- table's existing "don't index ahead of demonstrated need" convention (see
-- migration 084's source_hash comment).
--
-- The idempotency SELECT itself (`SELECT source_hash FROM tour_atoms WHERE
-- tour_id=... ORDER BY created_at DESC LIMIT 1`) needed no change -- it never
-- filtered on deleted or is_empty_marker, so it already picks up a marker row
-- as the tour's most recent tour_atoms entry, which is the whole point of
-- writing the marker in the first place.

BEGIN;

ALTER TABLE acp_contract.tour_atoms
    ADD COLUMN is_empty_marker BOOLEAN NOT NULL DEFAULT false;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('085', now(), 'AA-299: acp_contract.tour_atoms.is_empty_marker — zero-atom idempotency marker')
ON CONFLICT (version) DO NOTHING;

COMMIT;
