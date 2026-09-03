-- AA-518 Việc C + AA-505 (gộp 1 đợt, 02/09/2026) — per-stage admin model config + per-call
-- cost/quality log. Build prompt saved verbatim at docs/claude_tasks/AA-518-AA-505-per-stage.md;
-- full STEP0 (schema decisions vs. the prompt's own proposal) at docs/implementation-notes/
-- AA-518.md "Việc C round 3 (final build)".
--
-- 2 real deviations from the build prompt's proposed schema, found during STEP0:
--   1. `stage` is CALL-SITE granular (16 rows — one per place in the code that independently
--      picks a model today), not "A0"/"A1"/"T2"-style coarse product-phase labels. The build
--      prompt's own example list ("A0, A1, T2, T5, T7, T8, T9...") turned out not to map onto
--      real code structure: S1's rewrite graph (services/content_generation/graph.py) is the
--      SAME code whether triggered by an admin A1 batch-rewrite or a tenant T2 self-service
--      rewrite — there is no code-level "A1 vs T2" distinction to hang two different model
--      configs off of, only a `tenant_id` that differs at call time (NULL for A1, real for T2).
--      Config is keyed to the call site instead; llm_call_log's own `tenant_id` column is what
--      actually distinguishes an A1 admin call from a T2 tenant call of the identically-configured
--      `s1_generate` stage. See AA-518.md for the full 16-row call-site table + reasoning.
--   2. `updated_by` is TEXT, not `uuid REFERENCES shared.admin_users(admin_user_id)` — that
--      column doesn't exist (shared.admin_users' real PK is `id`, not `admin_user_id` — migration
--      074). More importantly, this app's real "who did this" convention for admin mutations
--      (api/routers/admin_a4.py::force_unpublish, AA-455) is the `x-admin-user-id` header value
--      formatted as `"admin:<id-or-unknown>"`, a free-text string, not a FK-checked admin_users
--      row — matched here for consistency rather than introducing a new, stricter convention.
--   3. content_piece_id / angle_gate_request_id are plain nullable UUID, no FK constraint. A log
--      row must never fail to insert because its parent content_piece/angle_gate_request row was
--      concurrently deleted (test-data cleanup, tenant offboarding) — an orphaned log row is a
--      fine, even desirable, permanent cost/quality record; a dropped log write is not.

CREATE TABLE IF NOT EXISTS shared.llm_role_config (
    stage         TEXT PRIMARY KEY,
    role          TEXT NOT NULL CHECK (role IN ('writer', 'judge', 'validate')),
    provider      TEXT NOT NULL CHECK (provider IN ('claude', 'openai')),
    model_id      TEXT NOT NULL,
    -- Claude (writer/validate) stages only: which satellite account LLMClient/invoke_claude()
    -- tries FIRST ('acc3' | 'acc1'). NULL for openai-provider (judge) rows — no AWS account
    -- routing applies to a direct OpenAI call.
    account_route TEXT CHECK (account_route IN ('acc1', 'acc3') OR account_route IS NULL),
    is_active     BOOLEAN NOT NULL DEFAULT true,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by    TEXT NOT NULL DEFAULT 'system-seed-aa518'
);

COMMENT ON TABLE shared.llm_role_config IS
    'AA-518 Việc C — admin-only (aa_internal), per-call-site model selection. Read (cached, '
    'short in-process TTL) by shared/llm_client/role_config.py, written by PATCH '
    '/admin/llm-config/{stage}. is_active=false rows are ignored by the reader and fall back to '
    'the code-level SAFE_DEFAULTS for that stage — a bad UI save can never brick the pipeline.';

