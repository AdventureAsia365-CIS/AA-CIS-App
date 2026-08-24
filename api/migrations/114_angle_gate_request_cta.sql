-- Migration 114: AA-450 — add `cta` to acp_shared.angle_gate_request (T8 build gap, STEP0
-- AA-450-00 §6 / build task §3).
--
-- SKILL_v2.md requires CTA as a hard input to writing final content (Human-In-The-Loop
-- Workflow step 4: "Ask for the specific CTA before generating angles") and the one real
-- prior writer (services/acp_s4_social/brief.py::ContentBrief.validate_anchors()) refuses to
-- run without one — but T8 (AA-449, migration 113) never added a cta column, and never wired
-- services/acp_planning/models.py::Slot.cta_target (already computed by T7's N6 allocator)
-- into angle_gate_request creation. Nullable by design — does not break the 113 rows that
-- already exist (their `cta` starts NULL, same "no migration needed, handled by the reader"
-- shape acp_contract.tour_atoms.owner_scope used at ADR-2026-038 Hướng B).
--
-- IMPORTANT, confirmed by reading the real call path (not assumed): the wiring this migration
-- enables (services/acp_angle_gate/service.py::create_request(), edited alongside this file)
-- looks up acp_shared.acp_v2_slots for a slot matching (tenant_id, channel, atom_id) and reads
-- its payload->>'cta_target'. That table is confirmed POPULATED ONLY by admin-triggered N7
-- paths (admin_atoms.py/admin_produce.py, both via allocate_month_from_db()) — T7's own real
-- tenant-facing endpoint (api/routers/v1_planning.py::get_slot_grid()) calls
-- compute_slot_grid() and returns the grid directly in the HTTP response, it NEVER calls
-- persist_slot_grid(). So for a tenant going through the real, current self-service T7->T8
-- flow, this lookup will realistically find nothing and `cta` will stay NULL even after this
-- fix — not just for the 113 pre-existing rows, but for new ones too, until either T7's preview
-- endpoint starts persisting slots or some other real source of a per-atom CTA exists. This is
-- flagged prominently in docs/implementation-notes/AA-450-t9-content-writing.md — the T9 write
-- endpoint (services/acp_content_writing/) is built to require a tenant-supplied `cta` in the
-- write request body whenever this column is NULL, rather than silently fabricating one.

BEGIN;

ALTER TABLE acp_shared.angle_gate_request ADD COLUMN IF NOT EXISTS cta TEXT;

COMMENT ON COLUMN acp_shared.angle_gate_request.cta IS
    'AA-450: the CTA for this request''s eventual T9 write. Sourced from services.acp_planning.'
    'models.Slot.cta_target (acp_shared.acp_v2_slots.payload) when a matching persisted slot '
    'exists at request-creation time (services/acp_angle_gate/service.py::create_request()); '
    'realistically NULL for most real tenant self-service requests today, since T7''s own '
    'tenant-facing endpoint never persists its computed SlotGrid — see this migration''s header '
    'comment. NULL is a legitimate, expected value, not only a pre-migration artifact; T9''s '
    'write endpoint requires a tenant-supplied cta in its own request body when this is NULL.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('114', now(),
    'AA-450: acp_shared.angle_gate_request.cta (nullable) — closes the T8 CTA gap STEP0 found; '
    'realistically stays NULL for most self-service requests since T7''s tenant endpoint never '
    'persists slots (see header comment) — T9''s write endpoint has its own fallback')
ON CONFLICT (version) DO NOTHING;

COMMIT;
