"""tests/verify_scripts/aa391_e2e_orchestrator.py — AA-391 live verify glue.

AA-475: BROKEN as of the N2 atomize teardown — `api.routers.v1_atoms` (this script's STEP 3
import, below) no longer exists; N2 platform-scope decompose was deleted along with
/admin/atomize + /admin/curation, retired in favor of T5's tenant-scoped atomize
(services/acp_produce/tenant_pipeline.py::run_t5_atomize). Never wired into pytest/CI (manual,
TEST_MODE-gated script only) so this doesn't break the build — left as-is rather than rewritten,
since patching STEP 3 to call T5 instead would misrepresent what this script's historical run
actually verified (N2, not T5). A future re-run of this chain needs a new STEP 3 written against
run_t5_atomize first.

WHY THIS FILE EXISTS (ADR-2026-037, same standard AA-364/367/375/376/377/378's own verify
scripts already met): proves the full S0->N8 chain (N0-N2 decompose -> N3 curate -> S1-from-atom
-> N4 runway -> N5 quarter (Gate B) -> N6 allocate -> N7 slot production -> N8 packet assembly)
runs end-to-end against REAL Laos + South Korea data for the real `aa_internal` tenant, calling
the real, unmodified production service functions each earlier issue already built and
live-verified individually (AA-299/305/306/320/375/376/377/378/364/367) -- this issue's own gap
is that no one had chained ALL of them in one continuous run before.

TEST_MODE (constraint from the AA-391 issue text):
    Every piece of auto-approve logic in this file is TEST-ONLY and lives ONLY in this
    standalone script -- it never touches any production router/endpoint code. This script
    calls the same real `services.*` functions a real approve-endpoint would call
    (`approve_quarter_plan_version`), it just supplies `approved_by="TEST_MODE_SCRIPT"` itself
    instead of a human clicking "Approve" in a UI. This is the exact same test methodology
    ADR-2026-037's prior scripts already used (e.g. aa377_aa378_run_persist_verify.py setting
    `quarter_plan.approved = True` directly) -- the only difference here is going through the
    REAL DB-persisted Gate B path (`save_quarter_plan_version` + `approve_quarter_plan_version`)
    instead of the in-memory bypass, because AA-391 explicitly asks to prove the real persisted
    gate, not just bypass it.

    Must be run with TEST_MODE=true in the environment -- the script refuses to run otherwise.

Gate inventory + what this script does with each (per the AA-391 issue text):
  - Gate A (N1 tenant onboarding approval, admin.py::approve_gate_a) -- SKIPPED. `aa_internal` is
    a pre-existing, already-`is_active` platform tenant (confirmed by live query in STEP 1 below),
    not a new tenant going through N1 onboarding. Gate A only exists to flip a NEW tenant's
    `is_active` false->true; it does not gate N4/N5/N6/N7/N8 for an already-active tenant. Matches
    the issue text's own "N1 onboard (mock, hoặc bỏ qua nếu N4-N6 không phụ thuộc N1)" -- N4-N6
    read `shared.tenants`/`acp_contract.v_trip_registry` directly, no dependency on
    `acp_shared.tenant_onboarding` found anywhere in `services/acp_planning/*.py` (confirmed by
    reading every N4-N6 module during STEP 0 prep for this script).
  - Gate B (N5/N6 quarter plan approval, AA-320) -- REAL persisted path exercised:
    `save_quarter_plan_version()` (creates a real `acp_shared.quarter_plan_version` row,
    status='pending') then `approve_quarter_plan_version(version_id, approved_by="TEST_MODE_SCRIPT",
    pool)` (real UPDATE, real audit trail). `approved_by="TEST_MODE_SCRIPT"` is written literally
    into `acp_shared.quarter_plan_version.approved_by` -- anyone reading this DB later sees
    unambiguously that this was not Ms. Thu approving anything real.
  - Gate C (AA-365, trust ramp / veto window) -- does not exist (0% code, confirmed Backlog in
    Linear as of this script's writing). N8 assembly in this repo does not depend on it --
    `deliver_packet()` (packets.py) has no Gate C call of any kind. Nothing to auto-approve here
    because there is no gate here yet.
  - BOFU/pricing content approval-forever (AA-365 hard constraint) -- NOT APPLICABLE YET: grepping
    `services/acp_produce/*.py` and `services/acp_planning/*.py` for any BOFU/pricing
    classification or gate found zero matches. There is no code path today that distinguishes
    BOFU/pricing content from any other content, so there is nothing for this script to avoid
    auto-approving -- flagged in the AA-391 report as a real gap AA-365 will need to close before
    Gate C can safely exist, not something this script papers over.

Real publish block (constraint from the AA-391 issue text):
    Confirmed by grep across `services/` and `api/` (see this issue's own implementation notes,
    docs/implementation-notes/AA-391.md) for any WordPress/social-platform/CMS send call: ZERO
    matches. `packets.py::deliver_packet()` -- the only function in this repo that ever sets
    `packets.status='delivered'` -- does exactly two things: calls `write_usage_log()` (an
    internal DB write, `acp_contract.tour_atoms.usage_log`) and updates `packets.status`/
    `delivered_at`. There is no HTTP call, no WordPress API, no social API anywhere in that
    function or anything it calls. `set_publish_mode()` additionally hard-blocks (raises
    `PublishModeBlockedError`) any attempt to move `publish_mode` past `'propose_only'` until F6
    exists as a Nghiep-recorded decision (AA-364, 05/08/2026) -- this script never calls
    `set_publish_mode()` at all, so packets stay at the DB default `'propose_only'` throughout.
    There is nothing to comment out or feature-flag: no real-publish code path exists to disable.

Scope decisions (recorded here, not silently applied):
  - Destinations: filters the real `Trip` list (from `fetch_trips()`) to `destination IN
    ('Laos', 'South Korea')` BEFORE calling the pure `compute_runway_map()`/`compute_quarter_plan()`
    functions -- not via `specials` (which only force-includes, doesn't exclude other
    destinations) and not via a DB-level WHERE clause on `v_trip_registry` (keeps the destination
    scoping visible in Python, not buried in a query only this script has). This guarantees
    `quarter_plan.trip_ids` can ONLY ever contain Laos/South Korea trips.
  - Week scope: only week=1 of the current month/quarter is allocated+produced live in this run
    (real Bedrock Sonnet/Nova Pro/DataForSEO calls stack up fast across weeks x channels x repair
    rounds -- CLAUDE.md's cost-discipline concern is real). The exact same
    `allocate_and_persist_week()`/`run_slot_production()` mechanism applies unchanged to weeks
    2-4; this is a live-run cost scope decision, not an architecture limitation.
  - No cleanup at the end. Every other ADR-2026-037 verify script deletes its rows because it
    used synthetic/hand-constructed test fixtures. This script's entire point is producing REAL
    content for Laos/South Korea tours under the REAL `aa_internal` tenant -- the atoms, S1
    content, quarter plan, slots, pieces, and packet this run creates are real production
    artifacts, not test fixtures, and are intentionally left in place.

Run ONLY inside the ECS task (S3-mediated exec) -- shared/llm_client/bedrock_satellite.py's STS
AssumeRole chain is scoped to the ECS task role.

    TEST_MODE=true python3 tests/verify_scripts/aa391_e2e_orchestrator.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/app")  # running as /tmp/aa391.py inside the ECS container — see
# docs/implementation-notes/AA-391.md "harness constraint" note: PYTHONPATH=/app is also
# passed at invocation, this is defensive belt-and-suspenders per the repo's own documented
# ECS-exec-daemonize convention.


def _daemonize(log_path: str) -> None:
    """Double-fork + os.setsid() so this process survives the launching ECS-exec/SSM session
    tearing down (the harness's interactive exec session cannot stay alive more than a few
    real seconds without output — see reference memory ecs-exec-long-sync-daemonize). Must run
    BEFORE any of this script's own heavy imports below (api.routers.v1_atoms /
    services.acp_produce.* chain), since even those module-level imports alone were observed
    live to block long enough to trip the harness's session, well before any Bedrock/DFS call
    in `main()` itself. The original foreground invocation prints SPAWNED and exits almost
    immediately; the real run (imports + all of main()) continues in the detached child,
    writing everything to `log_path`; a separate short-lived exec later polls that file for
    AA391_DONE_MARKER."""
    if os.fork() > 0:
        print(f"SPAWNED log={log_path}")
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    sys.stdout.flush()
    sys.stderr.flush()
    log_fd = open(log_path, "a", buffering=1)
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())


if __name__ == "__main__":
    _daemonize("/tmp/aa391_output.log")
    # Only the detached child (or a direct, non-`__main__` import, which never happens for
    # this file) reaches the rest of this module — the original foreground process has
    # already _exit(0)'d inside _daemonize() above.

import asyncio
import json
from datetime import date
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
import boto3

from api.routers.v1_atoms import _decompose_inline
from services.acp_planning.allocator import (
    allocate_and_persist_week,
    fetch_due_slots,
    mark_slot_status,
)
from services.acp_planning.quarter import (
    approve_quarter_plan_version,
    fetch_approved_quarter_plan,
    fetch_atoms_by_trip,
    compute_quarter_plan,
    save_quarter_plan_version,
)
from services.acp_planning.runway import compute_runway_map, fetch_trips
from services.acp_produce.packets import (
    assemble_packet,
    create_packet,
    deliver_packet,
    maybe_mark_packet_ready,
)
from services.acp_produce.slot_runner import run_slot_production
from services.content_generation.s1_from_atom import (
    DEFAULT_MODEL_TIER,
    GroundingError,
    generate_s1_from_atom,
)

TENANT_ID = "00000000-0000-0000-0000-000000000001"  # aa_internal — real platform tenant
DESTINATIONS = ["Laos", "South Korea"]
MARKET = "US"
MARKETS = ["US"]
CAPACITY_POSTS_PER_WEEK = 3
CHANNELS = ["blog", "facebook", "tiktok"]
WEEK = 1  # SlotGrid's own week-of-month numbering (1-4) — see AA-377.md. Cost-scoped to 1 week.
TEST_MODE_APPROVER = "TEST_MODE_SCRIPT"


def _step(title: str) -> None:
    print(f"\n{'=' * 12} {title} {'=' * 12}")


def _get_dsn() -> str:
    sm = boto3.client("secretsmanager", region_name="us-west-1")
    return sm.get_secret_value(SecretId="aa-cis/dev/rds")["SecretString"]


class _SingleConnPool:
    """Same minimal asyncpg.Pool-shaped adapter AA-367/375/376/377/378's own scripts use —
    every function called below takes `pool` and does `pool.acquire()`; this keeps one real
    connection for read-your-writes ordering across the whole run."""

    def __init__(self, conn: asyncpg.Connection):
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


async def main() -> None:
    if os.environ.get("TEST_MODE", "").lower() != "true":
        raise RuntimeError(
            "TEST_MODE must be set to 'true' in the environment to run this script — "
            "this script auto-approves Gate B (approved_by='TEST_MODE_SCRIPT') and is not "
            "safe to run without that flag being an explicit, visible choice."
        )

    dsn = _get_dsn()
    u = urlparse(dsn)
    db = await asyncpg.connect(
        host=u.hostname, port=u.port or 5432, user=u.username, password=u.password,
        database=u.path.lstrip("/"), ssl="require",
    )
    pool = _SingleConnPool(db)

    try:
        # ============================================================ STEP 1: baseline + tenant check
        _step("STEP 1: baseline — confirm aa_internal is a pre-existing active tenant (Gate A skip)")
        tenant_row = await db.fetchrow(
            "SELECT tenant_id, name, is_active, posts_per_week FROM shared.tenants WHERE tenant_id = $1::uuid",
            TENANT_ID,
        )
        print(f"shared.tenants row: {dict(tenant_row) if tenant_row else None}")
        if not tenant_row or not tenant_row["is_active"]:
            raise RuntimeError(
                f"aa_internal (tenant_id={TENANT_ID}) is not an active tenant — Gate A skip "
                "assumption in this script's own docstring is wrong for this DB. Stopping "
                "rather than silently proceeding on a false assumption."
            )
        print("Gate A SKIPPED — tenant already active, not a new N1 onboarding.")

        # ============================================================ STEP 2: discover Laos + Korea trips
        _step("STEP 2: N4 input — fetch_trips() then filter to destination IN Laos/South Korea")
        all_trips = await fetch_trips(UUID(TENANT_ID), pool)
        print(f"fetch_trips() total trips for tenant: {len(all_trips)}")
        destinations_seen = sorted({t.destination for t in all_trips if t.destination})
        print(f"distinct destinations seen: {destinations_seen}")
        trips = [t for t in all_trips if t.destination in DESTINATIONS]
        print(f"trips matching {DESTINATIONS}: {len(trips)} -> "
              f"{[(str(t.id), t.name, t.destination) for t in trips]}")
        if not trips:
            raise RuntimeError(
                f"No trips found for destinations {DESTINATIONS} — cannot continue. "
                f"Real destination strings seen in DB: {destinations_seen}"
            )
        trip_ids = [t.id for t in trips]

        # ============================================================ STEP 3: N0-N2 decompose (idempotent)
        _step("STEP 3: N0-N2 — atom decompose for Laos/South Korea trips (idempotent via source_hash)")
        before_atom_counts = await db.fetch(
            """
            SELECT tour_id, count(*) FILTER (WHERE NOT deleted AND NOT is_empty_marker) AS live_atoms
            FROM acp_contract.tour_atoms WHERE tour_id = ANY($1::uuid[]) GROUP BY tour_id
            """,
            trip_ids,
        )
        print(f"atom counts BEFORE decompose: {[dict(r) for r in before_atom_counts]}")

        decompose_rows = await db.fetch(
            """
            SELECT id, name, aa_summary, aa_highlights, itinerary_source, inclusions, exclusions
            FROM acp_contract.v_trip_registry
            WHERE id = ANY($1::uuid[])
            """,
            trip_ids,
        )
        decompose_result = await _decompose_inline(decompose_rows, pool)
        print(f"_decompose_inline() result: {json.dumps(decompose_result, default=str)}")

        after_atom_counts = await db.fetch(
            """
            SELECT tour_id, count(*) FILTER (WHERE NOT deleted AND NOT is_empty_marker) AS live_atoms
            FROM acp_contract.tour_atoms WHERE tour_id = ANY($1::uuid[]) GROUP BY tour_id
            """,
            trip_ids,
        )
        print(f"atom counts AFTER decompose: {[dict(r) for r in after_atom_counts]}")

        # ============================================================ STEP 4: N3 curation (TEST_MODE auto-star)
        _step("STEP 4: N3 — TEST_MODE auto-star all live atoms for these trips (curation stand-in)")
        starred_rows = await db.fetch(
            """
            UPDATE acp_contract.tour_atoms
            SET starred = TRUE, updated_at = now()
            WHERE tour_id = ANY($1::uuid[]) AND NOT deleted AND NOT is_empty_marker
            RETURNING atom_id, tour_id
            """,
            trip_ids,
        )
        print(f"TEST_MODE auto-curation: starred {len(starred_rows)} atom(s) across {len(trip_ids)} trip(s) "
              f"(note: starring is a weighting signal for N6, not a hard gate for S1/N6 eligibility — "
              f"confirmed by reading fetch_curated_atoms()/_eligible_atoms(), which only require "
              f"NOT deleted AND NOT is_empty_marker)")

        # ============================================================ STEP 5: S1-from-atom
        _step("STEP 5: N2b — S1-from-atom rewrite for each Laos/South Korea trip")
        s1_results = []
        for t in trips:
            tour = {"name": t.name, "country": t.destination}
            try:
                result = await generate_s1_from_atom(str(t.id), tour, pool, model_tier=DEFAULT_MODEL_TIER)
                print(f"[S1-from-atom OK] tour={t.id} name={t.name!r} "
                      f"atoms_used={len(result['atoms_used'])} retries={result['retries']} "
                      f"model={result['model_used']}")
                s1_results.append({"tour_id": str(t.id), "status": "passed", "retries": result["retries"]})
            except GroundingError as e:
                print(f"[S1-from-atom HELD] tour={t.id} name={t.name!r} error={e}")
                s1_results.append({"tour_id": str(t.id), "status": "gate_failed", "error": str(e)})
        print(f"S1-from-atom summary: {json.dumps(s1_results, default=str)}")

        # ============================================================ STEP 6: N4 runway (real, Laos/Korea only)
        _step("STEP 6: N4 — runway_map on the Laos/South Korea-filtered trip list")
        today = date.today()
        year, month = today.year, today.month
        quarter = (month - 1) // 3 + 1
        runway = compute_runway_map(UUID(TENANT_ID), year, trips, MARKETS)
        print(f"runway computed for {len(trips)} trip(s), year={year} markets={MARKETS}")

        # ============================================================ STEP 7: N5 quarter plan + REAL Gate B
        _step("STEP 7: N5 — compute_quarter_plan (Laos/Korea-only trips) -> persist -> Gate B TEST_MODE approve")
        atoms_by_trip = await fetch_atoms_by_trip(UUID(TENANT_ID), pool)
        plan = compute_quarter_plan(
            UUID(TENANT_ID), year, quarter, trips, MARKETS, CAPACITY_POSTS_PER_WEEK,
            [], runway, atoms_by_trip,
        )
        print(f"quarter_plan (in-memory, unapproved) trip_ids={plan.trip_ids}")
        non_scoped = set(plan.trip_ids) - set(trip_ids)
        if non_scoped:
            raise RuntimeError(
                f"compute_quarter_plan() selected trip_ids outside the Laos/South Korea scope: "
                f"{non_scoped} — destination filtering upstream failed to constrain this."
            )
        print("VERIFIED: every trip_id in the quarter plan is inside the Laos/South Korea scope")

        version_id = await save_quarter_plan_version(plan, pool, source="standard")
        pending_row = await db.fetchrow(
            "SELECT version_id, approval_status, approved_by FROM acp_shared.quarter_plan_version "
            "WHERE version_id = $1", version_id,
        )
        print(f"acp_shared.quarter_plan_version persisted (pending): {dict(pending_row)}")

        print(f"Gate B — TEST_MODE auto-approve, approved_by={TEST_MODE_APPROVER!r} "
              f"(NOT a real human approval — this is the TEST_MODE marker, per AA-391's own "
              f"requirement so nobody mistakes this for Ms. Thu's real sign-off)")
        await approve_quarter_plan_version(version_id, TEST_MODE_APPROVER, pool)
        approved_row = await db.fetchrow(
            "SELECT version_id, approval_status, approved_by, approved_at FROM acp_shared.quarter_plan_version "
            "WHERE version_id = $1", version_id,
        )
        print(f"acp_shared.quarter_plan_version AFTER Gate B approve: {dict(approved_row)}")

        # ============================================================ STEP 8: N6 reads back the REAL approved plan
        _step("STEP 8: N6 — fetch_approved_quarter_plan() reads the just-approved version back from DB")
        approved_plan = await fetch_approved_quarter_plan(UUID(TENANT_ID), year, quarter, pool)
        if approved_plan is None or not approved_plan.approved:
            raise RuntimeError("fetch_approved_quarter_plan() did not return an approved plan after Gate B approve")
        print(f"N6 read back approved plan: trip_ids={approved_plan.trip_ids} approved_by={approved_plan.approved_by}")

        # ============================================================ STEP 9: N6 allocate + persist week
        _step(f"STEP 9: N6 — allocate_and_persist_week() for week={WEEK} (cost-scoped to 1 week, see docstring)")
        run_id, slots = await allocate_and_persist_week(
            UUID(TENANT_ID), year, month, WEEK, CHANNELS, CAPACITY_POSTS_PER_WEEK,
            approved_plan, runway, MARKET, pool,
        )
        print(f"run_id={run_id} slots persisted={len(slots)}: "
              f"{[(s.slot_id, s.channel, s.kind, str(s.trip_id)) for s in slots]}")

        due_slots = await fetch_due_slots(pool, run_id)
        print(f"fetch_due_slots() returned {len(due_slots)} due slot(s)")

        # ============================================================ STEP 10: N7 slot production, all due slots
        _step("STEP 10: N7 — run_slot_production() for every due slot this week")
        all_pieces = []
        for slot in due_slots:
            print(f"\n--- slot {slot.slot_id} channel={slot.channel} kind={slot.kind} "
                  f"trip_id={slot.trip_id} ---")
            try:
                pieces = await run_slot_production(db, pool, TENANT_ID, slot, run_id, MARKET, dfs_client=None)
            except Exception as e:
                print(f"[slot_production ERROR] slot={slot.slot_id} error={type(e).__name__}: {e}")
                await mark_slot_status(pool, slot.slot_id, "skipped", reason=f"{type(e).__name__}: {e}")
                continue
            for p in pieces:
                print(f"  [{p.piece_id}] channel={p.channel} status={p.status} held_reason={p.held_reason} "
                      f"repair_count={p.repair_count}")
            all_pieces.extend(pieces)
            await mark_slot_status(pool, slot.slot_id, "produced" if pieces else "skipped",
                                    reason=None if pieces else "run_slot_production returned no pieces")

        passed_pieces = [p for p in all_pieces if p.status == "passed"]
        held_pieces = [p for p in all_pieces if p.status == "held"]
        print(f"\nN7 summary: total_pieces={len(all_pieces)} passed={len(passed_pieces)} held={len(held_pieces)}")
        for p in held_pieces:
            print(f"  HELD [{p.piece_id}] reason={p.held_reason} (visible, not silently dropped — L6)")

        # ============================================================ STEP 11: N8 assemble + deliver (or hold)
        _step("STEP 11: N8 — create_packet -> assemble_packet (passed pieces only) -> ready -> deliver")
        packet_id = await create_packet(db, TENANT_ID, year, month, WEEK)
        packet_row = await db.fetchrow(
            "SELECT packet_id, status, publish_mode FROM acp_deliver.packets WHERE packet_id = $1", packet_id,
        )
        print(f"packet created: {dict(packet_row)}")

        delivered = False
        if passed_pieces:
            n_assigned = await assemble_packet(db, packet_id, [p.piece_id for p in passed_pieces])
            print(f"assemble_packet: assigned {n_assigned} passed piece(s)")
            became_ready = await maybe_mark_packet_ready(db, packet_id)
            print(f"maybe_mark_packet_ready: {became_ready}")
            if became_ready:
                usage_result = await deliver_packet(db, pool, packet_id)
                print(f"deliver_packet: usage_log write result={usage_result}")
                delivered = True
        else:
            print("No passed pieces this run — packet stays 'assembling' with 0 pieces assigned. "
                  "This is a real, reportable outcome (matches AA-367/AA-375's own documented "
                  "few-shot pass rate — see docs/implementation-notes/AA-367.md), not a chain break.")

        final_packet_row = await db.fetchrow(
            "SELECT packet_id, status, publish_mode, delivered_at FROM acp_deliver.packets WHERE packet_id = $1",
            packet_id,
        )
        print(f"FINAL packet state: {dict(final_packet_row)}")
        if final_packet_row["publish_mode"] != "propose_only":
            raise RuntimeError(
                f"publish_mode is {final_packet_row['publish_mode']!r}, expected 'propose_only' — "
                "the hard-block on real publish (AA-364 decision) was somehow bypassed."
            )
        print("VERIFIED: publish_mode stayed 'propose_only' — no real publish is possible from this state "
              "(and no code exists anywhere in this repo to perform one — see this file's own docstring).")

        # ============================================================ STEP 12: independent DB verification
        _step("STEP 12: independent read-only verification of every stage's real DB state")
        atom_summary = await db.fetch(
            """SELECT tour_id, count(*) FILTER (WHERE starred) AS starred_count,
                      count(*) FILTER (WHERE NOT deleted AND NOT is_empty_marker) AS live_count
               FROM acp_contract.tour_atoms WHERE tour_id = ANY($1::uuid[]) GROUP BY tour_id""",
            trip_ids,
        )
        s1_runs = await db.fetch(
            """SELECT tour_id, status, model_tier, citation_count, word_count, created_at
               FROM acp_contract.s1_from_atom_runs WHERE tour_id = ANY($1::uuid[])
               ORDER BY created_at DESC""",
            trip_ids,
        )
        slot_status = await db.fetch(
            "SELECT status, count(*) FROM acp_shared.acp_v2_slots WHERE run_id = $1 GROUP BY status",
            run_id,
        )
        piece_status = await db.fetch(
            "SELECT channel, status, held_reason FROM acp_deliver.pieces WHERE run_id = $1", run_id,
        )
        evidence = {
            "quarter_plan_version": dict(approved_row),
            "atoms_by_tour": [dict(r) for r in atom_summary],
            "s1_from_atom_runs": [dict(r) for r in s1_runs],
            "slot_status_breakdown": [dict(r) for r in slot_status],
            "pieces": [dict(r) for r in piece_status],
            "packet": dict(final_packet_row),
            "delivered": delivered,
        }
        print(json.dumps(evidence, default=str, indent=2))

        _step("DONE")
        print(f"run_id={run_id} trips={len(trips)} slots_due={len(due_slots)} "
              f"pieces={len(all_pieces)} passed={len(passed_pieces)} packet_delivered={delivered}")
        print("No cleanup performed — see this file's own docstring (real content, not test fixtures).")

    finally:
        await db.close()


if __name__ == "__main__":
    # Reached only inside the detached daemon child — the foreground process already exited
    # inside _daemonize() near the top of this file, before any of the heavy imports above ran.
    DONE_MARKER = "AA391_DONE_MARKER"
    try:
        asyncio.run(main())
        print(f"{DONE_MARKER} status=SUCCESS")
    except BaseException as e:  # noqa: BLE001 — must still emit the marker on any failure
        print(f"{DONE_MARKER} status=FAILURE error={type(e).__name__}: {e}")
        raise