CREATE TABLE IF NOT EXISTS shared.llm_call_log (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID REFERENCES shared.tenants(tenant_id),  -- NULL for A-series (aa_internal)
    stage                  TEXT NOT NULL,
    role                   TEXT NOT NULL CHECK (role IN ('writer', 'judge', 'validate')),
    model                  TEXT NOT NULL,   -- the ACTUAL model_used this call (e.g.
                                             -- "satellite-us.anthropic...", not just "sonnet")
    tokens_in              INTEGER,
    tokens_out             INTEGER,
    cost_usd               NUMERIC(10, 6),
    -- Required on every insert (AA-518/AA-505 decision, 02/09/2026 S171): a real judge score/
    -- gate-pass result where one exists, else a real, computed-not-fabricated heuristic. See
    -- AA-518.md's per-stage quality_signal table for what each stage actually logs and why.
    quality_signal         JSONB NOT NULL,
    content_piece_id       UUID,
    angle_gate_request_id  UUID,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_llm_call_log_stage_created ON shared.llm_call_log(stage, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_call_log_tenant_created ON shared.llm_call_log(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_call_log_model_created ON shared.llm_call_log(model, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_call_log_piece ON shared.llm_call_log(content_piece_id) WHERE content_piece_id IS NOT NULL;

COMMENT ON TABLE shared.llm_call_log IS
    'AA-505 — one row per real LLM call, replacing the compute-then-discard pattern AA-434 '
    'documented. Written by shared/llm_client/call_log.py from every one of the 16 confirmed '
    'call sites (see AA-518.md). tenant_id NULL = an A-series (aa_internal) admin call.';

-- Seed — 16 rows, one per real call site confirmed in AA-518.md's STEP0 (round 3, 02/09/2026).
-- Every value below matches what the code actually does TODAY exactly (grep'd, not guessed) —
-- EXCEPT t5_atomize's account_route, called out below — so applying this migration changes zero
-- production behavior by itself until an admin touches the new UI.
INSERT INTO shared.llm_role_config (stage, role, provider, model_id, account_route, updated_by) VALUES
    -- S1 rewrite graph (services/content_generation/graph.py + its 4 node files) — shared by
    -- admin A1 batch-rewrite AND tenant T2 self-service rewrite (same code, see header above).
    ('s1_generate',         'writer',   'claude', 'haiku',   'acc3', 'system-seed-aa518'),
    ('s1_judge',            'judge',    'openai', 'gpt-4.1', NULL,   'system-seed-aa518'),
    ('s1_brand_audit',      'judge',    'openai', 'gpt-4.1', NULL,   'system-seed-aa518'),
    ('s1_flag_fix',         'writer',   'claude', 'haiku',   'acc3', 'system-seed-aa518'),
    ('s1_itinerary_nudge',  'writer',   'claude', 'haiku',   'acc3', 'system-seed-aa518'),
    -- S1's atom-based writer (services/content_generation/s1_from_atom.py) — Mechanism B, direct
    -- invoke_claude(), NOT part of the graph above.
    ('s1_atom_writer',      'writer',   'claude', 'sonnet',  'acc3', 'system-seed-aa518'),
    -- T8/T9 (services/acp_angle_gate, services/acp_content_writing) — tenant-facing, ADR-2026-038
    -- §0.5 fresh-build packages, Mechanism A.
    ('t8_angle_gen',        'writer',   'claude', 'sonnet',  'acc3', 'system-seed-aa518'),
    ('t9_write',            'writer',   'claude', 'sonnet',  'acc3', 'system-seed-aa518'),
    ('t10_judge',           'judge',    'openai', 'gpt-4.1', NULL,   'system-seed-aa518'),
    -- T5 atomize (services/acp_produce/tenant_pipeline.py) — Mechanism B. account_route='acc3'
    -- here is a DELIBERATE correction, not a like-for-like seed: the real code today omits
    -- `account=` entirely and silently falls back to invoke_claude()'s own default ('acc1') —
    -- flagged as unintentional drift in AA-518.md round 2 (every sibling Mechanism-B call site
    -- passes account="acc3" explicitly). Folded the fix in here since this task already touches
    -- this exact call site to wire config + persist-log — see AA-518.md "Changed" for the one-
    -- line code diff this seed corresponds to.
    ('t5_atomize',          'writer',   'claude', 'sonnet',  'acc3', 'system-seed-aa518'),
    -- N7 production pipeline (services/acp_produce/{generation,adapt,faq,repair,research,gates}.py)
    -- — Mechanism B (writer calls) + judge_client.py (F8/F9 judge calls).
    ('n7_draft',            'writer',   'claude', 'sonnet',  'acc3', 'system-seed-aa518'),
    ('n7_adapt',            'writer',   'claude', 'sonnet',  'acc3', 'system-seed-aa518'),
    ('n7_faq',              'writer',   'claude', 'sonnet',  'acc3', 'system-seed-aa518'),
    ('n7_repair',           'writer',   'claude', 'sonnet',  'acc3', 'system-seed-aa518'),
    ('n7_gap_research',     'validate', 'claude', 'haiku',   'acc3', 'system-seed-aa518'),
    ('n7_judge',            'judge',    'openai', 'gpt-4.1', NULL,   'system-seed-aa518')
ON CONFLICT (stage) DO NOTHING;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES (137, now(), 'llm_role_config + llm_call_log — AA-518 Việc C per-stage model config + AA-505 cost/quality log')
ON CONFLICT DO NOTHING;
