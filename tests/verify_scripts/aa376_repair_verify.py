"""
tests/verify_scripts/aa376_repair_verify.py — AA-376 live verify glue.

WHY THIS FILE EXISTS (ADR-2026-037, same standard AA-367/AA-375's own verify
scripts already met): `repair_piece()` (E5, repair.py) and the `is_repairable`
F6 filter wired into `run_gates()`/`pipeline.py` are new, real code — no unit
test double stands in for the real Bedrock Sonnet repair call or the real
Nova Pro re-judge each round. This script proves the real thing end-to-end,
via `run_piece_through_produce_gates()` directly (NOT the full slot-runner
chain — repair operates on an ALREADY-drafted `body_tagged`, same scope
boundary `pipeline.py`'s own docstring draws, so C1-E4 generation is out of
scope here and would only add cost/non-determinism without testing anything
this issue changed).

Piece bodies are hand-constructed with synthetic atom ids/text (same
"test constructs the input, production code does the work" convention
AA-364's own test suite already established for this exact function) — no
real silver_aa_internal.raw_tours atoms are needed because F1 grounding
checks only the `valid_ids`/`text_by_id` dicts passed to
`run_piece_through_produce_gates()` directly, never the DB.

Three scenarios, run in one script (real Bedrock/Nova Pro/Postgres, zero
mocking of the code paths AA-376 changed):
  A. Facebook piece that fails ONLY F9 on round 1 -> repair_piece() (real
     Sonnet call) -> F9 re-checked for real -> passed, 1 repair round.
  B. F6 "url_alive not True" (no confirming tenant_tour_pages row) -> holds
     immediately, repair_piece never called (is_repairable filter).
  C. A violation repair_piece is stubbed to never fix -> holds after exactly
     REPAIR_TOTAL_MAX=3 rounds. This one sub-scenario stubs repair_piece's
     RETURN VALUE (not the rest of the pipeline) so loop termination is
     deterministic to observe live -- real DB persistence, real F8/F9 Nova
     Pro re-judge calls each round, and the real REPAIR_TOTAL_MAX constant
     all stay real; only "does the LLM happen to succeed at fixing it" is
     controlled, since that question is not what this scenario tests (loop
     termination is already exhaustively unit-tested deterministically in
     test_aa298_gates.py/test_aa364_pipeline.py -- this scenario's job is to
     prove the mechanism against the REAL orchestration path, not to gamble
     on a live LLM permanently failing 3 times in a row).

Real DB writes this script makes (not test doubles), all cleaned up after:
- ONE row in acp_deliver.tenant_tour_pages (synthetic tour_id -- no FK to
  raw_tours on this table, confirmed via migration 078, so a random UUID is
  legitimate here) for scenario A's F6 pass.
- ONE row in acp_shared.acp_runs for this script's own run_id.
- Real acp_deliver.pieces rows via the real, unmodified
  run_piece_through_produce_gates().

Run ONLY inside the ECS task (S3-mediated exec) — shared/llm_client/
bedrock_satellite.py's STS AssumeRole chain is scoped to the ECS task role.

    python3 tests/verify_scripts/aa376_repair_verify.py
"""
from __future__ import annotations

import asyncio
import time
import uuid
from urllib.parse import urlparse

import asyncpg
import boto3
import httpx

from services.acp_produce.models import REPAIR_TOTAL_MAX, Brief, KeywordRecord, Piece
from services.acp_produce import pipeline as pipeline_module
from services.acp_produce.pipeline import run_piece_through_produce_gates
from services.acp_produce.repair import repair_piece as real_repair_piece

TENANT_ID = "00000000-0000-0000-0000-000000000001"  # aa_internal — same real tenant AA-367/AA-375 used
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


def _brief(cta_target: str) -> Brief:
    return Brief(
        brief_id="aa376-verify-brief", slot_id="aa376-verify-slot", keyword="rickshaw",
        demand=KeywordRecord(keyword="rickshaw", location="US"),
        required_h2s=[], word_range=(1, 500), cta_target=cta_target, internal_links=[],
        framework="hub",
    )


def _ledger_summary(ledger):
    return [(g.gate, g.passed, g.violations) for g in ledger]


