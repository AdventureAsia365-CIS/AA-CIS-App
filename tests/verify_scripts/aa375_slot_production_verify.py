"""
tests/verify_scripts/aa375_slot_production_verify.py — AA-375 live verify glue.

WHY THIS FILE EXISTS (ADR-2026-037, same standard AA-367's own verify script
already met): `services/acp_produce/slot_runner.py::run_slot_production()` is
new, real, glue-only code (no unit test double stands in for it — the unit
tests in `tests/unit/test_aa375_slot_runner.py` mock every chained function
on purpose, to isolate orchestration logic). This script proves the real
thing end-to-end: a real `Slot` pulled from `allocate_month()` (not
hand-constructed, unlike AA-367's script — AA-375's own instructions require
this), a real `acp_runs` row, and the real, unmodified
`run_slot_production()` chaining C1-C3 -> E1 -> E2 -> E3 -> E4 -> F1-F9
against real DataForSEO/Bedrock/Postgres. Test-only, run manually via the
S3-mediated ECS exec pattern, never imported by services/ code, never run by
pytest/CI — same convention as `aa367_real_piece_chain.py`.

`acp_runs` row (AA-378 not yet decided, per this issue's own instructions):
uses the exact same interim insert AA-367's script used
(`INSERT INTO acp_shared.acp_runs (tenant_id, status) VALUES ($1, 'running')
RETURNING run_id`) — TEMPORARY, pending AA-378's real option (a)/(b) decision.

`QuarterPlan.approved = True` set directly on the in-memory object below is
TEST-ONLY — it does not go through the real Gate B human-approval flow
(Ms. Thu). This mirrors AA-367's own "test constructs the input, production
code does the work" convention (there hand-building a `Slot`; here
hand-approving a `QuarterPlan` object that itself came from the real
`plan_quarter()` computation) — never persisted to
`acp_shared.quarter_plan_version`.

`tenant_tour_pages` seed happens AFTER `plan_quarter()` (so it targets the
real trips that computation actually chose, `quarter_plan.trip_ids` — a
first version of this script hardcoded a single known-rich TOUR_ID from
AA-367's own recon, but that tour did not make THIS run's top-N cut, a real,
reproducible finding logged in AA-375.md) but BEFORE `allocate_month()`
runs — `allocate_month()`'s own `make_slot()` sets `Slot.cta_target =
trip.trip_url if trip.url_alive else None` AT ALLOCATION TIME. Seeding after
allocation would leave `cta_target=None` on the already-built `Slot`, which
`compile_brief()` (C3) rejects on before the chain ever reaches F6 — a real,
reproducible consequence of `tenant_tour_pages` having ~0 rows in dev
(confirmed AA-367 STEP 0, still true here), documented rather than routed
around silently.

Real DB writes this script makes (not test doubles), all cleaned up after:
- ONE row in acp_deliver.tenant_tour_pages per trip in
  `quarter_plan.trip_ids` (real HTTP check done ONCE, same
  `_verify_url_reachable()` as AA-367's script — never a hardcoded claim;
  the one confirmed-reachable URL is reused across rows, this is a
  liveness stand-in, not a claim that each trip's real production page is
  that exact URL).
- ONE row in acp_shared.acp_runs for this script's own run.
- Real acp_deliver.pieces rows via the real, unmodified
  services/acp_produce/slot_runner.py::run_slot_production().

Run ONLY inside the ECS task (S3-mediated exec) — shared/llm_client/
bedrock_satellite.py's STS AssumeRole chain is scoped to the ECS task role.

    python3 tests/verify_scripts/aa375_slot_production_verify.py
"""
from __future__ import annotations

import asyncio
from datetime import date
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
import boto3
import httpx

from services.acp_planning.allocator import allocate_month
from services.acp_planning.quarter import plan_quarter
from services.acp_planning.runway import runway_map
from services.acp_produce.slot_runner import run_slot_production

