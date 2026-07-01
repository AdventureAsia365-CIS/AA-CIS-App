-- Migration 073: AA-242 — add 'superseded' to review_status_enum
--
-- Context: Regenerate-from-review-queue (AA-242) reruns the pipeline and INSERTs a new
-- generated_content version + a new review_queue row (never updates in-place — verified
-- STEP 0). When the regenerated version is publishable, the OLD review_queue row for that
-- tour must be closed out distinctly from a reviewer 'rejected' decision or an automatic
-- 'skipped' (timeout/auto-skip, unused dead value since migration 002/003). 'superseded'
-- disambiguates: this row was not judged bad, it was replaced by a newer regenerated version.
--
-- Postgres requires ALTER TYPE ... ADD VALUE to run outside an explicit transaction block
-- in older versions; on modern Postgres (12+) it is transactional-safe as a single statement.
-- Apply once against the shared Dev+Prod DB per project convention (single-env architecture).

ALTER TYPE review_status_enum ADD VALUE IF NOT EXISTS 'superseded';
