-- Migration 091: shared.pipeline_runs.ingest_details — structured ingest-level diagnostics
--
-- Context: AA-343 Part C. handler.py's ingest step never recorded WHY rows silently failed to
-- land in raw_tours (P1.3 — 14/30 rows vanished on batch 4bdd9b22 with error_message=NULL).
-- tours_passed/tours_failed were considered as the place to record this, but both already carry
-- different live semantics downstream: tours_passed is fully recomputed to the published-tour
-- count by services/export/handler.py once any tour in the batch is exported, and tours_failed is
-- incremented by api/routers/admin_pipeline.py for S1 LLM/quality-gate failures. Writing
-- ingest-level landed/dropped counts into either would misrepresent a just-ingested (not yet
-- rewritten) batch on the tenant-facing dashboard (api/routers/admin.py, unfiltered read of
-- tours_passed) and would permanently conflate ingest drops with quality failures once a batch
-- reaches export. A separate JSONB column avoids both collisions entirely.
--
-- Shape written by handler.py: {"rows_parsed": N, "rows_landed": N, "rows_dropped": N,
-- "drops": [{"reason": "...", "count": N, "sample_ids": [...]}]} — sample_ids carry
-- tour_id_external (falling back to src_name) so a dropped row can actually be traced back to
-- the source file, not just counted.
--
-- Nullable, no backfill: existing pipeline_runs rows (including the 3 stuck Laos batches) predate
-- this column and have no ingest-level diagnostic data to reconstruct.

BEGIN;

ALTER TABLE shared.pipeline_runs
    ADD COLUMN ingest_details JSONB DEFAULT NULL;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('091', now(), 'AA-343: shared.pipeline_runs.ingest_details — structured ingest-level landed/dropped diagnostics, separate from tours_passed/tours_failed')
ON CONFLICT (version) DO NOTHING;

COMMIT;
