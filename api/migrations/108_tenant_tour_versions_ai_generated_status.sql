-- Migration 108: AA-425 — allow 'ai_generated' in tenant_tour_versions.status
--
-- Pre-existing (P3-S9 era) bug, surfaced live during AA-425 verification: v1_tours.py's
-- trigger_rewrite() has always written status='ai_generated' for a high-scoring rewrite
-- (rewrite_score >= 7.0), and the frontend has always expected it (CatalogTab.tsx:594 has a
-- full "Ready to Review" amber-badge label mapped to exactly this value) — but the CHECK
-- constraint here only ever allowed ('pending','approved','rejected','needs_review'). Every
-- historical rewrite that reached this exact line crashed with a check-constraint violation,
-- silently caught by the caller's broad except and falling back to status='needs_review' with
-- quality_score left NULL (real content lost from the row, only a "generating" placeholder
-- remains in rewritten_content). Verified live (21/08/2026): zero historical rows carry that
-- crash signature except the one from this session's own testing — this bug appears to have
-- never actually fired in real usage before today, not a silent historical data-loss issue.
--
-- Purely additive: does not touch any existing row or any of the 4 already-allowed values.
ALTER TABLE gold_aa_internal.tenant_tour_versions
    DROP CONSTRAINT tenant_tour_versions_status_check,
    ADD CONSTRAINT tenant_tour_versions_status_check
        CHECK (status = ANY (ARRAY['pending', 'approved', 'rejected', 'needs_review', 'ai_generated']));

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('108', now(),
        'AA-425: tenant_tour_versions.status CHECK constraint now allows ai_generated '
        '(pre-existing P3-S9 gap between backend/frontend and the DB constraint)')
ON CONFLICT (version) DO NOTHING;
