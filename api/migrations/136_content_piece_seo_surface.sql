-- Migration 136: AA-514 -- content_piece gains seo_title/meta_description/slug.
--
-- STEP0 (docs/claude_audit/AA-514-step0-investigation.md) confirmed the origin's
-- `gates/shape.py::seo_surface()` needs structured Piece.seo_title/meta_description/slug/keyword
-- fields that acp_shared.content_piece never had (T9 has only ever written one `content_text`
-- blob). Nghiep's explicit decision (asked directly, real architecture fork): full port -- add
-- these columns and change T9's blog-channel writer output shape from plain text to a JSON
-- envelope carrying them alongside the body, rather than a schema-free heuristic substitute.
--
-- Nullable, and in practice only ever populated for channel='blog' (the only channel the origin's
-- own SEO surface gate scopes to, GATES tuple: `Gate("SEO surface", shape.seo_surface, BLOG,
-- fixable=True)`) -- the other 7 channels' writer output contract is UNCHANGED (still plain
-- text), so these 3 columns stay NULL for every non-blog piece, same as every pre-AA-514 row.

BEGIN;

ALTER TABLE acp_shared.content_piece
    ADD COLUMN IF NOT EXISTS seo_title TEXT,
    ADD COLUMN IF NOT EXISTS meta_description TEXT,
    ADD COLUMN IF NOT EXISTS slug TEXT;

COMMENT ON COLUMN acp_shared.content_piece.seo_title IS
    'AA-514 -- blog-channel only writer output field (T9), checked by quality_gates.py::'
    'gate_seo_surface() (F4 family). NULL for every non-blog piece and every pre-AA-514 row.';
COMMENT ON COLUMN acp_shared.content_piece.meta_description IS
    'AA-514 -- blog-channel only writer output field (T9), checked by quality_gates.py::'
    'gate_seo_surface(). NULL for every non-blog piece and every pre-AA-514 row.';
COMMENT ON COLUMN acp_shared.content_piece.slug IS
    'AA-514 -- blog-channel only writer output field (T9), checked by quality_gates.py::'
    'gate_seo_surface(). NULL for every non-blog piece and every pre-AA-514 row.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('136', now(),
    'AA-514: content_piece.seo_title/meta_description/slug -- blog-only SEO surface fields, '
    'full port of the origin seo_surface() gate (Nghiep-confirmed architecture decision)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