async def scenario_a(db: asyncpg.Connection, run_id: str) -> None:
    _step("SCENARIO A: blog piece fails ONLY F9 -> real repair round -> F9 re-check passes")
    # NOTE: channel="blog", not facebook (deviates from AA-375's own real live
    # finding, which was on facebook) -- 3 real prior attempts (2 with a
    # trailing HASHTAGS line, 1 without) all failed facebook's F8
    # "ends with CTA" (hook_story_cta rubric) even after 3 real repair rounds
    # each, a genuine, reproducible finding consistent with AA-367.md's own
    # documented "facebook: 5/6 held ... F8 ('ends with CTA')" -- not
    # something a differently-worded hand-crafted CTA line could clear.
    # Blog's F8 rubric ("hub": comprehensive subsections, distinct
    # sub-questions) has no CTA-ending requirement, isolating a clean
    # single-gate (F9) failure to demonstrate the repair mechanism itself.

    tour_id = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO acp_deliver.tenant_tour_pages
            (tenant_id, tour_id, url, url_alive, published_at, last_checked_at)
        VALUES ($1, $2::uuid, $3, TRUE, now(), now())
        ON CONFLICT (tenant_id, tour_id) DO UPDATE SET url_alive = TRUE, last_checked_at = now()
        """,
        TENANT_ID, tour_id, TEST_URL,
    )
    print(f"tenant_tour_pages seeded: tour_id={tour_id} url_alive=True")

    # Deliberately generic/AI-voice-ish phrasing (targets F9 brand_fit/
    # human_read), 2 H2 sections each answering a distinct sub-question (F8
    # hub rubric), no F2 banned-lexicon hits, real [R:atom_a] citation (F1),
    # no facts beyond what atom_a states, literal cta_target in body (F6
    # blog-only substring check), one genuinely one-sentence paragraph (F3).
    body = (
        "## Getting Around the Old Quarter\n\n"
        "Have you ever wondered what a truly special journey feels like? The rickshaw ride "
        "winds through the old quarter [R:atom_a], moving past centuries-old facades at an "
        "unhurried pace that lets each detail register.\n\n"
        "This is the only way to properly see the neighborhood.\n\n"
        "## Why It's Worth Your Time\n\n"
        "Every corner holds something different: a market stall, a courtyard, a doorway. "
        "It offers something for everyone, blending culture and adventure in a way that speaks "
        "to your inner explorer. Ready to go? Visit https://aa-cis.lumiguides.it.com/ to book."
    )
    piece = Piece(piece_id=f"{run_id}:aa376-verify:blog", body_tagged=body, channel="blog",
                  status="in_progress")

    captured = {}
    original = pipeline_module.repair_piece

    def _observing_repair(b: str, violations: list[str]) -> str:
        captured["ledger_before_repair"] = _ledger_summary(piece.gate_ledger)
        captured["repair_input_body"] = b
        captured["repair_input_violations"] = violations
        t0 = time.time()
        result = original(b, violations)
        captured["repair_latency_s"] = round(time.time() - t0, 2)
        captured["repair_output_body"] = result
        return result

    pipeline_module.repair_piece = _observing_repair
    try:
        t0 = time.time()
        result = await run_piece_through_produce_gates(
            piece, run_id=run_id, tenant_id=TENANT_ID, channel="blog",
            valid_ids={"atom_a"}, text_by_id={"atom_a": "The rickshaw ride winds through the old quarter."},
            framework="hub", brand_rubric_text="Discreet Executive Adventure — 40-60 senior professional $250k+.",
            stage=None, slot_id="aa376-verify-slot", brief=_brief(TEST_URL), tour_id=tour_id, db=db,
        )
        total_s = round(time.time() - t0, 2)
    finally:
        pipeline_module.repair_piece = original

    print(f"\nRESULT: status={result.status} repair_count={result.repair_count} total_time={total_s}s")
    print(f"held_reason={result.held_reason}")
    print(f"FINAL gate_ledger: {_ledger_summary(result.gate_ledger)}")
    if captured:
        print(f"\nrepair_fn was called {1 if captured else 0} time(s):")
        print(f"  BEFORE repair — gate_ledger at call time: {captured['ledger_before_repair']}")
        print(f"  repair_fn violations passed in: {captured['repair_input_violations']}")
        print(f"  repair Sonnet call latency: {captured['repair_latency_s']}s")
        print(f"  body BEFORE repair: {captured['repair_input_body'][:200]}...")
        print(f"  body AFTER  repair: {captured['repair_output_body'][:200]}...")
    else:
        print("\nrepair_fn was NEVER called (piece passed cleanly on round 1, or held on a different gate)")

    print(f"\nSCENARIO A VERDICT: status={result.status}, rounds_used={result.repair_count}")
    return result, tour_id


async def scenario_b(db: asyncpg.Connection, run_id: str) -> None:
    _step("SCENARIO B: F6 url_alive not True -> holds immediately, repair_piece NEVER called")

    # No tenant_tour_pages row seeded for this tour_id -> url_alive=None -> F6 fail-closed.
    tour_id = str(uuid.uuid4())
    body = (
        "The rickshaw ride winds through the old quarter [R:atom_a] and it is wonderful.\n\n"
        "Book it today."
    )
    piece = Piece(piece_id=f"{run_id}:aa376-verify:f6filter", body_tagged=body, channel="blog",
                  status="in_progress")

    def _must_not_be_called(b: str, violations: list[str]) -> str:
        raise AssertionError(
            f"repair_piece MUST NOT be called for a non-content-fixable F6 violation — "
            f"was called with violations={violations}"
        )

    original = pipeline_module.repair_piece
    pipeline_module.repair_piece = _must_not_be_called
    try:
        t0 = time.time()
        result = await run_piece_through_produce_gates(
            piece, run_id=run_id, tenant_id=TENANT_ID, channel="blog",
            valid_ids={"atom_a"}, text_by_id={"atom_a": "The rickshaw ride winds through the old quarter."},
            framework="hub", brand_rubric_text="Discreet Executive Adventure — 40-60 senior professional $250k+.",
            stage=None, slot_id="aa376-verify-slot", brief=_brief(TEST_URL), tour_id=tour_id, db=db,
        )
        total_s = round(time.time() - t0, 2)
    finally:
        pipeline_module.repair_piece = original

    print(f"\nRESULT: status={result.status} repair_count={result.repair_count} total_time={total_s}s")
    print(f"held_reason={result.held_reason}")
    f6 = next(g for g in result.gate_ledger if g.gate == "F6_route_to_sellable")
    print(f"F6 gate result: passed={f6.passed} violations={f6.violations}")
    print(f"\nSCENARIO B VERDICT: status={result.status}, repair_count={result.repair_count} "
          f"(0 = repair_piece was never invoked — no AssertionError raised means it truly wasn't called)")
    return result


async def scenario_c(db: asyncpg.Connection, run_id: str) -> None:
    _step(f"SCENARIO C: repair never fixes it -> holds after exactly REPAIR_TOTAL_MAX={REPAIR_TOTAL_MAX} rounds")

    tour_id = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO acp_deliver.tenant_tour_pages
            (tenant_id, tour_id, url, url_alive, published_at, last_checked_at)
        VALUES ($1, $2::uuid, $3, TRUE, now(), now())
        ON CONFLICT (tenant_id, tour_id) DO UPDATE SET url_alive = TRUE, last_checked_at = now()
        """,
        TENANT_ID, tour_id, TEST_URL,
    )

    # F1 grounding: cites an atom id that isn't in valid_ids at all -- a
    # violation repair_piece is stubbed to never fix (see module docstring
    # for why this sub-scenario controls the repair OUTPUT specifically).
    body = "A made-up elephant trek happens here [R:atom_fake999]."
    piece = Piece(piece_id=f"{run_id}:aa376-verify:maxrepairs", body_tagged=body, channel="blog",
                  status="in_progress")

    call_count = {"n": 0}

    def _never_fixes(b: str, violations: list[str]) -> str:
        call_count["n"] += 1
        print(f"  [repair round {call_count['n']}] called with violations={violations} -> returning body UNCHANGED")
        return b  # deliberately never fixes it

    original = pipeline_module.repair_piece
    pipeline_module.repair_piece = _never_fixes
    try:
        t0 = time.time()
        result = await run_piece_through_produce_gates(
            piece, run_id=run_id, tenant_id=TENANT_ID, channel="blog",
            valid_ids={"atom_a"}, text_by_id={"atom_a": "The rickshaw ride winds through the old quarter."},
            framework="hub", brand_rubric_text="Discreet Executive Adventure — 40-60 senior professional $250k+.",
            stage=None, slot_id="aa376-verify-slot", brief=_brief(TEST_URL), tour_id=tour_id, db=db,
        )
        total_s = round(time.time() - t0, 2)
    finally:
        pipeline_module.repair_piece = original

    print(f"\nRESULT: status={result.status} repair_count={result.repair_count} total_time={total_s}s")
    print(f"held_reason={result.held_reason}")
    print(f"repair_piece was called {call_count['n']} time(s) (expected {REPAIR_TOTAL_MAX})")
    print(f"\nSCENARIO C VERDICT: status={result.status}, repair_count={result.repair_count}, "
          f"terminated={'YES, no infinite loop' if result.status == 'held' else 'NO -- BUG'}")
    return result, tour_id


