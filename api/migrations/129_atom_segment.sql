-- Migration 129: AA-509 — acp_contract.tour_atoms.place/action + atom_segment/
-- atom_segment_member/atom_segment_alias.
--
-- STEP0 (docs/claude_audit/AA-509-step0-schema-matching-investigation.md) found tour_atoms has
-- no place/action split — one combined `text` field + a coarse `activity_type` enum — which the
-- reference repo's grouping algorithm (aa-social-media src/aa_social/segments.py) fundamentally
-- needs (Jaccard on `place`, verb-match on `action`). Build prompt chose Hướng A: T5 decompose
-- now asks the LLM for `place`/`action` separately (services/acp_shared/atom_extraction.py
-- SYSTEM_PROMPT). `text` stays (NOT dropped) — it is read directly by score_distinctiveness(),
-- T9's content_seed, N7 research H2 titles, slot_runner, angle_gate service (grep-confirmed,
-- see implementation notes Decision 1) — now derived as f"{place} — {action}" instead of an
-- LLM-written free sentence.
--
-- place/action are nullable: no backfill, same precedent as migration 093's itinerary_day
-- ("chỉ atom decompose từ migration này trở đi có giá trị") — an atom atomized before this
-- migration keeps place/action NULL until its day is next re-atomized (SYSTEM_PROMPT change
-- auto-invalidates every existing day_fingerprint row, so this happens automatically on the
-- next atomize call, not never — see implementation notes "Live Verify" step 1).

BEGIN;

ALTER TABLE acp_contract.tour_atoms
    ADD COLUMN place  TEXT NULL,
    ADD COLUMN action TEXT NULL;

COMMENT ON COLUMN acp_contract.tour_atoms.place IS
    'AA-509 — the place as the itinerary names it (T5 decompose, SYSTEM_PROMPT). NULL for atoms '
    'read before this migration, until their day is next re-atomized.';
COMMENT ON COLUMN acp_contract.tour_atoms.action IS
    'AA-509 — the activity at that place, short verb phrase (T5 decompose, SYSTEM_PROMPT). NULL '
    'for atoms read before this migration, until their day is next re-atomized.';

-- atom_segment rows are APPEND/UPDATE-ONLY, never deleted by segment_matching.py — required by
-- atom_segment_alias's own FK below: when two Segments merge, the id that gives way is recorded
-- as an alias (ADR 0002, Ms. Thư repo — "the id that gave way is recorded as an alias, so a
-- Calendar row built on it still resolves"), which only typechecks if that old segment_id STILL
-- EXISTS as a row here. segment_matching.py fully rebuilds atom_segment_member (membership is
-- derived, cheap to recompute) but only ever UPSERTs atom_segment, never DELETEs it — see
-- implementation notes Decision 3 for the full reasoning (this diverges from the SQLite reference
-- repo's own DELETE-then-reinsert of its `segments` table, which has no such FK to violate).
--
-- segment_id itself is derived from (tenant_id, canonical place, canonical verb) — tenant_id
-- included in the hash (services/acp_contract/segment_matching.py::_mint()) though ADR 0002's own
-- formula doesn't have it, same reasoning AA-508 already established for tour_atoms.atom_id
-- (Decision 2, docs/implementation-notes/AA-508.md): without it, two tenants both describing
-- "walk the Nakasendo trail" would collide on one PK row.
CREATE TABLE acp_contract.atom_segment (
    segment_id       TEXT PRIMARY KEY,
    tenant_id        UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    canonical_place  TEXT NOT NULL,
    canonical_action TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_atom_segment_tenant ON acp_contract.atom_segment(tenant_id);

CREATE TABLE acp_contract.atom_segment_member (
    segment_id  TEXT NOT NULL REFERENCES acp_contract.atom_segment(segment_id),
    atom_id     TEXT NOT NULL REFERENCES acp_contract.tour_atoms(atom_id),
    is_alias    BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (segment_id, atom_id)
);

CREATE INDEX idx_atom_segment_member_atom ON acp_contract.atom_segment_member(atom_id);

-- Segment-level alias (old segment_id -> the id it merged into) — distinct from
-- atom_segment_member.is_alias above (STEP0 flagged this as an open semantics question; kept
-- as an unused reserved column per the build prompt's literal schema, not populated by
-- segment_matching.py, which only writes this table for id resolution at the SEGMENT level,
-- matching aa_social.segments.reconcile_ids()'s actual mechanism).
CREATE TABLE acp_contract.atom_segment_alias (
    segment_id_old        TEXT PRIMARY KEY REFERENCES acp_contract.atom_segment(segment_id),
    segment_id_canonical  TEXT NOT NULL REFERENCES acp_contract.atom_segment(segment_id),
    merged_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('129', now(),
    'AA-509: tour_atoms.place/action + acp_contract.atom_segment/atom_segment_member/'
    'atom_segment_alias — deterministic Segment grouping ported from aa-social-media')
ON CONFLICT (version) DO NOTHING;

COMMIT;
