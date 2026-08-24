# AA-449 — T8 Angle Gate (build)

Follows `docs/claude_audit/AA-449-00-step0-t8-angle-gate-investigation.md` (STEP0, both rounds,
merged before build started — not re-derived here) and the round-2 build task saved at
`docs/claude_tasks/AA-449-01-build-t8-angle-gate.md`.

## Decisions

1. **Terminology (build task §1): "Goal" for the 8-value Bang-1 list, "Angle" only for the 3
   LLM-generated options.** `services/acp_angle_gate/goals.py` (`Goal` TypedDict, `key` field) is
   the Goal tier; the 3-per-request options are `AngleOption`/`angle_gate_option` rows. No file
   in this build uses the word "angle" for a goal, or "goal" for an angle option.

2. **Bang 1's own wording kept verbatim, including STEP0's 2 flagged discrepancies** (header said
   "7 loại" but lists 8; Conversion's SLAP expands "Purchase" here vs. SKILL_v2.md's own
   "Proceed") — the build task re-supplied Bang 1 unchanged and didn't ask for either correction,
   so `goals.py` uses Bang 1's exact `logic`/`marketing_term` strings, not SKILL_v2.md's. If
   Nghiep decides otherwise later, only `goals.py` needs editing — nothing downstream reads those
   specific words structurally, they only get interpolated into the LLM prompt.

3. **Channel extension: 4 -> 8 values, not 4 -> 7.** Bang 2 has 7 channels; "blog" (already a
   Slot.channel value from T7) has no Bang-2 row at all (STEP0 §5 flagged this). Kept "blog" for
   backward compat per the build task's own explicit regression requirement ("4 channel cũ vẫn
   hoạt động y hệt như trước") — added a new, self-authored fallback style entry for it in
   `channel_style.py`, clearly marked as not from Bang 2.

4. **n_atoms-per-slot grouping for the 4 new channels (`allocator.py`) — self-chosen from Bang
   2's own Structure column, not specified anywhere.** linkedin/instagram/ads join
   facebook/tiktok in the existing 1-atom group (all single-hook/single-idea formats per Bang 2's
   structure descriptions); landing_page joins blog/email in the up-to-4-atom group (Bang 2's own
   structure for it is explicitly multi-section). Same class of "self-chosen, documented inline"
   caveat this file's other constants already carry (THIN_TRIP_MAX_SHARE, ENGAGEMENT_RATE_BASELINE).

5. **LLM layer: `shared.llm_client.client.LLMClient` (model_tier="sonnet"), not
   `bedrock_satellite.invoke_claude` or Nova Pro judge_client.py.** Per the build task's explicit
   "đúng exclusive LLM layer đã chốt" — matched against `services/content_generation/graph.py`'s
   `generate_node()`, which does the same *kind* of job (one content-strategy LLM call returning
   structured JSON) and already uses this exact client. `acp_produce/generation.py`'s
   Bedrock-satellite-acc1-Sonnet-only path is a separate, AA-334-specific decision for long-form
   draft writing (a different job); `judge_client.py`'s Nova Pro is a cross-vendor QUALITY judge
   that must never share a model with any writer (ADR-2026-014/027) — neither applies here.

6. **JSON parsing: strip-fences -> `json.loads` -> `json_repair` salvage, same pattern
   `generate_node()` uses** — not a new parsing strategy. `AngleGenerationError` (new) is raised
   only when even the salvage can't produce exactly 3 valid angles with all 4 required fields; the
   request stays at `status='pending_goal'` (nothing partial gets written) so the tenant can
   retry without a fresh `request_id`.

7. **"Fixed brand audience" source: `shared.tenant_brand_rules.customer_segment` +
   `.customer_mindset`, read directly (new query, `brand_audience.py`) — not `core_idea`/
   `brand_type`, not the full `system_prompt`.** STEP0 §6 found the columns; this build is the
   first tenant-facing read of them (BrandTab.tsx's own `GET /api/tenant/admin/brand-identity`
   response never exposed them, only bakes them into `system_prompt` prose). `segment` = who they
   are, `mindset` = what they think/want — the 2 fields an angle-generation prompt actually needs
   to write TO someone; `brand_type`/`core_idea` describe the brand itself, not the audience, so
   left out.

