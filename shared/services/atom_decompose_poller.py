"""
AA-305 — poll real Bedrock Batch job outcome for acp_contract.atom_decompose_jobs
rows submitted via the >=100 path, and write the real status/error_message/
counts back. The submit path (api/routers/v1_atoms.py) only ever wrote
status='submitted' and never updated it — atomjob_cf3d9066e0 was Failed on
Bedrock but read 'submitted' in the DB forever, until this fix (AA-305 STEP 0).

Trigger mechanism NOT decided yet (AA-305) — this module is deliberately
trigger-agnostic: poll_job() takes an already-open asyncpg connection plus a
"bedrock" control-plane client and handles exactly one job. Whatever the
eventual trigger turns out to be (scheduled Lambda, on-demand admin endpoint,
...) wraps this; nothing here assumes either.

Progress-counter source — GetModelInvocationJob response, NOT manifest.json.out:
Per AWS docs "Monitor batch inference jobs"
(https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference-view.html,
fetched 2026-07-20) and the GetModelInvocationJob API reference
(https://docs.aws.amazon.com/bedrock/latest/APIReference/API_GetModelInvocationJob.html,
fetched 2026-07-20), the SAME GetModelInvocationJob call already made for
status also returns totalRecordCount/processedRecordCount/successRecordCount/
errorRecordCount directly — the docs explicitly note these are the same
numbers found in manifest.json.out ("Alternatively, you can find these
numbers in the manifest.json.out file"). Reading them off the response we
already have avoids a second S3 round trip and no new IAM permission is
needed (control-plane read access already covers this call) for data the API
already hands back.

STILL UNVERIFIED against a real >=100 job that actually ran and produced
nonzero counts. The field-presence mechanism WAS exercised live (AA-305,
2026-07-20) against atomjob_cf3d9066e0 (the only real Batch job that exists
— failed PRE-FLIGHT validation, "contains less records (1) than the
required minimum of: 100", before ever entering processing) and that first
pass revealed a real bug: successRecordCount/errorRecordCount were PRESENT
in the response (0/0) and the original code trusted key-presence alone,
writing a confident-looking succeeded_count=0/failed_count=0 for a job that
never processed a single record. Per the same "Monitor batch inference
jobs" doc: "The counters return 0 when you submit a job but processing has
not yet started" — presence doesn't mean measured. Fixed by gating on
processedRecordCount > 0 instead (see the code below) — re-verified live
against the same job, now correctly writes NULL/NULL.

This also surfaced an earlier, separate discrepancy: a plain `aws bedrock
get-model-invocation-job` CLI call from a local terminal during AA-305 STEP
0 (different botocore/CLI version, different caller identity —
pqnghiep-admin direct, not the AA-296 satellite AssumeRole chain) showed
these four fields entirely absent from the printed JSON, while boto3 inside
the actual ECS container shows them present at 0. Root cause of that
CLI-vs-boto3 discrepancy is still not established — most likely a
botocore/CLI version difference (this repo pins boto3==1.34.69). Doesn't
change the fix above (which no longer depends on presence alone), but worth
knowing if that discrepancy resurfaces elsewhere.

Net effect: the "don't trust a placeholder zero" mechanism is now verified
end-to-end for real, for a job that failed before processing. The opposite
case — processedRecordCount > 0, gate passes, real success/error numbers
get written — has NOT been observed, because no >=100 job has ever
processed a single record. Still worth confirming against the first real
>=100 job (see AA-305 PR description). The try/except below stays
regardless: a missing/unexpected shape must never block writing
status/error_message, and succeeded_count/failed_count are left NULL rather
than guessed whenever real processing can't be confirmed.
"""
from __future__ import annotations

from typing import Optional

import structlog
from botocore.exceptions import ClientError

logger = structlog.get_logger()

# Bedrock ModelInvocationJobStatus enum (verified against the API reference,
# see module docstring) mapped to this table's status CHECK constraint
# ('submitted','in_progress','completed','failed' — migration 081). Anything
# not in this map (Submitted/InProgress/Scheduled/Validating/Stopping) is
# non-terminal — poll_job() writes nothing and just reports it back.
_TERMINAL_STATUS_MAP = {
    "Completed": "completed",
    "PartiallyCompleted": "completed",
    "Failed": "failed",
    "Stopped": "failed",
    "Expired": "failed",
}


async def list_pollable_job_ids(conn) -> list[str]:
    """job_ids with a real Bedrock job (job_arn set) still in a non-terminal
    DB status. Trigger-agnostic starting point for whatever eventually loops
    over pending jobs (Lambda, admin endpoint, ...)."""
    rows = await conn.fetch(
        "SELECT job_id FROM acp_contract.atom_decompose_jobs "
        "WHERE job_arn IS NOT NULL AND status IN ('submitted', 'in_progress')"
    )
    return [r["job_id"] for r in rows]


