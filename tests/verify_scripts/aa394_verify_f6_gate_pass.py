"""
tests/verify_scripts/aa394_verify_f6_gate_pass.py — AA-394 post-backfill verify.

*** Depends on aa394_backfill_tenant_tour_pages.py having been run first for the same
*** tenant/tour(s) -- this script does not write tenant_tour_pages itself, it only proves
*** the backfill actually unblocks real N7 production. TEST-ONLY, same as the backfill
*** script it verifies -- see that file's docstring for the AA-395 real-engine caveat.

WHY THIS FILE EXISTS (AA-394, Nghiep, 09/08/2026): re-runs real, already-persisted N7
slots (acp_shared.acp_v2_slots, from AA-391's live chain run) through the real
services.acp_produce.slot_runner.run_slot_production() -- same function, same call
signature AA-391 used -- now that acp_deliver.tenant_tour_pages has real rows. Confirms
two things independently, not just in-memory: (1) F6 (gate_route_to_sellable) actually
clears now (gate_ledger has F6_route_to_sellable passed=True), and (2) Piece rows actually
get created at all (the real block AA-391 hit was one step earlier than F6 itself --
services/acp_planning/allocator.py:193's `cta = t.trip_url if t.url_alive else None` meant
every slot got cta_target=None while the table was empty, so research.py::compile_brief()
rejected with `no_cta_target` before any Piece object was ever created).

The persisted acp_v2_slots rows themselves keep their ORIGINAL cta_target=None baked in at
allocation time (ON CONFLICT DO NOTHING means re-allocating wouldn't fix that in place) --
this script reconstructs each Slot with a FRESH cta_target read live from
v_trip_registry.trip_url post-backfill, using the identical formula allocator.py uses, then
calls the real production function. Real Bedrock Sonnet + Nova Pro judge + DataForSEO
calls, zero mocking -- not cheap, use sparingly (see FIRST RUN result below for real cost
shape: 3 slots -> 9 real pieces, several LLM calls + repair rounds each).

FIRST RUN (09/08/2026): tour c9fb02ef-8db5-4849-a12e-e9718935039e (South Korea), 3 slots
(blog/facebook/tiktok) -> 9 real pieces (blog + adapted facebook/tiktok per slot
iteration). F6_route_to_sellable passed=True on 9/9 pieces (confirmed via independent
re-read of acp_deliver.pieces.gate_ledger, not just this script's own log). All 9 still
ended status=held -- but on F3_structural_variance / F8_framework / F9_brand_seo_audit_
social, pre-existing E2/E3 prompt-quality gaps already documented in
docs/implementation-notes/AA-367.md, unrelated to F6 and NOT fixed by this script. See
AA-394 Linear comments (09/08/2026) for full evidence.

Daemonized (double-fork) because real Bedrock/Nova Pro/DataForSEO calls for even 3 slots
run past the ECS-exec/SSM interactive session's few-second output budget -- see reference
memory ecs-exec-long-sync-daemonize, same pattern tests/verify_scripts/
aa391_e2e_orchestrator.py already uses.
"""
import os
import sys

sys.path.insert(0, "/app")  # running as a one-off script inside the ECS container


def _daemonize(log_path: str) -> None:
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
    _daemonize("/tmp/aa394_verify_output.log")

import asyncio
import json
from urllib.parse import urlparse
from uuid import UUID

import asyncpg
import boto3

from services.acp_planning.allocator import mark_slot_status
from services.acp_planning.models import Slot
from services.acp_produce.slot_runner import run_slot_production

TENANT_ID = "00000000-0000-0000-0000-000000000001"  # aa_internal
TOUR_ID = UUID("c9fb02ef-8db5-4849-a12e-e9718935039e")  # edit to verify a different tour's slots
MARKET = "US"
DONE_MARKER = "AA394_VERIFY_DONE"


class _SingleConnPool:
    """Minimal asyncpg.Pool-shaped adapter -- same pattern AA-367/375/376/377/378/391's
    own scripts use -- keeps one real connection for read-your-writes ordering."""

    def __init__(self, conn: asyncpg.Connection):
        self._conn = conn

    def acquire(self):
        return self

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


