-- Migration 127: AA-501 — acp_shared.angle_gate_request.dfs_paa_snapshot.
--
-- STEP0 (docs/claude_audit/AA-501-step0-review-screen-investigation.md §1.4) found the real gap:
-- `services/acp_shared/dfs_relevance.py::fetch_search_demand_signal()` reads
-- `silver_aa_internal.seo_context.people_also_ask`/`related_keywords` LIVE at angle-generation
-- time (`set_goal_and_generate()`, workflow step 5) to build the LLM prompt, then discards the
-- result — nothing on `angle_gate_request` or `content_piece` records what the LLM actually saw.
-- Nghiệp's explicit decision (AA-501 build task): this must be a SNAPSHOT, not a live re-fetch —
-- if T2 DFS re-runs later and changes `seo_context`, an already-written piece's displayed
-- context must NOT silently change out from under it.
--
-- Placed on `angle_gate_request`, not `content_piece`: `fetch_search_demand_signal()` is called
-- exactly once per request, at `set_goal_and_generate()` time (workflow step 5, before any angle
-- exists yet) — not once per write attempt. AA-497's reopen()/choose_angle() cycle re-points
-- `chosen` at an already-generated angle_gate_option row and lets T9 write again, but does NOT
-- re-call set_goal_and_generate() or regenerate angles — so one snapshot per request is correct
-- for every content_piece written under it, current or future.
--
-- Nullable JSONB, no CHECK shape constraint (mirrors `content_piece.gate_ledger`/`repair_log`'s
-- own "just a JSONB blob, shape owned by the Python layer" precedent, migration 115) — shape is
-- `{"relevance": "HIGH"|"MED"|"LOW", "people_also_ask": [...], "related_keywords": [...]}`,
-- i.e. `services.acp_shared.dfs_relevance.SearchDemandSignal`'s own 3 fields, serialized as-is.
-- NULL for every pre-migration row (no backfill possible — the live signal at THAT generation
-- time is gone, and re-fetching seo_context now would be exactly the live-drift problem this
-- migration exists to avoid) and for any request whose atom has no `trip_id` (no seo_context to
-- fetch in the first place, same as `fetch_search_demand_signal()`'s own None-return case).

BEGIN;

ALTER TABLE acp_shared.angle_gate_request
    ADD COLUMN IF NOT EXISTS dfs_paa_snapshot JSONB;

COMMENT ON COLUMN acp_shared.angle_gate_request.dfs_paa_snapshot IS
    'AA-501 — snapshot of services.acp_shared.dfs_relevance.SearchDemandSignal '
    '(relevance/people_also_ask/related_keywords) at the moment set_goal_and_generate() called '
    'fetch_search_demand_signal() for this request. NULL = no snapshot (pre-migration row, or '
    'the atom had no trip_id / seo_context to fetch from). Deliberately NOT re-fetched live for '
    'display — a later T2 DFS re-run must not change what an already-generated angle/piece shows '
    'it was written with.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('127', now(),
    'AA-501: acp_shared.angle_gate_request.dfs_paa_snapshot — DFS/PAA persisted at angle-gen '
    'time (snapshot, not live re-fetch) for the new T10 review screen')
ON CONFLICT (version) DO NOTHING;

COMMIT;