async def poll_job(conn, bedrock_client, job_id: str) -> dict:
    """Poll one atom_decompose_jobs row by job_id and write back its real
    outcome if Bedrock reports a terminal status. Never raises for expected
    failure modes (job_id not found, no job_arn stored, GetModelInvocationJob
    error) — returns {'ok': False, 'reason': ...} instead so a caller looping
    over many jobs doesn't need per-job try/except of its own.
    """
    row = await conn.fetchrow(
        "SELECT job_arn FROM acp_contract.atom_decompose_jobs WHERE job_id = $1",
        job_id,
    )
    if row is None:
        return {"ok": False, "job_id": job_id, "reason": "job_id not found in atom_decompose_jobs"}
    if row["job_arn"] is None:
        return {"ok": False, "job_id": job_id,
                 "reason": "no job_arn stored (inline <100 path job, or a pre-AA-305 row)"}

    try:
        resp = bedrock_client.get_model_invocation_job(jobIdentifier=row["job_arn"])
    except ClientError as e:
        logger.error("atom_decompose_poll_get_job_failed", job_id=job_id, job_arn=row["job_arn"], error=str(e))
        return {"ok": False, "job_id": job_id, "reason": f"GetModelInvocationJob failed: {e}"}

    bedrock_status = resp.get("status", "Unknown")
    new_status = _TERMINAL_STATUS_MAP.get(bedrock_status)

    if new_status is None:
        return {"ok": True, "job_id": job_id, "bedrock_status": bedrock_status, "updated": False}

    error_message = resp.get("message")
    if new_status == "failed" and not error_message:
        error_message = f"Bedrock job ended with status={bedrock_status!r} (no message field returned)"

    # Isolated on purpose (see module docstring) — a missing/unexpected shape
    # here must never block writing status/error_message above.
    #
    # Gated on processedRecordCount > 0, NOT on successRecordCount/
    # errorRecordCount presence alone (AA-305 follow-up, 2026-07-20 — found
    # live against atomjob_cf3d9066e0). Per the same "Monitor batch inference
    # jobs" doc cited above: "The counters return 0 when you submit a job but
    # processing has not yet started." A job that fails PRE-FLIGHT (like
    # atomjob_cf3d9066e0 — "contains less records (1) than the required
    # minimum of: 100" — rejected before ever reaching InProgress) still has
    # successRecordCount/errorRecordCount present in the response, reading 0
    # — but that 0 is the pre-processing placeholder value, not a measured
    # result. Checking key-presence alone (the original version of this code)
    # wrote a confident-looking 0/0 for a job that never processed anything,
    # which is exactly the "looks certain but isn't" problem these columns
    # exist to prevent. processedRecordCount == 0 necessarily means
    # successRecordCount == errorRecordCount == 0 too (success+error <=
    # processed), so gating on it costs nothing for jobs that genuinely did
    # process records — it only withholds the numbers when nothing was ever
    # measured.
    succeeded_count: Optional[int] = None
    failed_count: Optional[int] = None
    try:
        processed = resp.get("processedRecordCount")
        if processed is not None and int(processed) > 0 and \
                "successRecordCount" in resp and "errorRecordCount" in resp:
            succeeded_count = int(resp["successRecordCount"])
            failed_count = int(resp["errorRecordCount"])
        else:
            logger.warning(
                "atom_decompose_poll_counts_unavailable", job_id=job_id, bedrock_status=bedrock_status,
                processed_record_count=processed,
                reason="processedRecordCount is 0/absent — counters are a pre-processing placeholder "
                       "per AWS docs, not a measured result, even if successRecordCount/errorRecordCount "
                       "are themselves present",
            )
    except (TypeError, ValueError) as e:
        logger.warning("atom_decompose_poll_counts_parse_failed", job_id=job_id, error=str(e))
        succeeded_count = None
        failed_count = None

    await conn.execute(
        """
        UPDATE acp_contract.atom_decompose_jobs
        SET status = $2, error_message = $3, succeeded_count = $4, failed_count = $5, completed_at = now()
        WHERE job_id = $1
        """,
        job_id, new_status, error_message, succeeded_count, failed_count,
    )

    logger.info(
        "atom_decompose_poll_updated", job_id=job_id, bedrock_status=bedrock_status,
        new_status=new_status, succeeded_count=succeeded_count, failed_count=failed_count,
    )
    return {
        "ok": True, "job_id": job_id, "bedrock_status": bedrock_status, "updated": True,
        "status": new_status, "succeeded_count": succeeded_count, "failed_count": failed_count,
    }