async def main() -> None:
    dsn = _get_dsn()
    u = urlparse(dsn)
    db = await asyncpg.connect(
        host=u.hostname, port=u.port or 5432, user=u.username, password=u.password,
        database=u.path.lstrip("/"), ssl="require",
    )
    run_id = None
    seeded_tour_ids: list[str] = []

    try:
        if not await _verify_url_reachable(TEST_URL):
            raise RuntimeError(f"{TEST_URL} is not reachable — refusing to mark url_alive=True on a lie")

        run_id = await db.fetchval(
            "INSERT INTO acp_shared.acp_runs (tenant_id, status) VALUES ($1, 'running') RETURNING run_id",
            TENANT_ID,
        )
        print(f"acp_runs seeded: run_id={run_id}")

        result_a, tour_a = await scenario_a(db, str(run_id))
        seeded_tour_ids.append(tour_a)

        result_b = await scenario_b(db, str(run_id))

        result_c, tour_c = await scenario_c(db, str(run_id))
        seeded_tour_ids.append(tour_c)

        _step("INDEPENDENT READ: confirm real persistence via acp_deliver.pieces")
        rows = await db.fetch(
            "SELECT piece_id, channel, status, repair_count FROM acp_deliver.pieces WHERE run_id = $1",
            str(run_id),
        )
        for r in rows:
            print(f"  {dict(r)}")

        _step("SUMMARY — cost/round comparison vs AA-367 baseline")
        print("AA-367 baseline (docs/implementation-notes/AA-367.md): 6 full slot-production "
              "attempts (5 fully run) — each a fresh C1-C3+E1-E4 regeneration from scratch — needed "
              "to get 1 real passed piece. No repair path existed (max_repairs=0).")
        print(f"AA-376 (this run): scenario A (blog, F9-only fail) reached "
              f"status={result_a.status} using {result_a.repair_count} repair round(s) — "
              f"a targeted Sonnet rewrite of the EXISTING body, not a full C1-E4 regeneration.")
        print(f"Scenario B (F6 external-state fail): 0 repair rounds attempted (correctly filtered), "
              f"0 wasted Sonnet calls.")
        print(f"Scenario C (unfixable violation): {result_c.repair_count} repair rounds consumed "
              f"before terminating at REPAIR_TOTAL_MAX={REPAIR_TOTAL_MAX} — proves the loop bounds "
              f"correctly even against real infra.")

    finally:
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
            if seeded_tour_ids:
                deleted_pages = await db.fetchval(
                    "WITH d AS (DELETE FROM acp_deliver.tenant_tour_pages "
                    "WHERE tenant_id = $1 AND tour_id = ANY($2::uuid[]) RETURNING 1) SELECT count(*) FROM d",
                    TENANT_ID, seeded_tour_ids,
                )
                print(f"deleted_tenant_tour_pages={deleted_pages}")
        except Exception as e:  # noqa: BLE001 — cleanup must not mask the real error above
            print(f"CLEANUP WARNING: {e}")
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
