"""AA-494 Step 2 — migration 124's own constraints, pinned as a static text test.

No live-DB migration-runner test harness exists in this repo (confirmed: `tests/` has no
fixture that applies a real .sql migration file against a throwaway DB — the many "23
pre-existing live-DB-dependent failures" noted across recent implementation-notes files are RLS
integration tests, not migration-runner tests). Matching the repo's existing convention for
DB-adjacent logic without a live connection (test_aa249_seo_context_tour_unique.py: "pin the SQL
text ... not a live-DB row-collision integration test"), these tests read the migration file's
own text and assert its CHECK constraint accepts the new value and nothing unexpected.
"""
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "api" / "migrations" / "124_content_piece_reuse_columns.sql"
)


def _migration_sql() -> str:
    return MIGRATION_PATH.read_text()


def test_migration_file_exists():
    assert MIGRATION_PATH.exists(), f"expected {MIGRATION_PATH} to exist"


def test_angle_gate_request_status_check_accepts_reusable():
    sql = _migration_sql()
    assert "CHECK (status IN ('pending_goal', 'pending_choice', 'approved', 'reusable'))" in sql


def test_angle_gate_request_status_check_still_accepts_all_pre_existing_values():
    """Migration 113's original 3 values (pending_goal/pending_choice/approved) must all still
    be accepted — this is an ADD, not a replace, of the allowed value set."""
    sql = _migration_sql()
    check_line = next(line for line in sql.splitlines() if "CHECK (status IN" in line)
    for value in ("pending_goal", "pending_choice", "approved", "reusable"):
        assert f"'{value}'" in check_line, f"{value!r} missing from the new CHECK constraint"


def test_content_piece_gains_exactly_the_four_new_columns():
    sql = _migration_sql()
    for column in ("angle_gate_option_id", "channel", "content_summary", "content_embedding"):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in sql


def test_content_embedding_dimension_matches_migration_041_precedent():
    """Must stay consistent with the one existing embedding column in this codebase (migration
    041 / AA-62, Bedrock Titan Embed Text v2 = 1536-dim) rather than guessing a different model's
    dimension — see this migration's own header comment."""
    sql = _migration_sql()
    assert "content_embedding vector(1536)" in sql


def test_angle_gate_request_channel_column_not_dropped():
    """Decision 1's schema-impact note allows either a clean drop or a deprecate-in-place; this
    migration deliberately does NOT drop angle_gate_request.channel (still load-bearing for
    create_request()/T9's CTA lookup) — guard against a future edit silently reintroducing a
    DROP COLUMN here without re-checking that live dependency."""
    sql = _migration_sql()
    assert "DROP COLUMN" not in sql.upper()
