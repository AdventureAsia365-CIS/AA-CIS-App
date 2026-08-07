"""tests/verify_scripts/aa377_aa378_run_persist_verify.py — AA-377/AA-378 live verify glue.

WHY THIS FILE EXISTS (ADR-2026-037, same standard AA-367/AA-375/AA-376's own verify scripts
already met): `services/acp_planning/allocator.py`'s new
create_weekly_produce_run()/persist_slot_grid()/fetch_due_slots()/mark_slot_status()/
allocate_and_persist_week() are new, real, DB-wiring code — the mocked-pool unit tests
(tests/unit/test_aa377_aa378_run_slot_persist.py) intentionally isolate this module's own SQL
control flow from real Postgres semantics (real UNIQUE/FK/CHECK constraints, real JSONB
round-trip). This script proves the real thing end-to-end against real dev Postgres (migration
096) and the real, unmodified `services/acp_produce/slot_runner.py::run_slot_production()`
(AA-375) — same "test constructs the input via real upstream computation, production code does
the work" convention `aa375_slot_production_verify.py` already used.

Run ONLY inside the ECS task (S3-mediated exec) — shared/llm_client/bedrock_satellite.py's STS
AssumeRole chain is scoped to the ECS task role.

    python3 tests/verify_scripts/aa377_aa378_run_persist_verify.py
"""
from __future__ import annotations

import asyncio
from datetime import date
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
import boto3
import httpx

from services.acp_planning.allocator import (
    allocate_and_persist_week,
    create_weekly_produce_run,
    fetch_due_slots,
    mark_slot_status,
    persist_slot_grid,
)
from services.acp_planning.quarter import plan_quarter
from services.acp_planning.runway import runway_map
from services.acp_produce.slot_runner import run_slot_production

TENANT_ID = "00000000-0000-0000-0000-000000000001"  # aa_internal — same real tenant AA-367/AA-375 used
SPECIALS = ["Essential Korea"]  # same real-trip match AA-375's script used to reliably land a campaign slot
MARKET = "US"
MARKETS = ["US"]
CAPACITY_POSTS_PER_WEEK = 3
WEEK = 1  # SlotGrid's own week-of-month numbering (1-4), not ISO week — see AA-377.md
TEST_URL = "https://aa-cis.lumiguides.it.com/"  # real, live-checked below before being marked url_alive=True


def _step(title: str) -> None:
    print(f"\n{'=' * 12} {title} {'=' * 12}")


async def _verify_url_reachable(url: str) -> bool:
    async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
        r = await client.get(url)
        print(f"HTTP check {url} -> {r.status_code}")
        return r.status_code < 500


def _get_dsn() -> str:
    sm = boto3.client("secretsmanager", region_name="us-west-1")
    return sm.get_secret_value(SecretId="aa-cis/dev/rds")["SecretString"]


class _SingleConnPool:
    """Same minimal asyncpg.Pool-shaped adapter as AA-367/AA-375's scripts — every function
    called below takes `pool` and does `pool.acquire()`; this keeps one connection for
    read-your-writes ordering across the whole run."""

    def __init__(self, conn: asyncpg.Connection):
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


