-- =============================================================================
-- Migration 031: acp_silver_s3 v2 — ads_plan + run_context + lessons tables
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 20/05/2026
-- Ticket: AA-45 — S3 Campaign Planner Lambda
-- Sprint: M3
-- =============================================================================
-- acp_silver_s3 schema + content_calendars already exist from DBeaver/acp_m0_migration.sql.
-- This migration adds:
--   1. acp_silver_s3.ads_plan          — Google Ads output per run
--   2. acp_silver_s3.content_calendars — expanded_markdown column (additive)
--   3. acp_shared.acp_run_context      — cross-stage JSONB state per run
--   4. acp_shared.acp_lessons_agency   — tier 1+2 lessons (tenant+country scoped)
--   5. acp_shared.acp_lessons_shared   — tier 3 lessons (cross-tenant system)
--
-- NOTE: acp_shared.tenants does not exist — tenant_id uses VARCHAR(50) no FK,
-- consistent with acp_m0_migration.sql pattern.
-- social_plan moved to AA-80 (S4-social, M4).
-- =============================================================================

BEGIN;

-- ─── 1. ads_plan ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS acp_silver_s3.ads_plan (
    ads_plan_id   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        UUID         NOT NULL REFERENCES acp_shared.acp_runs(run_id) ON DELETE CASCADE,
    tenant_id     VARCHAR(50)  NOT NULL,
    country       VARCHAR(100) NOT NULL,
    model_id      VARCHAR(100) NOT NULL,
    campaigns     JSONB        NOT NULL DEFAULT '[]'::jsonb,
    pdf_s3_key    TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

ALTER TABLE acp_silver_s3.ads_plan ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON acp_silver_s3.ads_plan
    USING (tenant_id = current_setting('app.current_tenant', TRUE));

CREATE INDEX IF NOT EXISTS idx_ads_plan_run     ON acp_silver_s3.ads_plan(run_id);
CREATE INDEX IF NOT EXISTS idx_ads_plan_tenant  ON acp_silver_s3.ads_plan(tenant_id, created_at DESC);

-- ─── 2. content_calendars — add expanded_markdown column ─────────────────────

ALTER TABLE acp_silver_s3.content_calendars
    ADD COLUMN IF NOT EXISTS expanded_markdown   TEXT,
    ADD COLUMN IF NOT EXISTS skeleton_json       JSONB,
    ADD COLUMN IF NOT EXISTS funnel_mix          JSONB DEFAULT '{"tofu":20,"mofu":60,"bofu":20}'::jsonb,
    ADD COLUMN IF NOT EXISTS validation_errors   JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS input_tokens        INTEGER,
    ADD COLUMN IF NOT EXISTS output_tokens       INTEGER,
    ADD COLUMN IF NOT EXISTS model_id            VARCHAR(100);

-- ─── 3. acp_run_context — cross-stage JSONB state ────────────────────────────

CREATE TABLE IF NOT EXISTS acp_shared.acp_run_context (
    run_id                UUID         PRIMARY KEY REFERENCES acp_shared.acp_runs(run_id) ON DELETE CASCADE,
    tenant_id             VARCHAR(50)  NOT NULL,
    -- S1 output
    s1_keywords_used      JSONB        DEFAULT '[]'::jsonb,
    brand_brief           JSONB        DEFAULT '{}'::jsonb,
    -- S2 output
    s2_keyword_research   JSONB        DEFAULT '{}'::jsonb,
    s2_visibility_report  JSONB        DEFAULT '{}'::jsonb,
    -- S3 output
    s3_content_calendar   JSONB        DEFAULT '{}'::jsonb,
    s3_ads_plan           JSONB        DEFAULT '{}'::jsonb,
    s3_funnel_mix         JSONB        DEFAULT '{"tofu":20,"mofu":60,"bofu":20}'::jsonb,
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_run_context_tenant ON acp_shared.acp_run_context(tenant_id);

-- ─── 4. acp_lessons_agency — tier 1+2, tenant+country scoped ─────────────────

CREATE TABLE IF NOT EXISTS acp_shared.acp_lessons_agency (
    lesson_id   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID         NOT NULL REFERENCES acp_shared.acp_runs(run_id) ON DELETE CASCADE,
    tenant_id   VARCHAR(50)  NOT NULL,
    country     VARCHAR(100) NOT NULL,
    tier        VARCHAR(10)  NOT NULL CHECK (tier IN ('job', 'root')),
    content     TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

ALTER TABLE acp_shared.acp_lessons_agency ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON acp_shared.acp_lessons_agency
    USING (tenant_id = current_setting('app.current_tenant', TRUE));

CREATE INDEX IF NOT EXISTS idx_lessons_agency_tenant_country
    ON acp_shared.acp_lessons_agency(tenant_id, country, tier, created_at DESC);

-- ─── 5. acp_lessons_shared — tier 3, cross-tenant system ─────────────────────

CREATE TABLE IF NOT EXISTS acp_shared.acp_lessons_shared (
    lesson_id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    content             TEXT         NOT NULL,
    country             VARCHAR(100),
    promoted_from_run_id UUID        REFERENCES acp_shared.acp_runs(run_id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lessons_shared_country
    ON acp_shared.acp_lessons_shared(country, created_at DESC);

COMMIT;
