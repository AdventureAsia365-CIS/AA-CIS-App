-- Migration 109: AA-436 — T3 QA gate stops blocking the tenant flow
--
-- ADR-2026-038 §0.1 (amend §10.3, 22/08/2026): reverses the 21/08 self-service-escalate
-- direction. A tenant editing their own copy to clear a QA failure is a bad UX, and an
-- escalate-and-stop breaks the single-job T2->T3->T5 chain (AA-425). New behavior: after
-- TENANT_QA_MAX_REPAIRS (=2) self-repair rounds still fail, the tour is auto-passed through
-- to T4 (pool) + T5 (atomize) exactly like a real pass — `review_queue` still gets the same
-- escalate row as before (AA-425's escalate_t3_failure(), unchanged) so A4 (AA-437, cross-
-- tenant oversight, separate issue) can see it, but it no longer blocks the tenant.
--
-- `qa_auto_passed` is a new, separate signal from the existing `qa_status` column
-- (migration 107: 'pending'|'passed'|'failed'|'escalated', still written the same way —
-- 'escalated' still means "QA gate did not actually pass", untouched by this migration).
-- `qa_auto_passed` is purely the tenant-visible-badge flag: true means "this tour reached
-- your pool despite QA gate never truly clearing" — CatalogTab.tsx shows a small neutral
-- badge for it, no error detail (that stays in review_queue.escalate_detail, admin/A4-only).
--
-- Purely additive: default false is correct for every existing row (none of them went
-- through the new auto-pass path — that path didn't exist before this migration).
ALTER TABLE gold_aa_internal.tenant_tour_versions
    ADD COLUMN IF NOT EXISTS qa_auto_passed boolean NOT NULL DEFAULT false;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('109', now(),
        'AA-436: tenant_tour_versions.qa_auto_passed — T3 QA-gate failure after max repair '
        'rounds now auto-passes to T4/T5 instead of blocking; this flag drives the tenant-'
        'facing badge (qa_status/review_queue escalate row unchanged, still written)')
ON CONFLICT (version) DO NOTHING;
