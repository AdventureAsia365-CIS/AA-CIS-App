"""tests/verify_scripts/aa392_sonnet_writer_verify.py — AA-392 live quality verify.

WHY THIS FILE EXISTS (ADR-2026-037): AA-392 moved S1-from-atom's writer off Palmyra X5 onto
Bedrock satellite Sonnet (services/content_generation/s1_from_atom.py, DEFAULT_MODEL_TIER=
"claude" now). This script calls the real, unmodified generate_s1_from_atom() against a small,
deliberately chosen sample of real Laos/South Korea tours that AA-391's own (killed mid-run)
S0->N8 verify already decomposed+curated (764 atoms persisted, 87 tours) — no new decompose/
curation needed, this is read-only against existing atoms plus one real Sonnet call per tour.

Sample (5 tours, chosen for a real Palmyra-vs-Sonnet comparison + a size spread):
  - c9fb02ef-... "Exploring South Korea": AA-391's own killed run already got a PASSED Palmyra
    result for this exact tour before being stopped (citation_count=44, words_per_citation=18.1,
    retries=1) — same tour_id, same atoms, re-run here under Sonnet for a real side-by-side.
  - ca893afe-...  "14-Day South Korea Adventure": AA-391's run got a Palmyra GroundingError
    (entailment failures, exhausted 3 attempts) on this one — worth seeing if Sonnet does better.
  - 81cd098e-... "Namhae Island Adventure": thin (6 atoms).
  - 042cc47b-... "South Korea by Road Bike": rich (46 atoms).
  - 56233353-... "IMPRESSIONS OF LAOS": a Laos tour, mid-size (14 atoms).

Per Nghiep's explicit instruction (AA-392): this script verifies QUALITY on this small sample
ONLY. It does not resume AA-391's full 87-tour run, and makes no DB writes beyond what
generate_s1_from_atom() already does internally (none — it's a pure read+LLM-call function,
the router's _log_run() is what writes acp_contract.s1_from_atom_runs, not called here).

Run ONLY inside the ECS task (S3-mediated exec).

    python3 tests/verify_scripts/aa392_sonnet_writer_verify.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/app")


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
    _daemonize("/tmp/aa392_output.log")

import asyncio
import json
from urllib.parse import urlparse

import asyncpg
import boto3

from services.content_generation.s1_from_atom import DEFAULT_MODEL_TIER, GroundingError, generate_s1_from_atom

SAMPLE = [
    ("c9fb02ef-8db5-4849-a12e-e9718935039e", "prior Palmyra result: PASSED, citation_count=44, "
     "words_per_citation=18.1, retries=1"),
    ("ca893afe-27e2-431b-9596-b92514e7f98c", "prior Palmyra result: GroundingError after 3 attempts "
     "(entailment failures, e.g. novel '14' in a day-count sentence)"),
    ("81cd098e-5ecc-4cab-8593-6a6ebace67f7", "thin tour, 6 atoms, no prior Palmyra attempt"),
    ("042cc47b-909c-4c7b-af86-5acb992d00e2", "rich tour, 46 atoms, no prior Palmyra attempt"),
    ("56233353-30fb-4f00-a7b6-f5de9a9c086a", "Laos tour, 14 atoms, no prior Palmyra attempt"),
]


def _get_dsn() -> str:
    sm = boto3.client("secretsmanager", region_name="us-west-1")
    return sm.get_secret_value(SecretId="aa-cis/dev/rds")["SecretString"]


async def main() -> None:
    print(f"DEFAULT_MODEL_TIER={DEFAULT_MODEL_TIER!r} (must be 'claude', never 'palmyra')")
    assert DEFAULT_MODEL_TIER == "claude"

    dsn = _get_dsn()
    u = urlparse(dsn)
    db = await asyncpg.connect(
        host=u.hostname, port=u.port or 5432, user=u.username, password=u.password,
        database=u.path.lstrip("/"), ssl="require",
    )

    class _Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    pool = _Pool()
    results = []
    try:
        for tour_id, note in SAMPLE:
            row = await db.fetchrow(
                "SELECT tour_id, src_name, country FROM silver_aa_internal.raw_tours WHERE tour_id = $1::uuid",
                tour_id,
            )
            if not row:
                print(f"\n=== {tour_id} === NOT FOUND in raw_tours, skipping")
                continue
            tour = {"name": row["src_name"], "country": row["country"]}
            print(f"\n=== {tour_id} ({tour['name']}) ===")
            print(f"note: {note}")
            try:
                result = await generate_s1_from_atom(tour_id, tour, pool)
                print(f"model_used={result['model_used']} retries={result['retries']} "
                      f"atoms_available={result['atoms_available']} atoms_used={len(result['atoms_used'])}")
                print(f"gate: citation_count={result['gate']['citation_count']} "
                      f"words_per_citation={result['gate']['words_per_citation']} "
                      f"density_pass={result['gate']['density_pass']} "
                      f"closed_world_pass={result['gate']['closed_world_pass']} "
                      f"entailment_pass={result['gate']['entailment_pass']}")
                print(f"aa_summary (first 400 chars): {str(result['content'].get('aa_summary', ''))[:400]}")
                results.append({"tour_id": tour_id, "status": "passed", "model_used": result["model_used"],
                                 "retries": result["retries"], "gate": result["gate"]})
            except GroundingError as e:
                print(f"GroundingError: {e}")
                results.append({"tour_id": tour_id, "status": "gate_failed", "error": str(e)})
    finally:
        await db.close()

    print("\n" + "=" * 20 + " SUMMARY " + "=" * 20)
    print(json.dumps(results, default=str, indent=2))
    print("AA392_VERIFY_DONE_MARKER")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as e:  # noqa: BLE001
        print(f"AA392_VERIFY_DONE_MARKER status=FAILURE error={type(e).__name__}: {e}")
        raise