8. **No new atom-listing endpoint for the frontend picker.** `AngleGateTab.tsx` reuses
   `GET /api/tenant/admin/atoms` (already built for T6's `AtomsTab.tsx`) rather than adding a
   second tenant-scoped atom-listing route — same data, same tenant-scoping mechanism
   (`owner_scope` resolved server-side from the JWT), no reason to duplicate it.

9. **Single-atom tenant-scoped fetch (`service.py::_fetch_atom_for_tenant`) kept local to this
   package, not added to `services/acp_planning/tenant_pool.py`.** `tenant_pool.py` only has a
   "fetch ALL of a tenant's atoms, grouped by trip" function (T7's own need); T8 needs "fetch ONE
   atom by id, tenant-scoped" — a genuinely different query shape, T8-specific, so it lives in
   `services/acp_angle_gate/service.py` instead of extending a T7 module for a T8 need.

## Changed

- **New migration**: `api/migrations/113_acp_shared_angle_gate.sql` — `acp_shared.angle_gate_request`
  (RLS enabled, matching migration 112's `content_metric_snapshot` precedent) +
  `acp_shared.angle_gate_option` (child table, no RLS — matches `quarter_plan_version`'s own
  precedent, migration 092: tenant isolation enforced at the API layer via the parent's
  `request_id`, not a second policy). **Applied live** — see Live Verify below.
- **New package**: `services/acp_angle_gate/` — `goals.py`, `channel_style.py`,
  `brand_audience.py`, `prompts.py`, `generate.py`, `service.py`. No import from
  `services.acp_s4_social` anywhere (ADR-2026-038 §0.5 — "viết mới hoàn toàn").
- **New router**: `api/routers/v1_angle_gate.py` (5 endpoints, tenant-JWT-only via
  `api.routers.v1_tours.get_tenant`) + registered in `api/main.py`.
- **Edited (T7's channel extension, build task §2)**:
  - `services/acp_planning/models.py` — `Channel` Literal 4 -> 8 values.
  - `services/acp_planning/constants.py` — 4 new `FRAMEWORK_TABLE` `("ANY", channel)` entries.
  - `services/acp_planning/allocator.py` — `n_atoms` grouping extended to the 3 new 1-atom
    channels (see Decision 4).
  - `api/routers/admin.py` — `_VALID_CHANNELS` (the `PUT /admin/tenants/{id}/config` validator)
    extended to the same 8 values.
  - `frontend/app/admin/tenants/page.tsx` — `ALL_CHANNELS` (the admin channel-picker checkboxes)
    extended to the same 8 values.
- **New frontend**: `frontend/app/(tenant)/portal/t8-angle-gate/page.tsx`,
  `.../_components/AngleGateTab.tsx` (atom+channel picker -> goal picker -> 3-angle cards with a
  Choose button) — `Sidebar.tsx`/`layout.tsx` nav+breadcrumb entries added right after T7
  "Content Planning", per the build task's own placement instruction.
- **New tests**: `test_aa449_channel_extension.py` (23 — the "test bắt buộc" for the channel
  extension: all 8 channels don't crash, original 4 unchanged, new 4 get sensible frameworks),
  `test_aa449_angle_gate_generate.py` (8 — LLM JSON parsing/validation, LLMClient patched),
  `test_aa449_angle_gate_service.py` (11 — DB lifecycle/state-machine, mocked pool),
  `test_aa449_v1_angle_gate.py` (11 — router HTTP-status mapping). 53 new tests, all passing;
  full existing suite re-run clean (1499 passed, 1 pre-existing skip, 0 new failures); flake8
  clean; `npx tsc --noEmit` + `npx eslint` clean on every changed/new frontend file (the pattern
  eslint errors in `admin/tenants/page.tsx` and 1 `no-explicit-any` in `layout.tsx` are
  pre-existing, confirmed against unmodified `origin/main` before attributing anything to this
  change — same check AA-448's own notes already did for the `layout.tsx` one).

## Tradeoffs

- Decision 4 (n_atoms grouping) and the 4 new `FRAMEWORK_TABLE` entries are both self-chosen —
  Bang 2 describes structure/style/avoid per channel but never says how many atoms a slot on that
  channel should draw from, or names a machine-readable "framework" string. Flagged the same way
  this file's sibling constants already are, not silently invented.
- `angle_gate_option`'s `formula_fit` field can end up nearly identical across all 3 angles of one
  request whenever the chosen goal only maps to a single formula (e.g. Promotion -> AIDA only) —
  STEP0 §6/round-2 open question #5 already flagged this as unresolved by any source; not solved
  here, the field is built exactly as asked (LLM decides per-angle wording) and left as-is.
- No timeout on `pending_choice` (build task §3, explicit "KHÔNG giới hạn thời gian" decision) —
  `created_at` is kept on `angle_gate_request` specifically so a future timeout can read the row's
  age without a schema change, per that same instruction.

## Should know

- **Real environment finding from live-verify, not a code bug**: no tenant in the live DB
  currently has BOTH real `owner_scope` atoms AND a populated `customer_segment` at the same time
  — the migration-018 seed tenants (atlas-hearth, terra-family-expeditions, trail-pulse,
  wildkind-travel) with rich audience data have 0 atoms; atom-having tenants (test-n1-flow,
  test-agency) have no audience data. `fetch_brand_audience()`'s graceful-None path was the one
  actually exercised live (confirmed correct); the "real audience data reaches the prompt" path is
  covered by a mocked-data unit test instead
  (`test_aa449_angle_gate_generate.py::test_brand_audience_and_goal_reach_the_prompt`), not live.
- **Real live Bedrock fallback observed, not simulated**: native acc2 Sonnet 4.5
  (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`) returned
  `ValidationException: ...not available for channel program accounts...` during live-verify —
  `LLMClient` correctly fell through to the acc3 Bedrock satellite (T1.5a), which succeeded
  (`cost_usd=0.020229`). This is the documented fallback chain working for real, not a bug in
  this build — flagged here so a future session doesn't mistake the acc2 warning line in logs for
  something AA-449 broke.
- `Slot.Channel`'s Literal and `api/routers/admin.py::_VALID_CHANNELS` and
  `frontend/app/admin/tenants/page.tsx::ALL_CHANNELS` are 3 separate lists that must be kept in
  sync manually (no shared source of truth across Python/TypeScript) — `test_aa449_channel_
  extension.py::test_channel_literal_has_exactly_eight_values` pins the Python-side value set as
  a tripwire, but does not check the other 2 files.
- `AngleGateTab.tsx`'s atom picker shows ALL of a tenant's non-deleted curated atoms (up to 100),
  not filtered by which `Slot`/channel a T7 plan actually scheduled them for — this build's own
  API (`create_request(atom_id, channel)`) takes both as free-standing inputs, it does not require
  or reference a real `slot_id` from T7's `SlotGrid`. Wiring "start a T8 request directly from a
  specific T7 slot" (so `channel` is pre-filled and constrained to what T7 actually planned) is a
  real UX gap, not built here — out of this task's explicit scope ("Redesign UI Marketplace/
  Content Planning hiện có").

## Live Verify (real AWS access, `aa365-admin` session already authenticated this session)

Pre-merge — same S3-mediated ECS exec pattern + pre-merge "overwrite the changed .py files
directly onto the running `aa-cis-dev-api` container's disk" precedent AA-431/AA-448 established
(does not restart uvicorn, does not affect real traffic served by the old in-memory code).
ECS (`aa-cis-dev-cluster`/`aa-cis-dev-api`, task def `:129`) and RDS (`aa-cis-dev-db`) both
confirmed already running before starting (not started by this session).

1. **Migration 113 applied live** — `shared.schema_versions` confirms `version='113'`,
   `applied_at=2026-08-23T18:38:38Z`.
2. **Full lifecycle, real tenant (`test-n1-flow`, `6fbaf284-e3cd-4b4b-b53b-c9a04e8fae8e`), real
   atom (`atom_0e9a4a62ed`, real Southern Laos waterfall content)**:
   - `create_request(atom_id, channel="linkedin")` -> `status="pending_goal"`.
   - `set_goal_and_generate(goal="promotion")` -> real Bedrock call (see "Should know" for the
     acc2->acc3 fallback) -> 3 real angles, all 4 fields populated on each, exactly 1
     `recommended=true` -> `status="pending_choice"`. The LLM's own output was grounded and
     honest about the atom's limits (one angle's `best_final_style` explicitly noted "the content
     seed... does not specify exact distances or heights beyond Tad Fane's provincial superlative;
     the final writer should not fabricate those figures") — not prompted for that specifically,
     an emergent effect of the system prompt's "never invent facts" instruction.
   - `choose_angle(idx=0)` -> **the response itself** (not a follow-up GET) already shows
     `status="approved"` — the exact AA-448 stale-response bug class this build was told to watch
     for, confirmed NOT repeated (`service.choose_angle()` re-fetches from the DB before
     returning, by design — see Decision/code comment).
   - Independent `fetch_request()` call (separate from the mutating call) confirms the DB agrees.
3. **Cleanup**: the one `angle_gate_request` row created (cascades to its 3 `angle_gate_option`
   rows via `ON DELETE CASCADE`) deleted in the script's own `finally` block. Independent re-check
   (same script, after cleanup): `0` remaining `angle_gate_request` rows for `test-n1-flow`.
4. **Not done this session**: true end-to-end HTTP-through-API-Gateway verification (needs the
   new router actually registered in a running uvicorn process, i.e. a real deploy) — same
   documented limitation AA-448's own notes state for this exact pre-merge situation; a post-merge
   post-deploy step for whoever merges this.

## Post-merge / post-deploy record

- **PR #204** (`feature/aa-449-build-t8-angle-gate` → `main`): all 5 required CI checks green —
  squash-merged manually by Nghiep after review (not auto-merged, per this repo's own
  migration-PR convention — carries migration 113, already applied live pre-merge so the merge
  itself touched no schema). Merge commit `8093645`.
- **Deploy Dev** (triggered by the #204 merge): green. New task def **`aa-cis-dev-api:130`**,
  service `1/1` running, single `PRIMARY` deployment, `rolloutState: COMPLETED`.
- **Real end-to-end HTTP verify, post-deploy** (first time these endpoints were reachable via
  the actual domain, not just the pre-merge function-level pass) — minted a real tenant JWT for
  `test-n1-flow` and called `https://api-cis.lumiguides.it.com` directly:
  - No `Authorization` header on `POST /v1/angle-gate/requests` → **401** — auth boundary
    intact. (`GET /v1/angle-gate/goals` returns 200 with no auth — intentional, it's a static
    list with no tenant-specific data, not an oversight.)
  - `POST /v1/angle-gate/requests` `{atom_id, channel:"linkedin"}` → **200**, real atom
    (`atom_0e9a4a62ed`), `status: pending_goal` — exercises the newly-added `linkedin` channel
    end-to-end, not just in tests.
  - `POST /v1/angle-gate/requests/{id}/goal` `{goal:"promotion"}` → **200**, real Bedrock
    Sonnet 4.5 call, 3 angles returned, all 4 fields populated on each, exactly 1
    `recommended: true`, `status: pending_choice`.
  - `POST /v1/angle-gate/requests/{id}/choose` `{idx:0}` → **200**, `status: approved` in the
    response itself. Independent follow-up `GET` → also `approved`, same chosen idx — confirms
    `choose_angle()`'s re-fetch-before-return design actually avoids AA-448's stale-response bug
    class in real HTTP traffic, not just in the mocked/function-level test.
  - Cleanup: deleted the one `angle_gate_request` row this pass created (cascade removed its 3
    `angle_gate_option` rows) — independently re-confirmed `0` remaining rows for the tenant.

### New finding this round — pre-existing, not caused by this PR

Minting the tenant JWT via the documented shortcut (`api.routers.auth._create_jwt`, in-container)
**crashed the ECS-exec SSM session outright** (`Cannot perform start session: EOF`, zero stdout,
the spawned `python3` process left as a zombie) — reproduced consistently across 6+ attempts.
Isolated the cause: importing `api.routers.auth` (or anything that pulls in the `api` package)
triggers a Sentry-DSN-from-Secrets-Manager fetch that fails (`ResourceNotFoundException` — the
secret doesn't exist in this account) and logs a warning, and something after that kills the
whole process rather than degrading gracefully. Worked around by minting the JWT with plain
PyJWT directly, using the same fallback secret `api/routers/auth.py` itself falls back to when
`JWT_SECRET` is unset (confirmed unset in this container — a real, separate finding: the dev
container is running on its hardcoded default JWT secret, not a real per-env secret). Not fixed
here — out of scope for T8, pre-existing in code this task didn't touch, and needs someone to
actually trace the Sentry init path to know if it's Sentry-specific or a coincidental red
herring. Flagging for a future ticket, not silently dropping it.
