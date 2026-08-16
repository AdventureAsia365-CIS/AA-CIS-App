"""
tests/verify_scripts/aa367_real_piece_chain.py — AA-367 live verify glue.

WHY THIS FILE EXISTS (STEP 0 decision 1, Nghiep 06/08/2026): the real N7
C1-E5 building blocks (AA-369/370/371/372, PR #110) exist and are each
independently unit-tested, but no production "slot-runner" chains them
against a real Slot yet -- adapt.py's own docstring says so directly: "no
real slot-runner exists yet to enforce this, so it's a call-order contract,
not a code guard." That gap is tracked separately as AA-375 and is
explicitly NOT this issue's scope. AA-367 (assemble_packet() /
maybe_mark_packet_ready() / deliver_packet(), services/acp_produce/
packets.py) still needs >=1 REAL, non-hand-constructed 'passed' Piece to
verify against -- Linear AA-367's own verify checklist requires it. This
script is that one-off glue: test-only, run manually against the real dev
DB via the S3-mediated ECS exec pattern (global CLAUDE.md's canonical
pattern), never imported by services/ code, never run by pytest/CI.

NO MOCKING anywhere below -- every C1/C2/C3/E1/E2/E3/E4/F1-F9 call is the
real function against real DataForSEO/Bedrock/Postgres. The only
hand-assembled object is the `Slot` itself (real atom_ids pulled from a real
tour, everything else literal) -- the same "test constructs the input,
production code does the work" convention every existing N7 unit test
already uses (see test_aa364_pipeline.py's own module docstring).

Real DB writes this script makes (not test doubles):
- ONE row in acp_deliver.tenant_tour_pages for TOUR_ID. This table has 0
  rows anywhere in dev (confirmed AA-367 STEP 0, 06/08/2026) -- nothing in
  the codebase writes it yet, which is why F6 (gates.py::
  gate_route_to_sellable) fails closed on every real tour today. That gap is
  real and is flagged in the AA-367 report, NOT fixed broadly here --this
  script only seeds the one row it needs, and only marks url_alive=True
  after an ACTUAL HTTP check (_verify_url_reachable()), never a hardcoded
  claim.
- ONE row in acp_shared.acp_runs for this script's own run (0 rows existed
  in dev before this, confirmed AA-367 STEP 0) -- the real FK
  `acp_deliver.pieces.run_id REFERENCES acp_shared.acp_runs(run_id)` needs
  one.
- Real acp_deliver.pieces / acp_deliver.packets rows via the real,
  unmodified services/acp_produce/pipeline.py and packets.py functions.

Run ONLY inside the ECS task (S3-mediated exec) -- shared/llm_client/
bedrock_satellite.py's own docstring is explicit that its STS AssumeRole
chain is scoped to "identity ECS task role hiện tại"; this will NOT work
from a local/laptop AWS profile.

    python3 tests/verify_scripts/aa367_real_piece_chain.py
"""
from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import asyncpg
import boto3
import httpx

from services.acp_planning.models import Slot
from services.acp_produce import packets
from services.acp_produce.adapt import adapt_channels
from services.acp_produce.dataforseo import parse_top_pages
from services.acp_produce.faq import apply_faq
from services.acp_produce.generation import build_outline, generate_draft
from services.acp_produce.models import Piece
from services.acp_produce.pipeline import run_piece_through_produce_gates
from services.acp_produce.research import compile_brief, fetch_slot_atoms, fetch_slot_demand_data
from services.content_generation.brand_standards import AA_BRAND_IDENTITY_PROMPT
from shared.secrets import get_dataforseo_creds

TENANT_ID = "00000000-0000-0000-0000-000000000001"  # aa_internal — real tenant (raw_tours confirms this)
TOUR_ID = "b4d315a6-21cb-4d2b-9a2f-9d654388078a"  # real tour, 26 live atoms (AA-367 STEP 0 recon, 06/08/2026)
MARKET = "US"  # source market (KeywordRecord.location semantics — never destination)
TEST_URL = "https://aa-cis.lumiguides.it.com/"  # real, live-checked below before being marked url_alive=True


def _step(title: str) -> None:
    print(f"\n{'=' * 12} {title} {'=' * 12}")


async def _verify_url_reachable(url: str) -> bool:
    """Real HTTP check — this script never marks url_alive=True on a claim
    it hasn't itself confirmed (ADR-2026-037 no-fabrication spirit)."""
    async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
        r = await client.get(url)
        print(f"HTTP check {url} -> {r.status_code}")
        return r.status_code < 500  # a 3xx (e.g. redirect to login) still means "alive"


def _get_dsn() -> str:
    sm = boto3.client("secretsmanager", region_name="us-west-1")
    return sm.get_secret_value(SecretId="aa-cis/dev/rds")["SecretString"]


