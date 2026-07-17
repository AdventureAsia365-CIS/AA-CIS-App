"""
/v1/atoms — AA-302 Atom decomposition (ACP v2, Bedrock Batch).

POST /v1/atoms/decompose
     → submit a Bedrock Batch (CreateModelInvocationJob) run that extracts
       content atoms for tours pending decompose (or an explicit tour_ids
       list). Only SUBMITS the job — parsing the completed output back into
       acp_contract.tour_atoms is a separate, later piece of work.

Requires BEDROCK_BATCH_ROLE_ARN (account 1 role, accounts/acc1-bedrock
Terraform — applied 2026-07-17). NOTE: production boto3 (requirements.txt,
1.34.69) does not yet have create_model_invocation_job — this endpoint's
Bedrock call will fail with an SDK-level error (unknown operation) until
the production SDK is upgraded. Verified working in isolation via a
separate venv (boto3 1.43.49), not yet through this service.
"""
import json
import os
import uuid

import boto3
import structlog
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds
from pydantic import BaseModel
from typing import Optional

from api.routers.auth import verify_jwt as _verify_jwt
from shared.llm_client.bedrock_satellite import BedrockUnavailable, get_satellite_client

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/atoms", tags=["atoms"])

AWS_REGION = os.environ.get("AWS_REGION", "us-west-1")
BRONZE_BUCKET = os.environ.get("BRONZE_BUCKET", "aa-cis-bronze-005097885195")

# Bucket is owned by account 2 (005097885195) even though this job submits
# via account 1 (867490540162) satellite AssumeRole — Bedrock defaults
# s3BucketOwner to the CALLER's account if omitted, which is wrong here and
# is why the S108b test job (rlp2kr2537zm) failed GetObject validation.
BRONZE_BUCKET_OWNER_ACCOUNT_ID = os.environ.get("BRONZE_BUCKET_OWNER_ACCOUNT_ID", "005097885195")

# Terraform accounts/acc1-bedrock (feat/aa-302-bedrock-batch-iam-acc1) đã
# apply — role thật, account 1.
BEDROCK_BATCH_ROLE_ARN = os.environ.get(
    "BEDROCK_BATCH_ROLE_ARN", "arn:aws:iam::867490540162:role/aa-bedrock-batch-inference-role"
)

# Cùng inference profile satellite AA-296 đã xác nhận hoạt động
# (shared/llm_client/bedrock_satellite.py) — dùng Sonnet cho tác vụ extract
# atom (cần đọc hiểu itinerary dài, không phải tác vụ rẻ/đơn giản).
BATCH_MODEL_ID = "arn:aws:bedrock:us-west-1:867490540162:inference-profile/global.anthropic.claude-sonnet-4-6"
ANTHROPIC_VERSION = "bedrock-2023-05-31"


def _get_tenant(
    request: Request,
    credentials: Optional[_Creds] = Depends(_HTTPBearer(auto_error=False)),
):
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    x_admin = request.headers.get("X-Admin-Secret", "")
    if admin_secret and x_admin == admin_secret:
        return {"sub": "00000000-0000-0000-0000-000000000001", "role": "admin"}
    if credentials:
        try:
            return _verify_jwt(credentials.credentials)
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="Not authenticated")


# ── Models ────────────────────────────────────────────────────────────────────

class DecomposeRequest(BaseModel):
    tour_ids: Optional[list[str]] = None


# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You extract content atoms from a tour's source material for a travel \
marketing platform. An atom is one concrete, verbatim-derived moment from the trip — not a \
summary, not a paraphrase, not an invented detail.

Extract concrete, verbatim-derived moments only. If input is thin or empty, return an empty \
list — never invent content not present in the source text.

Respond with ONLY a JSON object matching this exact contract:
{
  "atoms": [
    {
      "text": "verbatim-derived moment, 1-2 sentences",
      "activity_type": "trek|bike|food|culture|stay|transit|other",
      "emotional_hook": "string or null",
      "visual_potential": 1,
      "persona_fit": ["string", "..."],
      "season_note": "string or null"
    }
  ]
}