async def main() -> None:
    sm = boto3.client("secretsmanager", region_name="us-west-1")
    secret = sm.get_secret_value(SecretId="aa-cis/dev/rds")["SecretString"]
    u = urlparse(secret)
    db = await asyncpg.connect(
        host=u.hostname, port=u.port or 5432, user=u.username, password=u.password,
        database=u.path.lstrip("/"), ssl="require",
    )
    pool = _SingleConnPool(db)
    try:
        vtr = await db.fetchrow(
            "SELECT trip_url, url_alive FROM acp_contract.v_trip_registry WHERE id = $1",
            TOUR_ID,
        )
        print(f"v_trip_registry for {TOUR_ID}: {dict(vtr)}")
        cta = vtr["trip_url"] if vtr["url_alive"] else None
        print(f"computed cta_target (same formula as allocator.py:193): {cta!r}")
        if not cta:
            raise RuntimeError(
                "backfill did not take effect for this tour -- cta_target still None, aborting"
            )

        slot_rows = await db.fetch(
            "SELECT slot_id, week, channel, kind, tour_id, payload "
            "FROM acp_shared.acp_v2_slots WHERE tour_id = $1 ORDER BY channel",
            TOUR_ID,
        )
        print(f"\npersisted slots for this tour: {len(slot_rows)}")

        run_id = await db.fetchval(
            "INSERT INTO acp_shared.acp_v2_runs (tenant_id, year, week, status) "
            "VALUES ($1, extract(year from now())::int, 1, 'producing') "
            "ON CONFLICT (tenant_id, year, week) DO UPDATE SET status = 'producing' "
            "RETURNING run_id",
            TENANT_ID,
        )
        print(f"run_id: {run_id}")

        all_pieces = []
        for row in slot_rows:
            payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            slot = Slot(
                slot_id=row["slot_id"], week=row["week"], channel=row["channel"], kind=row["kind"],
                trip_id=row["tour_id"], atom_ids=payload.get("atom_ids", []),
                funnel_stage=payload.get("funnel_stage", "TOFU"), framework=payload.get("framework"),
                cta_target=cta,  # <-- the fix: fresh, real cta_target instead of the stale None
                topic_hint=payload.get("topic_hint"), keyword_seed=payload.get("keyword_seed"),
            )
            print(f"\n--- re-running slot {slot.slot_id} channel={slot.channel} "
                  f"cta_target={slot.cta_target!r} ---")
            try:
                pieces = await run_slot_production(db, pool, TENANT_ID, slot, run_id, MARKET, dfs_client=None)
            except Exception as e:
                print(f"[ERROR] slot={slot.slot_id} {type(e).__name__}: {e}")
                await mark_slot_status(pool, slot.slot_id, "skipped", reason=f"{type(e).__name__}: {e}")
                continue
            for p in pieces:
                f6 = next((g for g in p.gate_ledger if g.gate == "F6_route_to_sellable"), None)
                print(f"  [{p.piece_id}] channel={p.channel} status={p.status} "
                      f"held_reason={p.held_reason} F6={f6}")
            all_pieces.extend(pieces)
            await mark_slot_status(pool, slot.slot_id, "produced" if pieces else "skipped",
                                    reason=None if pieces else "run_slot_production returned no pieces (still)")

        passed = [p for p in all_pieces if p.status == "passed"]
        held = [p for p in all_pieces if p.status == "held"]
        f6_pass = sum(
            1 for p in all_pieces
            if any(g.gate == "F6_route_to_sellable" and g.passed for g in p.gate_ledger)
        )
        print(f"\n=== SUMMARY: total_pieces={len(all_pieces)} passed={len(passed)} held={len(held)} "
              f"F6_pass={f6_pass}/{len(all_pieces)} ===")

        # independent re-read from DB, not just in-memory objects
        db_pieces = await db.fetch(
            "SELECT piece_id, status, held_reason, gate_ledger FROM acp_deliver.pieces "
            "WHERE tenant_id = $1", TENANT_ID,
        )
        print(f"\nindependent DB re-read: {len(db_pieces)} piece rows now in acp_deliver.pieces")
        for r in db_pieces:
            ledger = json.loads(r["gate_ledger"]) if isinstance(r["gate_ledger"], str) else r["gate_ledger"]
            f6 = next((g for g in ledger if g.get("gate") == "F6_route_to_sellable"), None)
            print(f"  {r['piece_id']} | status={r['status']} | held_reason={r['held_reason']} | F6={f6}")

        print(f"\n{DONE_MARKER}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
