-- Migration 107: AA-425 [A/T-T2-T5] T3 QA gate + T5 atomize support
--
-- (a) gold_aa_internal.tenant_tour_versions — decision (a), AA-425 Linear comment 21/08: reuse
-- this table as T4 ("Tenant Tour Pool"), it already IS the right shape (tenant-scoped, versioned
-- S1-engine output). It had no QA-gate status column — `status` is the tenant-facing approve/
-- reject/pending workflow (unchanged), qa_status is T3's own independent verdict (did this
-- version pass the grounding+structural gate at all, regardless of whether a tenant has since
-- approved/rejected it).
ALTER TABLE gold_aa_internal.tenant_tour_versions
    ADD COLUMN IF NOT EXISTS qa_status text NOT NULL DEFAULT 'pending'
        CHECK (qa_status IN ('pending', 'passed', 'failed', 'escalated')),
    ADD COLUMN IF NOT EXISTS qa_repair_count smallint NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS qa_checked_at timestamptz;

-- (b) silver_aa_internal.review_queue — decision (b): reuse for T3 escalate + tenant-facing
-- filtered view (tenant_id column already existed, no change needed there). generated_content_id
-- is NOT NULL with a real FK to silver_aa_internal.generated_content (the admin/N4 pipeline's own
-- table) — a tenant-rewrite escalate has no such row, and forcing an unrelated id in would either
-- violate the FK or point at the wrong content. Made nullable instead of inventing a fake id.
-- tenant_tour_version_id links an escalate row back to its real source
-- (gold_aa_internal.tenant_tour_versions). escalate_detail carries the issue's mandated
-- {check_id, field, description, source_span, suggested_fix} structured payload per finding;
-- failure_summary (existing column, unchanged shape) stays a short human-readable line, matching
-- every other review_queue writer's convention in this codebase.
ALTER TABLE silver_aa_internal.review_queue
    ALTER COLUMN generated_content_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS tenant_tour_version_id uuid
        REFERENCES gold_aa_internal.tenant_tour_versions(id),
    ADD COLUMN IF NOT EXISTS escalate_detail jsonb;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('107', now(),
        'AA-425 T2-T5: tenant_tour_versions.qa_status/qa_repair_count/qa_checked_at + '
        'review_queue nullable generated_content_id, tenant_tour_version_id, escalate_detail')
ON CONFLICT (version) DO NOTHING;