async def main() -> None:
    dsn = _get_dsn()
    u = urlparse(dsn)
    db = await asyncpg.connect(
        host=u.hostname, port=u.port or 5432, user=u.username, password=u.password,
        database=u.path.lstrip("/"), ssl="require",
    )
    pool = _SingleConnPool(db)
    run_id = None
    quarter_plan = None
    seeded_tenant_pages: list[str] = []
    piece_id_via_new_run = None

    try:
        # ---------------------------------------------------------- baseline: old acp_runs (S1-S4) untouched
        _step("BASELINE: acp_shared.acp_runs (old S1-S4 table) row count, before anything")
        old_runs_before = await db.fetchval("SELECT COUNT(*) FROM acp_shared.acp_runs")
        print(f"acp_shared.acp_runs count (before) = {old_runs_before}")

        # ---------------------------------------------------------- N4/N5 real planning
        _step("N4/N5: runway_map -> plan_quarter (test-only approved=True) — real candidate trips")
        today = date.today()
        year, month = today.year, today.month
        quarter = (month - 1) // 3 + 1

        runway = await runway_map(UUID(TENANT_ID), year, MARKETS, pool)
        quarter_plan = await plan_quarter(
            UUID(TENANT_ID), year, quarter, MARKETS, CAPACITY_POSTS_PER_WEEK, SPECIALS, runway, pool,
        )
        quarter_plan.approved = True  # TEST-ONLY — bypasses real Gate B human approval, never persisted
        print(f"quarter_plan trip_ids={quarter_plan.trip_ids} forced_specials={quarter_plan.forced_specials}")

        _step("SETUP: seed tenant_tour_pages (real HTTP check, once) so allocate has a real cta_target")
        if not await _verify_url_reachable(TEST_URL):
            raise RuntimeError(f"{TEST_URL} is not reachable — refusing to mark url_alive=True on a lie")
        for tid in quarter_plan.trip_ids:
            await db.execute(
                """
                INSERT INTO acp_deliver.tenant_tour_pages
                    (tenant_id, tour_id, url, url_alive, published_at, last_checked_at)
                VALUES ($1, $2::uuid, $3, TRUE, now(), now())
                ON CONFLICT (tenant_id, tour_id) DO UPDATE SET
                    url = EXCLUDED.url, url_alive = TRUE, last_checked_at = now()
                """,
                TENANT_ID, str(tid), TEST_URL,
            )
            seeded_tenant_pages.append(str(tid))
        print(f"tenant_tour_pages seeded for {len(seeded_tenant_pages)} trip(s)")

        # ---------------------------------------------------------- VERIFY bullet 1: deterministic slot_id
        _step("VERIFY 1: allocate_and_persist_week() called twice for the same week -> same run_id + slot_ids")
        before_rows = await db.fetch(
            "SELECT slot_id, status FROM acp_shared.acp_v2_slots "
            "WHERE tenant_id = $1 ORDER BY slot_id", TENANT_ID,
        )
        print(f"acp_v2_slots BEFORE first call ({len(before_rows)}): {[dict(r) for r in before_rows]}")

        run_id_1, slots_1 = await allocate_and_persist_week(
            UUID(TENANT_ID), year, month, WEEK, ["blog", "facebook", "tiktok"],
            CAPACITY_POSTS_PER_WEEK, quarter_plan, runway, MARKET, pool,
        )
        run_id = run_id_1
        after_first = await db.fetch(
            "SELECT slot_id, status FROM acp_shared.acp_v2_slots "
            "WHERE run_id = $1 ORDER BY slot_id", run_id_1,
        )
        print(f"run_id={run_id_1} slots persisted ({len(slots_1)}): {[s.slot_id for s in slots_1]}")
        print(f"acp_v2_slots AFTER first call ({len(after_first)}): {[dict(r) for r in after_first]}")

        run_id_2, slots_2 = await allocate_and_persist_week(
            UUID(TENANT_ID), year, month, WEEK, ["blog", "facebook", "tiktok"],
            CAPACITY_POSTS_PER_WEEK, quarter_plan, runway, MARKET, pool,
        )
        after_second = await db.fetch(
            "SELECT slot_id, status FROM acp_shared.acp_v2_slots "
            "WHERE run_id = $1 ORDER BY slot_id", run_id_2,
        )
        print(f"run_id={run_id_2} (2nd call) slots ({len(slots_2)}): {[s.slot_id for s in slots_2]}")
        print(f"acp_v2_slots AFTER second call ({len(after_second)}): {[dict(r) for r in after_second]}")

        if run_id_1 != run_id_2:
            raise RuntimeError(f"run_id changed between calls: {run_id_1} != {run_id_2}")
        if sorted(s.slot_id for s in slots_1) != sorted(s.slot_id for s in slots_2):
            raise RuntimeError("slot_id set changed between the two allocate_and_persist_week() calls")
        if len(after_first) != len(after_second):
            raise RuntimeError(
                f"row count changed on re-allocation: {len(after_first)} -> {len(after_second)} "
                "(expected identical — ON CONFLICT DO NOTHING should have been a no-op)"
            )
        print("PASS: same run_id, same slot_id set, same row count across 2 calls")

        if not slots_1:
            raise RuntimeError("No slots persisted for this week — cannot continue VERIFY 2-3")

        # Pick VERIFY 3's blog candidate FIRST, before VERIFY 2 marks anything 'produced' — a 1st
        # attempt at this script marked slots_1[0] "produced" without checking it wasn't the only
        # usable blog slot, which then starved VERIFY 3 (fetch_due_slots() correctly excluded it,
        # exactly as designed, just against the wrong slot). Real bug in this script, not in
        # allocator.py / slot_runner.py — fixed by choosing VERIFY 2's target explicitly instead
        # of "whichever slot happens to be first".
        blog_candidates = [s for s in slots_1 if s.channel == "blog" and s.atom_ids and s.cta_target]
        if not blog_candidates:
            all_blog = [(s.slot_id, s.trip_id, s.cta_target, s.atom_ids) for s in slots_1 if s.channel == "blog"]
            raise RuntimeError(
                "No blog Slot with atom_ids + cta_target came out of allocate_and_persist_week() — "
                f"a real finding, not a bug in this script. All blog slots this week: {all_blog}"
            )
        campaign_blog = [s for s in blog_candidates if s.kind == "campaign"]
        blog_slot = campaign_blog[0] if campaign_blog else blog_candidates[0]
        other_slots = [s for s in slots_1 if s.slot_id != blog_slot.slot_id]
        if not other_slots:
            raise RuntimeError(
                f"Only 1 slot this week ({blog_slot.slot_id}, the one VERIFY 3 needs) — "
                "need >=2 slots to test VERIFY 2's exclusion without starving VERIFY 3. "
                "Real finding (low capacity this week), not a bug in this script."
            )
        target_slot = other_slots[0]
        print(f"blog_slot (reserved for VERIFY 3)={blog_slot.slot_id} channel={blog_slot.channel}")
        print(f"target_slot (VERIFY 2's mark-produced target)={target_slot.slot_id} channel={target_slot.channel}")

        # ---------------------------------------------------------- VERIFY bullet 2: produced excluded from due
        _step("VERIFY 2: mark 1 slot 'produced' -> fetch_due_slots() must exclude it")
        due_before = await fetch_due_slots(pool, run_id)
        print(f"due BEFORE mark: {[s.slot_id for s in due_before]}")
        if target_slot.slot_id not in {s.slot_id for s in due_before}:
            raise RuntimeError(f"{target_slot.slot_id} not in due list before marking — test setup broken")

        await mark_slot_status(pool, target_slot.slot_id, "produced")
        row_after_mark = await db.fetchrow(
            "SELECT status, produced_at FROM acp_shared.acp_v2_slots WHERE slot_id = $1", target_slot.slot_id,
        )
        print(f"acp_v2_slots row after mark_slot_status: {dict(row_after_mark)}")

        due_after = await fetch_due_slots(pool, run_id)
        print(f"due AFTER mark: {[s.slot_id for s in due_after]}")
        if target_slot.slot_id in {s.slot_id for s in due_after}:
            raise RuntimeError(f"{target_slot.slot_id} still appears in due list after marking 'produced'")
        if blog_slot.slot_id not in {s.slot_id for s in due_after}:
            raise RuntimeError(
                f"{blog_slot.slot_id} (VERIFY 3's own candidate) unexpectedly disappeared from "
                "the due list after marking a DIFFERENT slot 'produced' — persist/fetch bug."
            )
        print("PASS: produced slot no longer appears in fetch_due_slots(); the untouched blog_slot still does")

        # ---------------------------------------------------------- VERIFY bullet 3: real Piece via new FK
        _step("VERIFY 3: slot_runner.run_slot_production() on a real Slot pulled from acp_v2_slots")
        due_now = await fetch_due_slots(pool, run_id)
        matches = [s for s in due_now if s.slot_id == blog_slot.slot_id]
        if not matches:
            raise RuntimeError(f"blog_slot {blog_slot.slot_id} no longer in due list — unexpected")
        slot = matches[0]
        print(f"slot picked FROM acp_v2_slots (not allocate_month() ad hoc): slot_id={slot.slot_id} "
              f"trip_id={slot.trip_id} channel={slot.channel} kind={slot.kind}")

        pieces = await run_slot_production(db, pool, TENANT_ID, slot, run_id, MARKET, dfs_client=None)
        print(f"run_slot_production returned {len(pieces)} piece(s)")
        for p in pieces:
            print(f"[{p.piece_id}] channel={p.channel} status={p.status} held_reason={p.held_reason}")

        persisted_rows = await db.fetch(
            "SELECT piece_id, channel, status, run_id FROM acp_deliver.pieces WHERE run_id = $1", run_id,
        )
        print(f"acp_deliver.pieces rows for run_id={run_id} ({len(persisted_rows)}): "
              f"{[dict(r) for r in persisted_rows]}")
        if len(persisted_rows) != len(pieces):
            raise RuntimeError(
                f"run_slot_production() returned {len(pieces)} pieces but {len(persisted_rows)} persisted "
                f"under run_id={run_id} via the new acp_v2_runs FK — a real persistence gap."
            )
        if pieces:
            piece_id_via_new_run = pieces[0].piece_id
        print("PASS: real Piece(s) persisted through acp_deliver.pieces.run_id -> acp_v2_runs FK")

        # ---------------------------------------------------------- VERIFY bullet 4: FK actually enforced
        _step("VERIFY 4: INSERT acp_deliver.pieces with a NON-EXISTENT run_id must fail (FK constraint)")
        bogus_run_id = "00000000-0000-0000-0000-999999999999"
        bogus_piece_id = f"verify-fk-bogus-{bogus_run_id}"
        fk_enforced = False
        try:
            await db.execute(
                """
                INSERT INTO acp_deliver.pieces (piece_id, run_id, tenant_id, channel, body_tagged, status)
                VALUES ($1, $2, $3, 'blog', 'bogus fk test', 'in_progress')
                """,
                bogus_piece_id, bogus_run_id, TENANT_ID,
            )
        except asyncpg.ForeignKeyViolationError as e:
            fk_enforced = True
            print(f"EXPECTED FK violation raised: {e}")
        if not fk_enforced:
            # if it didn't raise, the row would have been inserted — clean it up so this failure
            # doesn't itself corrupt dev data, then fail loudly.
            await db.execute("DELETE FROM acp_deliver.pieces WHERE piece_id = $1", bogus_piece_id)
            raise RuntimeError(
                "INSERT with a non-existent run_id did NOT raise ForeignKeyViolationError — "
                "the new acp_v2_runs FK is not actually enforced."
            )
        print("PASS: FK constraint rejects a non-existent run_id")

        # ---------------------------------------------------------- VERIFY bullet 5: old S1-S4 table untouched
        _step("VERIFY 5: acp_shared.acp_runs (old S1-S4 table) row count unchanged")
        old_runs_after = await db.fetchval("SELECT COUNT(*) FROM acp_shared.acp_runs")
        print(f"acp_shared.acp_runs count (after) = {old_runs_after} (before = {old_runs_before})")
        if old_runs_after != old_runs_before:
            raise RuntimeError(
                f"acp_shared.acp_runs row count changed ({old_runs_before} -> {old_runs_after}) — "
                "this session should only ever touch acp_v2_runs/acp_v2_slots, never the old S1-S4 table."
            )
        print("PASS: old acp_shared.acp_runs (S1-S4) completely untouched")

        _step("DONE")
        print(f"run_id={run_id} total_slots={len(slots_1)} pieces_persisted={len(persisted_rows)}")

    finally:
        # ---------------------------------------------------------- CLEANUP (restore dev DB to pre-test state)
        _step("CLEANUP")
        try:
            if run_id is not None:
                deleted_pieces = await db.fetchval(
                    "WITH d AS (DELETE FROM acp_deliver.pieces WHERE run_id = $1 RETURNING 1) "
                    "SELECT count(*) FROM d",
                    run_id,
                )
                deleted_slots = await db.fetchval(
                    "WITH d AS (DELETE FROM acp_shared.acp_v2_slots WHERE run_id = $1 RETURNING 1) "
                    "SELECT count(*) FROM d",
                    run_id,
                )
                deleted_runs = await db.fetchval(
                    "WITH d AS (DELETE FROM acp_shared.acp_v2_runs WHERE run_id = $1 RETURNING 1) "
                    "SELECT count(*) FROM d",
                    run_id,
                )
                print(f"deleted_pieces={deleted_pieces} deleted_v2_slots={deleted_slots} "
                      f"deleted_v2_runs={deleted_runs}")
            if seeded_tenant_pages:
                deleted_pages = await db.fetchval(
                    "WITH d AS (DELETE FROM acp_deliver.tenant_tour_pages "
                    "WHERE tenant_id = $1 AND tour_id = ANY($2::uuid[]) RETURNING 1) SELECT count(*) FROM d",
                    TENANT_ID, seeded_tenant_pages,
                )
                print(f"deleted_tenant_tour_pages={deleted_pages}")
        except Exception as e:  # noqa: BLE001 — cleanup must not mask the real error above
            print(f"CLEANUP WARNING: {e}")
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