class _SingleConnPool:
    """Minimal `asyncpg.Pool`-shaped adapter around one already-open
    connection, so `atom_usage.write_usage_log()` (which calls
    `pool.acquire()`) can run against this script's single connection.
    Test-only glue — production callers of `deliver_packet()` pass a real
    `asyncpg.Pool` (e.g. `api/main.py`'s `get_pool()`), this class exists
    only because this script deliberately keeps one connection for its own
    read-your-writes ordering guarantees across the whole run."""

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

    try:
        # ---------------------------------------------------------- SETUP
        _step("SETUP: seed tenant_tour_pages (real HTTP check) + acp_runs")
        if not await _verify_url_reachable(TEST_URL):
            raise RuntimeError(f"{TEST_URL} is not reachable — refusing to mark url_alive=True on a lie")

        await db.execute(
            """
            INSERT INTO acp_deliver.tenant_tour_pages
                (tenant_id, tour_id, url, url_alive, published_at, last_checked_at)
            VALUES ($1, $2::uuid, $3, TRUE, now(), now())
            ON CONFLICT (tenant_id, tour_id) DO UPDATE SET
                url = EXCLUDED.url, url_alive = TRUE, last_checked_at = now()
            """,
            TENANT_ID, TOUR_ID, TEST_URL,
        )
        print(f"tenant_tour_pages seeded: tenant={TENANT_ID} tour={TOUR_ID} url={TEST_URL} url_alive=True")

        run_id = await db.fetchval(
            "INSERT INTO acp_shared.acp_runs (tenant_id, status) VALUES ($1, 'running') RETURNING run_id",
            TENANT_ID,
        )
        print(f"acp_runs seeded: run_id={run_id}")

        atom_rows = await db.fetch(
            """
            SELECT atom_id FROM acp_contract.tour_atoms
            WHERE tour_id = $1::uuid AND NOT deleted AND NOT is_empty_marker
            ORDER BY atom_id LIMIT 6
            """,
            TOUR_ID,
        )
        atom_ids = [r["atom_id"] for r in atom_rows]
        print(f"real atom_ids selected ({len(atom_ids)}): {atom_ids}")

        slot = Slot(
            slot_id="aa367-verify-slot-1", week=1, channel="blog", kind="evergreen",
            trip_id=TOUR_ID, atom_ids=atom_ids, funnel_stage="TOFU",
            keyword_seed="India tours", cta_target=TEST_URL,
        )

        # ---------------------------------------------------------- C1/C2
        _step("C1/C2: fetch_slot_demand_data (real DataForSEO)")
        demand, serp = await fetch_slot_demand_data(slot, MARKET)
        print(f"demand: keyword={demand.keyword!r} volume={demand.volume} confidence={demand.confidence}")
        print(f"serp: intent={serp.intent_verdict} paa={len(serp.paa_questions)} domains={len(serp.top10_domains)}")

        login, password = get_dataforseo_creds()
        top_pages = await parse_top_pages(login, password, demand.keyword, MARKET)
        print(f"top_pages crawled: {len(top_pages)}")

        # ---------------------------------------------------------- C3
        _step("C3: compile_brief (real, demand-law + gap_statement via Haiku satellite)")
        brief = await compile_brief(db, TENANT_ID, slot, demand, serp, top_pages)
        if brief is None:
            raise RuntimeError("TOPIC REJECTED by compile_brief() — see acp_shared.unknown_ledger for the reason")
        print(f"brief_id={brief.brief_id} framework={brief.framework} required_h2s={brief.required_h2s}")
        print(f"faq_candidates={len(brief.faq_candidates)} gap_statement={brief.gap_statement!r}")

        atoms = await fetch_slot_atoms(atom_ids, db)
        atom_text_by_id = {a["atom_id"]: a["text"] for a in atoms}

        # ---------------------------------------------------------- E1/E2
        _step("E1/E2: build_outline + generate_draft (real Sonnet satellite)")
        outline = build_outline(brief)
        print(f"outline sections: {[s.title for s in outline]}")
        blog_body = generate_draft(brief, outline, atom_text_by_id)
        print(f"blog draft length: {len(blog_body)} chars")
        print(f"blog draft (first 500 chars):\n{blog_body[:500]}")

        blog_piece = Piece(piece_id="aa367-verify-blog", body_tagged=blog_body, channel="blog", status="in_progress")

        # E3 before E4 — adapt.py's own call-order contract (no code guard, docstring-only today)
        _step("E3: adapt_channels (real Sonnet satellite, facebook + tiktok)")
        channel_pieces = adapt_channels(blog_piece, atom_text_by_id)
        print(f"channel pieces produced: {[p.piece_id for p in channel_pieces]}")
        for p in channel_pieces:
            print(f"  [{p.channel}] {p.body_tagged[:300]}")

        # ---------------------------------------------------------- E4
        _step("E4: apply_faq (real Sonnet satellite)")
        blog_piece = apply_faq(blog_piece, brief, atom_text_by_id)
        print(f"blog piece faq_items: {len(blog_piece.faq_items)}, faq_jsonld: {blog_piece.faq_jsonld is not None}")

        # ---------------------------------------------------------- F1-F9 (real, all channels)
        _step("F1-F9: run_piece_through_produce_gates (real, no mocking)")
        all_pieces = [blog_piece] + channel_pieces
        passed_piece_ids: list[str] = []
        for piece in all_pieces:
            result = await run_piece_through_produce_gates(
                piece, run_id=str(run_id), tenant_id=TENANT_ID, channel=piece.channel,
                valid_ids=set(atom_text_by_id), text_by_id=atom_text_by_id,
                framework=brief.framework, brand_rubric_text=AA_BRAND_IDENTITY_PROMPT,
                stage=None, slot_id=slot.slot_id, brief=brief, tour_id=TOUR_ID, db=db,
            )
            gate_summary = [(g.gate, g.passed) for g in result.gate_ledger]
            print(f"[{result.piece_id}] channel={piece.channel} status={result.status} "
                  f"held_reason={result.held_reason}")
            print(f"  gate_ledger: {gate_summary}")
            if result.status == "passed":
                passed_piece_ids.append(result.piece_id)

        print(f"\nREAL PASSED PIECE IDS: {passed_piece_ids}")
        if not passed_piece_ids:
            raise RuntimeError(
                "0 pieces reached status='passed' through the real gate stack — "
                "cannot verify assemble_packet()/maybe_mark_packet_ready()/deliver_packet() "
                "against real data. Report this as a real finding, do not fake a passed piece."
            )

        # ---------------------------------------------------------- packet assembly (AA-367)
        _step("AA-367: create_packet -> assemble_packet -> maybe_mark_packet_ready -> deliver_packet")
        today = await db.fetchval("SELECT CURRENT_DATE")
        iso_year, iso_week, _ = today.isocalendar()
        iso_month = today.month
        try:
            packet_id = await packets.create_packet(db, TENANT_ID, iso_year, iso_month, iso_week)
        except asyncpg.UniqueViolationError:
            packet_id = await db.fetchval(
                "SELECT packet_id FROM acp_deliver.packets WHERE tenant_id=$1 AND year=$2 AND month=$3 AND week=$4",
                TENANT_ID, iso_year, iso_month, iso_week,
            )
        print(f"packet_id={packet_id} (year={iso_year} month={iso_month} week={iso_week})")

        status_row = await db.fetchrow(
            "SELECT status, publish_mode FROM acp_deliver.packets WHERE packet_id=$1", packet_id)
        print(f"packets row right after create/reuse: {dict(status_row)}")

        n_assigned = await packets.assemble_packet(db, packet_id, passed_piece_ids)
        print(f"assemble_packet assigned {n_assigned} piece(s)")

        status_row = await db.fetchrow("SELECT status FROM acp_deliver.packets WHERE packet_id=$1", packet_id)
        print(f"packets.status after assemble_packet: {status_row['status']}")

        # usage_log BEFORE ready and BEFORE delivered — must be untouched
        usage_before = await db.fetch(
            "SELECT atom_id, usage_log FROM acp_contract.tour_atoms WHERE atom_id = ANY($1::text[])",
            list(atom_text_by_id.keys()),
        )
        print("usage_log BEFORE ready/delivered:")
        for r in usage_before:
            print(f"  {r['atom_id']}: {r['usage_log']}")

        advanced = await packets.maybe_mark_packet_ready(db, packet_id)
        print(f"maybe_mark_packet_ready -> advanced={advanced}")

        status_row = await db.fetchrow("SELECT status FROM acp_deliver.packets WHERE packet_id=$1", packet_id)
        print(f"packets.status after maybe_mark_packet_ready: {status_row['status']}")

        usage_after_ready = await db.fetch(
            "SELECT atom_id, usage_log FROM acp_contract.tour_atoms WHERE atom_id = ANY($1::text[])",
            list(atom_text_by_id.keys()),
        )
        print("usage_log AFTER ready, BEFORE delivered (must be unchanged from BEFORE):")
        for r in usage_after_ready:
            print(f"  {r['atom_id']}: {r['usage_log']}")
        assert usage_before == usage_after_ready, "usage_log changed before delivered — STEP 5 boundary violated!"

        usage_result = await packets.deliver_packet(db, pool, packet_id)
        print(f"deliver_packet -> write_usage_log result: {usage_result}")

        status_row = await db.fetchrow(
            "SELECT status, delivered_at FROM acp_deliver.packets WHERE packet_id=$1", packet_id)
        print(f"packets row after deliver_packet: {dict(status_row)}")

        usage_after_delivered = await db.fetch(
            "SELECT atom_id, usage_log FROM acp_contract.tour_atoms WHERE atom_id = ANY($1::text[])",
            list(atom_text_by_id.keys()),
        )
        print("usage_log AFTER delivered (must show exactly the passed pieces' cited atoms, +1 entry each):")
        for r in usage_after_delivered:
            print(f"  {r['atom_id']}: {r['usage_log']}")

        _step("DONE")
        print(f"packet_id={packet_id} passed_piece_ids={passed_piece_ids} usage_result={usage_result}")

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
