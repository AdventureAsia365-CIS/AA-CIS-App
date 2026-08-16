"""
tests/integration/test_aa412_produce_history_piece_review.py — AA-412's two new
read paths (GET .../packets/{id}/pieces, GET .../produce/runs) plus the
per-piece review write path (POST .../pieces/{id}/review) and the review-gate
on POST .../packets/{id}/gate-c/approve — exercised against the REAL schema
(all migrations applied by conftest.py's `_setup_schema`, including this
issue's own migration 105), not a mocked pool. Uses `db_conn` (psycopg2, the
existing fixture) to seed rows and a real `asyncpg` pool (same local
`cis_integration_test` DB, no live AWS RDS needed — the harness has no
credentials for that here) to exercise the actual admin_produce.py route
functions end-to-end, including the real `jsonb_to_recordset()` gate_summary
SQL in list_produce_runs().

Test data is shaped after the real N7 run #6 gate_ledger
(docs/claude_audit/AA-404-n7-run6-results.md — F1_grounding/F5_atom_density/
F9_brand_seo_audit, the same 3 gates that report's Step 4 discusses) rather
than reusing that run's literal row, since this session has no live DB
connection to pull it from (AWS is stopped, see repo CLAUDE.md) — the report
only publishes 8-char run_id prefixes, not full UUIDs, so the exact row can't
be re-addressed anyway. `run_id` below embeds that same 8-char prefix
(`d0722ae3`) so this test's provenance is traceable back to that report.
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest
import pytest_asyncio

# tests/integration/ has no __init__.py, so the repo root is never on sys.path here — api.*
# isn't importable without this. Same fix, same place, as
# test_compiled_graph_state_propagation.py's own module-level comment explains (conftest.py's
# sys.path.insert(0, dirname(__file__)) only covers this directory, for `_constants`).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from api.routers import admin_produce  # noqa: E402 — must follow the sys.path fix above

DB_HOST = os.environ.get("CIS_TEST_DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("CIS_TEST_DB_PORT", "5432"))
DB_NAME = os.environ.get("CIS_TEST_DB_NAME", "cis_integration_test")
DB_USER = os.environ.get("CIS_TEST_DB_USER", "cistest")
DB_PASS = os.environ.get("CIS_TEST_DB_PASS", "cistest")

TENANT_ID = "00000000-0000-0000-0000-000000000001"
# Traceable back to docs/claude_audit/AA-404-n7-run6-results.md's run #6 — see module docstring.
RUN_ID = "d0722ae3-0000-0000-0000-000000000006"


class _FakeRequest:
    """Minimal stand-in for FastAPI's Request — admin_produce.py route
    functions only ever read `request.app.state.pool`."""
    class _App:
        class _State:
            pool = None
        state = _State()
    app = _App()


@pytest_asyncio.fixture
async def apg_pool():
    pool = await asyncpg.create_pool(
        host=DB_HOST, port=DB_PORT, database=DB_NAME, user=DB_USER, password=DB_PASS,
        min_size=1, max_size=2,
    )
    yield pool
    await pool.close()


@pytest.fixture
def seeded_run(db_conn):
    """Seeds one real-shaped run: acp_shared.acp_v2_runs + acp_deliver.packets +
    2 acp_deliver.pieces (1 held on F1+F5, 1 passed clean) — enough to exercise
    every new endpoint's real SQL. Cleans up its own rows on teardown (these 3
    tables aren't in db_conn's own TRUNCATE list)."""
    cur = db_conn.cursor()
    packet_id = str(uuid.uuid4())
    piece_held = f"{RUN_ID}:slot_a:blog"
    piece_passed = f"{RUN_ID}:slot_b:blog"

    cur.execute(
        """
        INSERT INTO acp_shared.acp_v2_runs (run_id, tenant_id, year, month, week, status, created_at, completed_at)
        VALUES (%s, %s, 2026, 9, 2, 'completed', %s, %s)
        """,
        (RUN_ID, TENANT_ID, datetime(2026, 8, 16, 2, 45, 2, tzinfo=timezone.utc),
         datetime(2026, 8, 16, 2, 45, 2, tzinfo=timezone.utc)),
    )
    cur.execute(
        "INSERT INTO acp_deliver.packets (packet_id, tenant_id, year, month, week) VALUES (%s, %s, 2026, 9, 2)",
        (packet_id, TENANT_ID),
    )

    held_ledger = json.dumps([
        {"gate": "F1_grounding", "passed": False,
         "violations": ["sentence states ['400'] not present in its cited id(s)"]},
        {"gate": "F5_atom_density", "passed": False,
         "violations": ["words 600-900: zero atom/fact citations in this stretch"]},
        {"gate": "F9_brand_seo_audit", "passed": True, "violations": []},
    ])
    passed_ledger = json.dumps([
        {"gate": "F1_grounding", "passed": True, "violations": []},
        {"gate": "F5_atom_density", "passed": True, "violations": []},
        {"gate": "F9_brand_seo_audit", "passed": True, "violations": []},
    ])
    audit_json = json.dumps({"brand_voice_score": 7, "notes": "concrete, on-brand"})

    cur.execute(
        """
        INSERT INTO acp_deliver.pieces
            (piece_id, run_id, tenant_id, slot_id, channel, body_tagged, status,
             gate_ledger, brand_seo_audit, held_reason, packet_id)
        VALUES (%s, %s, %s, 'slot_a', 'blog', %s, 'held', %s, %s, %s, NULL)
        """,
        (piece_held, RUN_ID, TENANT_ID, "## South Korea bike trip\nReal draft body.",
         held_ledger, None, "F1_grounding: sentence states ['400'] not present..."),
    )
    cur.execute(
        """
        INSERT INTO acp_deliver.pieces
            (piece_id, run_id, tenant_id, slot_id, channel, body_tagged, status,
             gate_ledger, brand_seo_audit, packet_id)
        VALUES (%s, %s, %s, 'slot_b', 'blog', %s, 'passed', %s, %s, %s)
        """,
        (piece_passed, RUN_ID, TENANT_ID, "## Yeongdo Island cycling\nReal passed body.",
         passed_ledger, audit_json, packet_id),
    )
    db_conn.commit() if not db_conn.autocommit else None

    yield {"run_id": RUN_ID, "packet_id": packet_id, "piece_held": piece_held, "piece_passed": piece_passed}

    cur.execute("DELETE FROM acp_deliver.pieces WHERE run_id = %s", (RUN_ID,))
    cur.execute("DELETE FROM acp_deliver.packets WHERE packet_id = %s", (packet_id,))
    cur.execute("DELETE FROM acp_shared.acp_v2_runs WHERE run_id = %s", (RUN_ID,))
    cur.close()


def _request(pool):
    req = _FakeRequest()
    req.app.state.pool = pool
    return req


_TEST_SECRET = "aa412-integration-secret"


@pytest.fixture(autouse=True)
def _admin_secret(monkeypatch):
    monkeypatch.setattr("api.routers.admin.ADMIN_SECRET", _TEST_SECRET)


@pytest.mark.asyncio
async def test_list_produce_runs_real_schema(seeded_run, apg_pool):
    """GET /produce/runs against the real DB — including the actual
    jsonb_to_recordset() gate_summary query, never exercised by the mocked
    unit tests."""
    runs = await admin_produce.list_produce_runs(_request(apg_pool), _TEST_SECRET)

    run = next(r for r in runs if r["run_id"] == seeded_run["run_id"])
    assert run["tenant_id"] == TENANT_ID
    assert run["year"] == 2026 and run["month"] == 9 and run["week"] == 2
    assert run["piece_count"] == 2
    assert run["passed_count"] == 1
    assert run["held_count"] == 1
    assert run["gate_summary"]["F1_grounding"] == {"passed": 1, "failed": 1}
    assert run["gate_summary"]["F5_atom_density"] == {"passed": 1, "failed": 1}
    assert run["gate_summary"]["F9_brand_seo_audit"] == {"passed": 2, "failed": 0}


@pytest.mark.asyncio
async def test_list_packet_pieces_real_body_and_ledger(seeded_run, apg_pool):
    """GET /packets/{id}/pieces reads real `body_tagged`/`gate_ledger`/
    `brand_seo_audit` from acp_deliver.pieces — the exact gap AA-412 exists
    to close (previously 0 routes returned body_tagged at all)."""
    pieces = await admin_produce.list_packet_pieces(seeded_run["packet_id"], _request(apg_pool), _TEST_SECRET)

    assert len(pieces) == 1  # only the passed piece was assigned to a packet — matches assemble_packet()'s own rule
    piece = pieces[0]
    assert piece["piece_id"] == seeded_run["piece_passed"]
    assert "Yeongdo Island" in piece["body_tagged"]
    assert piece["gate_ledger"][0] == {"gate": "F1_grounding", "passed": True, "violations": []}
    assert piece["brand_seo_audit"] == {"brand_voice_score": 7, "notes": "concrete, on-brand"}
    assert piece["review_status"] == "pending"


@pytest.mark.asyncio
async def test_packet_pieces_404_for_unknown_packet(apg_pool):
    with pytest.raises(Exception) as exc:
        await admin_produce.list_packet_pieces(str(uuid.uuid4()), _request(apg_pool), _TEST_SECRET)
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_review_then_gate_c_approve_real_flow(seeded_run, apg_pool):
    """End-to-end real flow: reviewing the one piece in the packet flips
    review_status in the real table, and only THEN does
    POST .../gate-c/approve succeed for a mode past 'propose_only' — before
    review, it must 409 without ever calling confirm_ramp_transition()."""
    packet_id = seeded_run["packet_id"]
    piece_id = seeded_run["piece_passed"]

    blocked = admin_produce.GateCApproveRequest(mode="approve_to_publish", actor="qa-integration")
    with pytest.raises(Exception) as exc:
        await admin_produce.approve_gate_c(packet_id, blocked, _request(apg_pool), _TEST_SECRET)
    assert getattr(exc.value, "status_code", None) == 409

    review_body = admin_produce.PieceReviewRequest(decision="approve", actor="qa-integration", note="verified body")
    result = await admin_produce.review_piece(piece_id, review_body, _request(apg_pool), _TEST_SECRET)
    assert result == {"piece_id": piece_id, "review_status": "approved"}

    row = await apg_pool.fetchrow(
        "SELECT review_status, reviewed_by, review_note FROM acp_deliver.pieces WHERE piece_id = $1", piece_id,
    )
    assert row["review_status"] == "approved"
    assert row["reviewed_by"] == "qa-integration"
    assert row["review_note"] == "verified body"

    approved = admin_produce.GateCApproveRequest(mode="approve_to_publish", actor="qa-integration")
    outcome = await admin_produce.approve_gate_c(packet_id, approved, _request(apg_pool), _TEST_SECRET)
    assert outcome["status"] == "transitioned"

    publish_mode = await apg_pool.fetchval(
        "SELECT publish_mode FROM acp_deliver.packets WHERE packet_id = $1", packet_id,
    )
    assert publish_mode == "approve_to_publish"
