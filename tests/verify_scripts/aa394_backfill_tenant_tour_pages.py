"""
tests/verify_scripts/aa394_backfill_tenant_tour_pages.py — AA-394 TEST_BACKFILL.

*** THIS IS NOT THE REAL LANDING PAGE ENGINE. IT WILL BE REPLACED BY AA-395 (per-tenant,
*** per-tour white-label landing page, ADR-2026-030) WHEN THAT WORK IS DONE -- DO NOT
*** point production traffic or Gate C review at anything this script writes, and DO NOT
*** reuse this script's approach as a shortcut once AA-395 exists.

WHY THIS FILE EXISTS (AA-394, Nghiep, 09/08/2026): `acp_deliver.tenant_tour_pages`
(migration 078, AA-302) has been empty since it was created -- ADR-2026-030 decided AA
should host a real white-label tour page per tenant, but that "+1-2 sprint landing page
engine" was never built (tracked as AA-395, not started). With the table empty, EVERY N6
slot gets `cta_target=None` (services/acp_planning/allocator.py:193:
`cta = t.trip_url if t.url_alive else None`) and `research.py::compile_brief()` rejects
with `no_cta_target` before any Piece is ever created -- F6 (gate_route_to_sellable) never
even gets a chance to run. AA-391's real S0->N8 chain run (Laos+South Korea, 87 tours)
produced exactly 0 pieces because of this.

WHAT THIS SCRIPT DOES: writes ONE shared, non-tour-specific, but genuinely live/reachable
URL into `acp_deliver.tenant_tour_pages` for every tour matching the given tenant +
destination filter, purely so `cta_target`/F6 stop failing closed. It does NOT create or
represent a real per-tour sales page -- there is no tour-specific content behind the URL.
Real per-tour landing pages are AA-395's job.

HOW TO RECOGNIZE THIS AS TEST DATA when reading `acp_deliver.tenant_tour_pages` later:
every row this script writes has the IDENTICAL `url` value and `published_at` values
clustered at one run timestamp -- a real per-tenant landing page engine would never
produce that shape.

FIRST RUN (09/08/2026): TENANT_ID=aa_internal, DESTINATIONS=("Laos", "South Korea"),
URL="https://aa-cis.lumiguides.it.com/" (live CIS marketing root, confirmed HTTP 200
out-of-band before running) -- 87 tours (57 Laos + 30 South Korea), matching AA-391's
real dataset. See AA-394 Linear comments (09/08/2026) for the full before/after verify.

REUSE: edit TENANT_ID_TEXT / DESTINATIONS / TEST_URL below for a different backfill batch
(e.g. a different destination) before AA-395 lands. Safe to re-run -- `ON CONFLICT
(tenant_id, tour_id) DO UPDATE` makes it idempotent.

Run via the S3-mediated ECS exec pattern (global CLAUDE.md's canonical pattern) -- this
container has no local psql/aws CLI. Never imported by services/ code, never run by
pytest/CI (same convention as every other tests/verify_scripts/aaNNN_*.py file).
"""
import asyncio
import json
from urllib.parse import urlparse

import asyncpg
import boto3

TEST_URL = "https://aa-cis.lumiguides.it.com/"  # live CIS root domain -- confirm HTTP 200 out-of-band before reuse
TENANT_ID_TEXT = "00000000-0000-0000-0000-000000000001"  # aa_internal, TEXT convention (AA-367 precedent)
DESTINATIONS = ("Laos", "South Korea")  # edit for a different backfill batch


async def main() -> None:
    sm = boto3.client("secretsmanager", region_name="us-west-1")
    secret = sm.get_secret_value(SecretId="aa-cis/dev/rds")["SecretString"]
    u = urlparse(secret)
    conn = await asyncpg.connect(
        host=u.hostname, port=u.port or 5432, user=u.username,
        password=u.password, database=u.path.lstrip("/"), ssl="require",
    )
    try:
        trip_rows = await conn.fetch(
            "SELECT id, name, destination FROM acp_contract.v_trip_registry "
            "WHERE tenant_id = $1 AND destination = ANY($2::text[]) ORDER BY destination, id",
            TENANT_ID_TEXT, list(DESTINATIONS),
        )
        print(f"tour count for {DESTINATIONS}: {len(trip_rows)}")
        by_dest: dict[str, int] = {}
        for r in trip_rows:
            by_dest[r["destination"]] = by_dest.get(r["destination"], 0) + 1
        print("by destination:", by_dest)

        before = await conn.fetchval("SELECT count(*) FROM acp_deliver.tenant_tour_pages")
        print(f"acp_deliver.tenant_tour_pages rows before backfill: {before}")

        rows = [(TENANT_ID_TEXT, r["id"], TEST_URL) for r in trip_rows]
        await conn.executemany(
            """
            INSERT INTO acp_deliver.tenant_tour_pages
                (tenant_id, tour_id, url, url_alive, published_at, last_checked_at)
            VALUES ($1, $2::uuid, $3, TRUE, now(), now())
            ON CONFLICT (tenant_id, tour_id) DO UPDATE SET
                url = EXCLUDED.url, url_alive = TRUE, last_checked_at = now()
            """,
            rows,
        )

        after = await conn.fetchval("SELECT count(*) FROM acp_deliver.tenant_tour_pages")
        print(f"acp_deliver.tenant_tour_pages rows after backfill: {after}")

        sample = await conn.fetch(
            "SELECT tenant_id, tour_id, url, url_alive, published_at FROM acp_deliver.tenant_tour_pages "
            "ORDER BY published_at DESC LIMIT 3"
        )
        for s in sample:
            print("sample row:", dict(s))

        # confirm v_trip_registry (which LEFT JOINs this table) now surfaces trip_url/url_alive
        vtr = await conn.fetch(
            "SELECT id, name, trip_url, url_alive FROM acp_contract.v_trip_registry "
            "WHERE tenant_id = $1 AND destination = ANY($2::text[]) LIMIT 3",
            TENANT_ID_TEXT, list(DESTINATIONS),
        )
        print("\nv_trip_registry sample after backfill (trip_url should be non-null now):")
        for v in vtr:
            print(dict(v))

        out = {"tour_count": len(trip_rows), "url": TEST_URL, "tenant_id": TENANT_ID_TEXT,
               "before": before, "after": after}
        with open("/tmp/aa394_backfill_result.json", "w") as f:
            json.dump(out, f)
        print("\nwrote /tmp/aa394_backfill_result.json")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
