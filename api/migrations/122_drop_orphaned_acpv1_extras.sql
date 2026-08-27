-- Migration 122: AA-481 — drop 6 additional dead ACPv1/pre-ACP tables found in the AA-479
-- full-schema audit (docs/claude_audit/AA-479-schema-audit.md), NOT in migration 121's 15-table
-- scope because none of them have a real FK constraint into acp_shared.acp_runs (or anything
-- else) — confirmed via pg_constraint 27/08/2026: 0 FK edges (as source or target) for any of
-- the 6 tables below, 0 views depend on them (pg_depend). Re-verified fresh immediately before
-- drafting this migration: all 6 still 0 rows, 0 real (non-comment) code callers.
--
-- acp_shared.acp_cms_publish_queue (migration 039, AA-100) — CMS publish queue for the old
-- v1_s4_blog.py::hitl_decision() (deleted in AA-477). T11's real acp_shared.publish_log
-- (migration 116, AA-455) is a NEW, separate table — its own migration comment says it "mirrors
-- the real precedent... acp_cms_publish_queue (migration 039) — but scoped to content_piece
-- instead of the old pre-T-series blog_drafts" — a design-lineage note, not data reuse.
--
-- acp_shared.idempotency_keys (migration 029, AA-43) — created explicitly "for S2 run dedup".
-- services/acp/s2/ has no real source left (only stale __pycache__, confirmed via `git ls-files`
-- and a live `ModuleNotFoundError` on `import services.acp.s2.graph`).
--
-- shared.lessons_registry (migration 002/003 — the earliest schema versions on record, predating
-- ACP entirely). 0 caller anywhere in api/ or services/.
--
-- public.checkpoints / checkpoint_blobs / checkpoint_writes — LangGraph's own AsyncPostgresSaver
-- runtime tables. No file under api/migrations/ creates them (LangGraph's checkpointer.setup()
-- created them at runtime, historically from S2's own graph checkpointing). 0 caller of
-- `checkpointer`/`AsyncPostgresSaver`/`PostgresSaver` anywhere in the current codebase.
-- public.checkpoint_migrations (LangGraph's own internal migration counter, 10 rows) is
-- deliberately NOT touched here — dropping it isn't necessary to remove the 3 empty data tables,
-- and it's LangGraph-library-owned bookkeeping, not something this app's migrations should manage.
--
-- Companion PR also removes 7 dead test files that imported services.acp.s2.* (6 whole files +
-- 1 surgical edit on tests/acp/test_s1_state_bridge.py, which mixed live S1 tests with dead S2
-- tests in the same file).
--
-- Meant to run alongside migration 121 (AA-477, same PR) — both draft, both apply together after
-- explicit go-ahead. No FK ordering dependency between 121 and 122 (confirmed 0 constraints
-- connecting the 6 tables here to anything in 121's 15-table cluster or vice versa).

BEGIN;

DROP TABLE IF EXISTS acp_shared.acp_cms_publish_queue;
DROP TABLE IF EXISTS acp_shared.idempotency_keys;
DROP TABLE IF EXISTS shared.lessons_registry;
DROP TABLE IF EXISTS public.checkpoints;
DROP TABLE IF EXISTS public.checkpoint_blobs;
DROP TABLE IF EXISTS public.checkpoint_writes;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('122', now(),
    'AA-481: DROP 6 additional dead ACPv1/pre-ACP tables (acp_cms_publish_queue, '
    'idempotency_keys, lessons_registry, public.checkpoints/checkpoint_blobs/checkpoint_writes) '
    'found in the AA-479 full-schema audit, 0 FK/0 caller confirmed')
ON CONFLICT (version) DO NOTHING;

COMMIT;