TENANT_ID = "00000000-0000-0000-0000-000000000001"  # aa_internal — same real tenant AA-367 used
# SPECIALS (2nd-attempt addition, real finding from the 1st live run): allocate_month()'s own
# `keyword_seed = chosen[0].text[:60]` (allocator.py B6) is a truncated ATOM SENTENCE FRAGMENT, not
# a real search-intent phrase — DataForSEO legitimately finds no search volume for it, so
# compile_brief()'s demand law (research.py) correctly rejects every real "evergreen" Slot this
# script's 1st run produced (see docs/implementation-notes/AA-375.md). `kind="campaign"` is the
# only real bypass compile_brief() offers (`slot.kind == "campaign"` -> demand_reason set, no DFS
# volume required) — forcing one via a real matched trip name, not fabricating a Slot, so this
# script can also exercise the E1-E9/F1-F9 happy path, not only the (already real) reject path.
SPECIALS = ["Essential Korea"]
MARKET = "US"
MARKETS = ["US"]
CAPACITY_POSTS_PER_WEEK = 3
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
    """Same minimal `asyncpg.Pool`-shaped adapter as AA-367's script —
    `fetch_trips()`/`fetch_atoms_by_trip()`/`run_slot_production()` all call
    `pool.acquire()`; this keeps one connection for read-your-writes
    ordering across the whole run."""

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
    run_id = None  # captured inside try; referenced directly in cleanup, never re-queried
    quarter_plan = None  # ditto — cleanup needs quarter_plan.trip_ids to know which pages rows it seeded

    try:
        # ---------------------------------------------------------- N4/N5 real planning (before any seed)
        _step("N4/N5: runway_map -> plan_quarter (test-only approved=True) — find out which trips are real candidates")
        today = date.today()
        year, month = today.year, today.month
        quarter = (month - 1) // 3 + 1

        runway = await runway_map(UUID(TENANT_ID), year, MARKETS, pool)
        print(f"runway cells: {len(runway.cells)}")

        quarter_plan = await plan_quarter(
            UUID(TENANT_ID), year, quarter, MARKETS, CAPACITY_POSTS_PER_WEEK, SPECIALS, runway, pool,
        )
        quarter_plan.approved = True  # TEST-ONLY — bypasses real Gate B human approval, never persisted
        print(f"quarter_plan trip_ids={quarter_plan.trip_ids} forced_specials={quarter_plan.forced_specials} "
              f"(test-only approved=True, in-memory)")

        # ---------------------------------------------------------- SETUP (real HTTP check, seed AFTER
        # knowing which real trips plan_quarter actually chose — TOUR_ID's own AA-367 fame does not
        # guarantee it makes THIS run's top-N cut; tenant_tour_pages has ~0 real rows in dev (AA-367
        # STEP 0 finding, still true), so url_alive would be None/False, and cta_target None, for
        # every one of quarter_plan.trip_ids otherwise — seed all of them with the one HTTP-confirmed
        # URL so allocate_month() below can produce >=1 blog Slot with a real cta_target.)
        _step("SETUP: seed tenant_tour_pages for quarter_plan.trip_ids (real HTTP check, once) + acp_runs")
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
        print(f"tenant_tour_pages seeded for {len(quarter_plan.trip_ids)} trip(s): url={TEST_URL} url_alive=True")

        run_id = await db.fetchval(
            "INSERT INTO acp_shared.acp_runs (tenant_id, status) VALUES ($1, 'running') RETURNING run_id",
            TENANT_ID,
        )
        print(f"acp_runs seeded: run_id={run_id} (TEMPORARY interim shape, pending AA-378)")

        # ---------------------------------------------------------- N6 real allocation
        _step("N6: allocate_month() — now with real, live cta_target available for the seeded trips")
        slot_grid = await allocate_month(
            UUID(TENANT_ID), year, month, ["blog", "facebook", "tiktok"],
            CAPACITY_POSTS_PER_WEEK, quarter_plan, runway, MARKET, pool,
        )
        print(f"slot_grid: {len(slot_grid.slots)} slots, capacity_note={slot_grid.capacity_note!r}")

        candidates = [s for s in slot_grid.slots if s.channel == "blog" and s.atom_ids and s.cta_target]
        if not candidates:
            all_blog = [(s.slot_id, s.trip_id, s.cta_target, s.atom_ids)
                        for s in slot_grid.slots if s.channel == "blog"]
            raise RuntimeError(
                "No real blog Slot with a non-empty atom_ids + cta_target came out of allocate_month() "
                f"even after seeding url_alive=True for all of quarter_plan.trip_ids={quarter_plan.trip_ids} — "
                f"a real finding, not a bug in this script. All blog slots: {all_blog}"
            )
        # Prefer kind="campaign" (bypasses compile_brief()'s demand law, see SPECIALS comment above) —
        # falls back to whatever else came out if SPECIALS somehow didn't land a campaign slot this run.
        campaign_candidates = [s for s in candidates if s.kind == "campaign"]
        slot = campaign_candidates[0] if campaign_candidates else candidates[0]
        print(f"slot picked: slot_id={slot.slot_id} trip_id={slot.trip_id} channel={slot.channel} "
              f"kind={slot.kind} atom_ids={slot.atom_ids} cta_target={slot.cta_target} "
              f"keyword_seed={slot.keyword_seed!r}")

        # ---------------------------------------------------------- AA-375: real chain end-to-end
        _step("run_slot_production(): real C1-C3 -> E1 -> E2 -> E3 -> E4 -> F1-F9, zero mocking")
        pieces = await run_slot_production(
            db, pool, TENANT_ID, slot, str(run_id), MARKET, dfs_client=None,
        )
        print(f"run_slot_production returned {len(pieces)} piece(s)")
        for p in pieces:
            gate_summary = [(g.gate, g.passed) for g in p.gate_ledger]
            print(f"[{p.piece_id}] channel={p.channel} status={p.status} held_reason={p.held_reason}")
            print(f"  gate_ledger: {gate_summary}")

        passed = [p for p in pieces if p.status == "passed"]
        print(f"\nPASSED PIECE IDS: {[p.piece_id for p in passed]}")

        # ---------------------------------------------------------- independent read-path confirmation
        _step("Independent read: confirm real persistence via acp_deliver.pieces")
        rows = await db.fetch(
            "SELECT piece_id, channel, status, run_id FROM acp_deliver.pieces WHERE run_id = $1",
            str(run_id),
        )
        print(f"acp_deliver.pieces rows for this run_id ({len(rows)}):")
        for r in rows:
            print(f"  {dict(r)}")
        if len(rows) != len(pieces):
            raise RuntimeError(
                f"run_slot_production() returned {len(pieces)} pieces but only {len(rows)} persisted "
                f"under run_id={run_id} — a real persistence gap, not expected."
            )

        _step("DONE")
        print(f"run_id={run_id} slot_id={slot.slot_id} total_pieces={len(pieces)} passed={len(passed)}")

    finally:
        # ---------------------------------------------------------- CLEANUP (restore dev DB to pre-test state)
        _step("CLEANUP")
        try:
            if run_id is not None:
                deleted_pieces = await db.fetchval(
                    "WITH d AS (DELETE FROM acp_deliver.pieces WHERE run_id = $1 RETURNING 1) "
                    "SELECT count(*) FROM d",
                    str(run_id),
                )
                deleted_runs = await db.fetchval(
                    "WITH d AS (DELETE FROM acp_shared.acp_runs WHERE run_id = $1 RETURNING 1) "
                    "SELECT count(*) FROM d",
                    run_id,
                )
                print(f"deleted_pieces={deleted_pieces} deleted_acp_runs={deleted_runs}")
            if quarter_plan is not None and quarter_plan.trip_ids:
                deleted_pages = await db.fetchval(
                    "WITH d AS (DELETE FROM acp_deliver.tenant_tour_pages "
                    "WHERE tenant_id = $1 AND tour_id = ANY($2::uuid[]) RETURNING 1) SELECT count(*) FROM d",
                    TENANT_ID, [str(t) for t in quarter_plan.trip_ids],
                )
                print(f"deleted_tenant_tour_pages={deleted_pages}")
        except Exception as e:  # noqa: BLE001 — cleanup must not mask the real error above
            print(f"CLEANUP WARNING: {e}")
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
