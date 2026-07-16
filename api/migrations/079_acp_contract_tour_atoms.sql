-- Migration 079: AA-302 — acp_contract.tour_atoms (Atom schema)
--
-- Context: AA-302 (EPIC AA-297, ACP v2). Schema atom port từ aamc/models.py
-- (bản research Ms. Thư), giữ đủ 16 field, KHÔNG cắt bớt.
--
-- atom_id: TEXT PRIMARY KEY, giữ format "atom_" + uuid4().hex[:10] (không
-- đổi UUID chuẩn) — vì tag trích dẫn trong content [R:atom_id] (gate F1
-- grounding) phải khớp string này nguyên văn.
--
-- usage_log/cooldown_until: JSONB trong bảng chính, không tách bảng con ở
-- v1 — chưa có luồng sinh dữ liệu thật (N7), tách sớm là tối ưu hoá cho
-- luồng chưa tồn tại.
--
-- owner_scope: field MỚI, không có trong research (D3, họp Ms. Thư 13/07).
--
-- tour_id: UUID (không phải str tự do như research) — FK tới
-- silver_aa_internal.raw_tours(tour_id).
--
-- Không viết decompose_atoms() hay code Python nào ở migration này — chỉ
-- DB schema.

BEGIN;

CREATE TABLE acp_contract.tour_atoms (
    atom_id           TEXT PRIMARY KEY,
    tour_id           UUID NOT NULL REFERENCES silver_aa_internal.raw_tours(tour_id),
    owner_scope       TEXT NOT NULL DEFAULT 'platform',
    text              TEXT NOT NULL,
    activity_type     TEXT,
    emotional_hook    TEXT,
    visual_potential  SMALLINT NOT NULL DEFAULT 1 CHECK (visual_potential BETWEEN 1 AND 3),
    persona_fit       JSONB NOT NULL DEFAULT '[]',
    season_note       TEXT,
    distinctiveness   TEXT NOT NULL DEFAULT 'LOW' CHECK (distinctiveness IN ('HIGH','MED','LOW')),
    media             JSONB NOT NULL DEFAULT '{"has_photo": false, "has_video": false, "media_refs": []}',
    starred           BOOLEAN NOT NULL DEFAULT false,
    deleted           BOOLEAN NOT NULL DEFAULT false,
    usage_log         JSONB NOT NULL DEFAULT '[]',
    cooldown_until    JSONB NOT NULL DEFAULT '{}',
    human_seam_notes  JSONB NOT NULL DEFAULT '[]',
    weight            NUMERIC NOT NULL DEFAULT 1.0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tour_atoms_tour_id ON acp_contract.tour_atoms(tour_id) WHERE NOT deleted;
CREATE INDEX idx_tour_atoms_distinctiveness ON acp_contract.tour_atoms(distinctiveness) WHERE NOT deleted;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('079', now(), 'AA-302: acp_contract.tour_atoms — Atom schema (16 field theo aamc/models.py research + owner_scope mới D3)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
