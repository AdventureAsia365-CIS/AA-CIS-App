-- Migration 077: AA-296 — silver_aa_internal.generated_content.satellite_used
--
-- Context: AA-296 thêm nhánh T1.5/T2.5 (Bedrock qua acc1 satellite, cross-
-- account AssumeRole) khi acc2 (TrueIDC channel-program org) không có
-- Anthropic model. satellite_used phân biệt content được viết qua satellite
-- (vẫn đúng chất lượng/model ý định ban đầu) với fallback_used (hạ tier,
-- hoặc rơi xuống GPT-4.1) — 2 khái niệm khác nhau, không dùng chung 1 cột.
--
-- Plain ADD COLUMN — no transactional-safety caveat applies.
-- Applied: Dev only, per project convention (single-env architecture, same as 071-076).

BEGIN;

ALTER TABLE silver_aa_internal.generated_content
    ADD COLUMN IF NOT EXISTS satellite_used BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN silver_aa_internal.generated_content.satellite_used IS
    'AA-296: true khi content được viết qua Bedrock satellite (acc1 cross-account AssumeRole), không phải acc2 trực tiếp hoặc GPT-4.1 fallback.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('077', NOW(), 'AA-296: generated_content.satellite_used for T1.5/T2.5 tracking')
ON CONFLICT (version) DO NOTHING;

COMMIT;
