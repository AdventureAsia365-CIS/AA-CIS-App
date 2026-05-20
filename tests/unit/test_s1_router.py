"""
Unit tests for v1_s1 — S1 Configured Rewrite Engine.
Uses mock asyncpg connections — no live DB required.
Covers: tour listing, run creation, version activation.
"""
import datetime
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _make_conn(fetchval=None, fetchrow=None, fetch=None, execute=None):
    conn = AsyncMock()
    conn.fetchval  = AsyncMock(return_value=fetchval)
    conn.fetchrow  = AsyncMock(return_value=fetchrow)
    conn.fetch     = AsyncMock(return_value=fetch or [])
    conn.execute   = AsyncMock(return_value=execute or "UPDATE 1")
    # transaction() context manager
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=None)
    tx_ctx.__aexit__  = AsyncMock(return_value=False)
    conn.transaction  = MagicMock(return_value=tx_ctx)
    return conn


def _make_pool(fetchval=None, fetchrow=None, fetch=None, execute=None):
    conn = _make_conn(fetchval=fetchval, fetchrow=fetchrow, fetch=fetch, execute=execute)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__  = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


def _make_request(pool):
    req = MagicMock()
    req.app.state.pool = pool
    req.headers = {}
    return req


TENANT = {"sub": "00000000-0000-0000-0000-000000000001", "role": "admin"}
NOW    = datetime.datetime(2026, 5, 20, 10, 0, 0, tzinfo=datetime.timezone.utc)


# ── GET /tours ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_approved_tours_returns_200():
    """Returns 200 with data list when approved tours exist."""
    from api.routers.v1_s1 import list_approved_tours

    fake_rows = [
        {"tour_id": "aaaaaaaa-0000-0000-0000-000000000001", "sku": "SKU1",
         "tour_id_external": None, "src_name": "Bali Adventure",
         "country": "Indonesia", "provider": "WanderLux",
         "review_status": "approved", "ingest_at": NOW},
        {"tour_id": "aaaaaaaa-0000-0000-0000-000000000002", "sku": "SKU2",
         "tour_id_external": None, "src_name": "Sri Lanka Tour",
         "country": "Sri Lanka", "provider": "HorizonVoyages",
         "review_status": "approved", "ingest_at": NOW},
    ]
    pool, _ = _make_pool(fetch=fake_rows)
    result = await list_approved_tours(
        _make_request(pool), TENANT,
        country=None, supplier=None, upload_date_from=None, upload_date_to=None,
    )
    assert result["total"] == 2
    assert result["data"][0]["aa_name"] == "Bali Adventure"
    assert result["data"][1]["country"] == "Sri Lanka"


@pytest.mark.asyncio
async def test_list_approved_tours_empty_returns_200():
    """Returns 200 with empty list — never 404."""
    from api.routers.v1_s1 import list_approved_tours

    pool, _ = _make_pool(fetch=[])
    result = await list_approved_tours(
        _make_request(pool), TENANT,
        country=None, supplier=None, upload_date_from=None, upload_date_to=None,
    )
    assert result["total"] == 0
    assert result["data"] == []


@pytest.mark.asyncio
async def test_list_approved_tours_filter_by_country():
    """Country filter is forwarded to the query."""
    from api.routers.v1_s1 import list_approved_tours

    pool, conn = _make_pool(fetch=[])
    await list_approved_tours(
        _make_request(pool), TENANT,
        country="Vietnam", supplier=None, upload_date_from=None, upload_date_to=None,
    )
    call_args = conn.fetch.call_args
    sql = call_args[0][0]
    params = call_args[0][1:]
    assert "LOWER(country)" in sql
    assert "Vietnam" in params


# ── POST /run ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_run_success():
    """Valid tour_ids → run_id returned, tour_content_versions created."""
    from api.routers.v1_s1 import create_run, CreateRunRequest, RunConfig

    tour_id = "aaaaaaaa-0000-0000-0000-000000000001"
    run_id  = "bbbbbbbb-0000-0000-0000-000000000001"

    pool, conn = _make_pool()
    # First fetch: approved tours validation
    conn.fetch.side_effect = [
        [{"tour_id": tour_id}],  # approved tours check
    ]
    conn.fetchrow.return_value = {"run_id": run_id}

    req = _make_request(pool)
    body = CreateRunRequest(
        tour_ids=[tour_id],
        run_config=RunConfig(model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
                             seo_mode="informational", language="EN-US"),
    )

    with patch("api.routers.v1_s1._boto3") as mock_boto3:
        mock_sf = MagicMock()
        mock_boto3.client.return_value = mock_sf
        mock_sf.start_execution.return_value = {"executionArn": "arn:aws:states:..."}

        with patch.dict("os.environ", {"STEP_FUNCTIONS_ARN": "arn:aws:states:us-west-1:123:stateMachine:s1"}):
            result = await create_run(body, req, TENANT)

    assert "run_id" in result
    assert result["tour_count"] == 1
    assert result["started_count"] == 1
    assert result["failed_count"] == 0