visual_potential is an integer 1-3 (3 = strong photo/video potential). No prose outside the \
JSON object."""


def _build_user_prompt(row: dict) -> str:
    parts = [f"TOUR: {row['name']}"]
    if row.get("aa_summary"):
        parts.append(f"SUMMARY: {row['aa_summary']}")
    if row.get("aa_highlights"):
        highlights = row["aa_highlights"]
        if isinstance(highlights, str):
            highlights = json.loads(highlights)
        if highlights:
            parts.append("HIGHLIGHTS:\n- " + "\n- ".join(str(h) for h in highlights))
    if row.get("itinerary_source"):
        parts.append(f"ITINERARY:\n{row['itinerary_source']}")
    if row.get("inclusions"):
        parts.append(f"INCLUSIONS:\n{row['inclusions']}")
    if row.get("exclusions"):
        parts.append(f"EXCLUSIONS:\n{row['exclusions']}")
    return "\n\n".join(parts)


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/decompose", status_code=202)
async def decompose(
    body: DecomposeRequest,
    request: Request,
    tenant=Depends(_get_tenant),
):
    """Submit a Bedrock Batch job to extract atoms for pending tours."""
    pool = request.app.state.pool

    async with pool.acquire() as conn:
        if body.tour_ids:
            rows = await conn.fetch("""
                SELECT id, name, aa_summary, aa_highlights, itinerary_source,
                       inclusions, exclusions
                FROM acp_contract.v_trip_registry
                WHERE id = ANY($1::uuid[])
            """, body.tour_ids)
        else:
            rows = await conn.fetch("""
                SELECT vtr.id, vtr.name, vtr.aa_summary, vtr.aa_highlights,
                       vtr.itinerary_source, vtr.inclusions, vtr.exclusions
                FROM acp_contract.v_trip_registry vtr
                LEFT JOIN acp_contract.tour_atoms ta
                    ON ta.tour_id = vtr.id AND NOT ta.deleted
                WHERE ta.tour_id IS NULL
            """)

    if not rows:
        return {"message": "no tours pending decompose", "tour_count": 0}

    job_id = f"atomjob_{uuid.uuid4().hex[:10]}"

    lines = []
    for r in rows:
        record = {
            "recordId": str(r["id"]),
            "modelInput": {
                "anthropic_version": ANTHROPIC_VERSION,
                "max_tokens": 4096,
                "system": _SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": _build_user_prompt(dict(r))}],
            },
        }
        lines.append(json.dumps(record))
    jsonl_body = "\n".join(lines) + "\n"

    input_key = f"batch-input/atom-decompose/{job_id}.jsonl"
    output_prefix = f"batch-output/atom-decompose/{job_id}/"
    input_s3_uri = f"s3://{BRONZE_BUCKET}/{input_key}"
    output_s3_uri = f"s3://{BRONZE_BUCKET}/{output_prefix}"

    s3 = boto3.client("s3", region_name=AWS_REGION)
    s3.put_object(
        Bucket=BRONZE_BUCKET,
        Key=input_key,
        Body=jsonl_body.encode("utf-8"),
        ContentType="application/jsonl",
    )

    tour_ids_json = json.dumps([str(r["id"]) for r in rows])

    if not BEDROCK_BATCH_ROLE_ARN:
        logger.warning("atom_decompose_role_not_configured", job_id=job_id)
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO acp_contract.atom_decompose_jobs
                    (job_id, tour_ids, status, input_s3_uri, output_s3_uri, error_message)
                VALUES ($1, $2::jsonb, 'failed', $3, $4, $5)
            """, job_id, tour_ids_json, input_s3_uri, output_s3_uri,
                "BEDROCK_BATCH_ROLE_ARN not configured — accounts/acc1-bedrock Terraform not applied yet")
        raise HTTPException(
            503,
            "BEDROCK_BATCH_ROLE_ARN chưa cấu hình — Terraform accounts/acc1-bedrock chưa được apply "
            "(xem AA-302). JSONL đã build và upload S3 thành công tại " + input_s3_uri + ".",
        )

    try:
        # ECS task role (acc2) không có quyền gọi CreateModelInvocationJob trên
        # acc1 trực tiếp — client "bedrock" (control-plane) phải qua cùng
        # AssumeRole satellite chain AA-296 dùng cho "bedrock-runtime", không
        # phải boto3.client("bedrock", ...) mặc định (chạy bằng identity acc2).
        bedrock = get_satellite_client("bedrock")
    except BedrockUnavailable as e:
        logger.error("atom_decompose_satellite_assume_role_failed", job_id=job_id, error=str(e))
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO acp_contract.atom_decompose_jobs
                    (job_id, tour_ids, status, input_s3_uri, output_s3_uri, error_message)
                VALUES ($1, $2::jsonb, 'failed', $3, $4, $5)
            """, job_id, tour_ids_json, input_s3_uri, output_s3_uri, f"AssumeRole to satellite failed: {e}")
        raise HTTPException(
            503,
            f"Không AssumeRole được vào satellite Bedrock (acc1): {e}. JSONL đã build và upload S3 "
            "thành công tại " + input_s3_uri + ".",
        )

    try:
        # Bedrock jobName regex forbids "_" ([a-zA-Z0-9]{1,63}(-*[a-zA-Z0-9\+\-\.]){0,63}) —
        # job_id itself stays untouched (DB key + log field), only the value
        # passed to Bedrock is sanitized.
        bedrock_job_name = job_id.replace("_", "-")
        bedrock.create_model_invocation_job(
            jobName=bedrock_job_name,
            roleArn=BEDROCK_BATCH_ROLE_ARN,
            modelId=BATCH_MODEL_ID,
            inputDataConfig={
                "s3InputDataConfig": {
                    "s3InputFormat": "JSONL",
                    "s3Uri": input_s3_uri,
                    "s3BucketOwner": BRONZE_BUCKET_OWNER_ACCOUNT_ID,
                },
            },
            outputDataConfig={
                "s3OutputDataConfig": {
                    "s3Uri": output_s3_uri,
                    "s3BucketOwner": BRONZE_BUCKET_OWNER_ACCOUNT_ID,
                },
            },
        )
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_message = e.response.get("Error", {}).get("Message", str(e))
        logger.error(
            "atom_decompose_batch_submit_failed",
            job_id=job_id, error_code=error_code, error_message=error_message,
        )
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO acp_contract.atom_decompose_jobs
                    (job_id, tour_ids, status, input_s3_uri, output_s3_uri, error_message)
                VALUES ($1, $2::jsonb, 'failed', $3, $4, $5)
            """, job_id, tour_ids_json, input_s3_uri, output_s3_uri, f"{error_code}: {error_message}")
        raise HTTPException(
            502,
            f"Bedrock Batch submit failed ({error_code}): {error_message}. Nếu error_code là "
            "AccessDeniedException/ValidationException liên quan tới roleArn, khả năng cao do "
            "accounts/acc1-bedrock Terraform chưa apply — không phải lỗi code.",
        )

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO acp_contract.atom_decompose_jobs
                (job_id, tour_ids, status, input_s3_uri, output_s3_uri)
            VALUES ($1, $2::jsonb, 'submitted', $3, $4)
        """, job_id, tour_ids_json, input_s3_uri, output_s3_uri)

    logger.info("atom_decompose_submitted", job_id=job_id, tour_count=len(rows))
    return {"job_id": job_id, "tour_count": len(rows), "status": "submitted"}