@pytest.mark.asyncio
async def test_create_run_empty_tour_ids_raises_422():
    """Empty tour_ids raises 422 before touching DB."""
    from api.routers.v1_s1 import create_run, CreateRunRequest, RunConfig

    pool, _ = _make_pool()
    body = CreateRunRequest(tour_ids=[], run_config=RunConfig())

    with pytest.raises(HTTPException) as exc:
        await create_run(body, _make_request(pool), TENANT)

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_create_run_with_unapproved_tour_returns_422():
    """Tour not in approved set → 422 with informative detail."""
    from api.routers.v1_s1 import create_run, CreateRunRequest, RunConfig

    tour_id = "aaaaaaaa-0000-0000-0000-000000000001"
    pool, conn = _make_pool()
    # Approved check returns empty — tour not approved
    conn.fetch.side_effect = [[]]

    body = CreateRunRequest(
        tour_ids=[tour_id],
        run_config=RunConfig(),
    )

    with pytest.raises(HTTPException) as exc:
        await create_run(body, _make_request(pool), TENANT)

    assert exc.value.status_code == 422
    assert tour_id in exc.value.detail


@pytest.mark.asyncio
async def test_create_run_invalid_uuid_raises_422():
    """Malformed UUID in tour_ids raises 422."""
    from api.routers.v1_s1 import create_run, CreateRunRequest, RunConfig

    pool, _ = _make_pool()
    body = CreateRunRequest(tour_ids=["not-a-uuid"], run_config=RunConfig())

    with pytest.raises(HTTPException) as exc:
        await create_run(body, _make_request(pool), TENANT)

    assert exc.value.status_code == 422


# ── PATCH /versions/{version_id}/activate ────────────────────────────────────

@pytest.mark.asyncio
async def test_activate_version_deactivates_others():
    """
    activate_version sets is_active=TRUE on target and is_active=FALSE on all others.
    Verifies both UPDATE calls are made within a transaction.
    """
    from api.routers.v1_s1 import activate_version

    version_id  = "cccccccc-0000-0000-0000-000000000001"
    raw_tour_id = "aaaaaaaa-0000-0000-0000-000000000001"

    pool, conn = _make_pool()
    conn.fetchrow.return_value = {"id": version_id, "raw_tour_id": raw_tour_id}

    result = await activate_version(version_id, _make_request(pool), TENANT)

    # transaction was used
    conn.transaction.assert_called_once()

    # Two execute calls: deactivate-all then activate-one
    assert conn.execute.call_count == 2
    calls = [str(c) for c in conn.execute.call_args_list]
    assert any("FALSE" in c for c in calls)
    assert any("TRUE" in c for c in calls)

    assert result["version_id"]  == version_id
    assert result["raw_tour_id"] == raw_tour_id
    assert result["activated"]   is True


@pytest.mark.asyncio
async def test_activate_nonexistent_version_returns_404():
    """activate_version raises 404 when version not found."""
    from api.routers.v1_s1 import activate_version

    pool, conn = _make_pool()
    conn.fetchrow.return_value = None   # not found

    with pytest.raises(HTTPException) as exc:
        await activate_version("cccccccc-0000-0000-0000-000000000001", _make_request(pool), TENANT)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_activate_invalid_uuid_raises_422():
    """activate_version raises 422 for malformed version_id."""
    from api.routers.v1_s1 import activate_version

    pool, _ = _make_pool()
    with pytest.raises(HTTPException) as exc:
        await activate_version("not-a-uuid", _make_request(pool), TENANT)

    assert exc.value.status_code == 422


# ── _safe_uuid ────────────────────────────────────────────────────────────────

def test_safe_uuid_valid():
    from api.routers.v1_s1 import _safe_uuid
    result = _safe_uuid("aaaaaaaa-0000-0000-0000-000000000001", "test")
    assert result == "aaaaaaaa-0000-0000-0000-000000000001"


def test_safe_uuid_invalid_raises_422():
    from api.routers.v1_s1 import _safe_uuid
    with pytest.raises(HTTPException) as exc:
        _safe_uuid("bad-uuid", "test")
    assert exc.value.status_code == 422
