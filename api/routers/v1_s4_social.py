"""
/v1/acp/s4/social — S4.2 Social Media Content Engine API (AA-93).

Routes:
  POST /v1/acp/s4/social/generate → auto mode: brief → 1 angle → write → save
  POST /v1/acp/s4/social/angles   → guided step 1: brief → 3 angles
  POST /v1/acp/s4/social/write    → guided step 2: brief + angle → write → save
  GET  /v1/acp/s4/social/{id}     → fetch social_content row
"""
import asyncio
import json
import os
from typing import Optional
from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds
from pydantic import BaseModel

from api.routers.auth import verify_jwt as _verify_jwt
from services.acp_s4_social.brief import ContentBrief, VALID_CHANNELS
from services.acp_s4_social.llm_client import make_llm_client
from services.acp_shared.cost_utils import calc_bedrock_cost, record_stage_cost

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/acp/s4/social", tags=["S4 Social Engine"])


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_admin(
    request: Request,
    credentials: Optional[_Creds] = Depends(_HTTPBearer(auto_error=False)),
):
    admin_secret = os.environ.get("ADMIN_SECRET", "")
    if admin_secret and request.headers.get("X-Admin-Secret") == admin_secret:
        return {"sub": "00000000-0000-0000-0000-000000000001", "role": "admin"}
    if credentials:
        try:
            return _verify_jwt(credentials.credentials)
        except Exception:
            pass
    raise HTTPException(status_code=401, detail="Not authenticated")


def _get_pool(request: Request) -> asyncpg.Pool:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="DB not ready")
    return pool


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, UUID):
            d[k] = str(v)
    return d


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class BriefIn(BaseModel):
    brand: str
    audience: str
    channel: str
    goal: str
    topic: str
    tone: str
    cta: str
    must_include: list[str] = []
    must_avoid: list[str] = []
    destination: str = ""
    tour_name: str = ""


class GenerateRequest(BaseModel):
    brief: BriefIn
    run_id: Optional[str] = None
    tenant_id: str = "aa_internal"
    tour_id: Optional[str] = None
    tour_name: Optional[str] = None
    llm_provider: str = "bedrock"
    model_id: Optional[str] = None


class AnglesRequest(BaseModel):
    brief: BriefIn
    llm_provider: str = "bedrock"
    model_id: Optional[str] = None


class WriteRequest(BaseModel):
    brief: BriefIn
    selected_angle: dict
    run_id: Optional[str] = None
    tenant_id: str = "aa_internal"
    tour_id: Optional[str] = None
    tour_name: Optional[str] = None
    llm_provider: str = "bedrock"
    model_id: Optional[str] = None


def _to_brief(b: BriefIn) -> ContentBrief:
    return ContentBrief(
        brand=b.brand, audience=b.audience, channel=b.channel,
        goal=b.goal, topic=b.topic, tone=b.tone, cta=b.cta,
        must_include=b.must_include, must_avoid=b.must_avoid,
        destination=b.destination, tour_name=b.tour_name,
    )


def _validate_brief(brief: ContentBrief):
    missing = brief.validate_anchors()
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required brief fields: {', '.join(missing)}. "
                   f"Valid channels: {', '.join(VALID_CHANNELS)}",
        )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_auto(
    request: Request,
    body: GenerateRequest,
    _auth=Depends(_get_admin),
):
    """Auto mode: select best angle automatically, write, save."""
    from services.acp_s4_social.handler import run_auto

    brief = _to_brief(body.brief)
    _validate_brief(brief)

    token_log: list = []
    llm_client = make_llm_client(body.llm_provider, body.model_id, token_log=token_log)
    meta = {
        "run_id": body.run_id,
        "tenant_id": body.tenant_id,
        "tour_id": body.tour_id,
        "tour_name": body.tour_name or body.brief.tour_name,
        "llm_provider": body.llm_provider,
        "model_id": body.model_id,
    }

    pool = _get_pool(request)
    try:
        async with pool.acquire() as db:
            result = await run_auto(brief, meta, db, llm_client)
        if body.run_id and token_log:
            in_tok = sum(t[0] for t in token_log)
            out_tok = sum(t[1] for t in token_log)
            cost = calc_bedrock_cost(in_tok, out_tok, "haiku")
            await asyncio.to_thread(record_stage_cost, body.run_id, "s4_social", cost, in_tok, out_tok)
        logger.info("s4_social_auto_done", social_id=result["social_id"], channel=body.brief.channel)
        return result
    except Exception as e:
        logger.error("s4_social_auto_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/angles")
async def get_angles(
    body: AnglesRequest,
    _auth=Depends(_get_admin),
    request: Request = None,
):
    """Guided step 1: generate 3 angles for human selection."""
    from services.acp_s4_social.handler import run_guided_angles

    brief = _to_brief(body.brief)
    _validate_brief(brief)

    llm_client = make_llm_client(body.llm_provider, body.model_id)
    try:
        angles = run_guided_angles(brief, llm_client)
        return {"angles": angles}
    except Exception as e:
        logger.error("s4_social_angles_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/write")
async def write_guided(
    request: Request,
    body: WriteRequest,
    _auth=Depends(_get_admin),
):
    """Guided step 2: write with human-selected angle, save."""
    from services.acp_s4_social.handler import run_guided_write

    brief = _to_brief(body.brief)
    _validate_brief(brief)

    if not body.selected_angle or not body.selected_angle.get("name"):
        raise HTTPException(status_code=422, detail="selected_angle.name is required")

    token_log: list = []
    llm_client = make_llm_client(body.llm_provider, body.model_id, token_log=token_log)
    meta = {
        "run_id": body.run_id,
        "tenant_id": body.tenant_id,
        "tour_id": body.tour_id,
        "tour_name": body.tour_name or body.brief.tour_name,
        "llm_provider": body.llm_provider,
        "model_id": body.model_id,
    }

    pool = _get_pool(request)
    try:
        async with pool.acquire() as db:
            result = await run_guided_write(brief, body.selected_angle, meta, db, llm_client)
        if body.run_id and token_log:
            in_tok = sum(t[0] for t in token_log)
            out_tok = sum(t[1] for t in token_log)
            cost = calc_bedrock_cost(in_tok, out_tok, "haiku")
            await asyncio.to_thread(record_stage_cost, body.run_id, "s4_social", cost, in_tok, out_tok)
        logger.info("s4_social_guided_done", social_id=result["social_id"])
        return result
    except Exception as e:
        logger.error("s4_social_guided_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{social_id}")
async def get_social(
    social_id: str,
    request: Request,
    _auth=Depends(_get_admin),
):
    try:
        UUID(social_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid social_id UUID")

    pool = _get_pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT social_id::text, run_id::text, tenant_id, tour_id::text, "
            "tour_name, tiktok, facebook_post, facebook_ad, strategy_notes, "
            "channel, content_brief, selected_angle, formula_used, mode, "
            "quality_warnings, llm_provider, model_id, validation_status, "
            "hitl_gate_3_social_status, created_at "
            "FROM acp_silver_s4.social_content WHERE social_id=$1::uuid",
            social_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Social content not found")
    return _row_to_dict(row)


# ── PATCH /{social_id}/hitl — Gate 3-social approve/reject ───────────────────

class SocialHitlRequest(BaseModel):
    status: str
    reviewer_id: str
    notes: Optional[str] = None


@router.patch("/{social_id}/hitl")
async def gate3_social_decision(
    social_id: str,
    body: SocialHitlRequest,
    request: Request,
    _auth=Depends(_get_admin),
):
    """Gate 3-social: approve or reject per-tour social content."""
    if body.status not in ("approved", "rejected"):
        raise HTTPException(status_code=422, detail="status must be 'approved' or 'rejected'")
    try:
        UUID(social_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid social_id UUID")

    pool = _get_pool(request)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE acp_silver_s4.social_content
            SET hitl_gate_3_social_status = $1,
                hitl_reviewer_id          = $2,
                hitl_decided_at           = NOW()
            WHERE social_id = $3::uuid
            RETURNING social_id::text, tenant_id, run_id::text,
                      hitl_gate_3_social_status, hitl_reviewer_id, hitl_decided_at
            """,
            body.status, body.reviewer_id, social_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Social content not found")

        await conn.execute(
            """
            INSERT INTO acp_shared.audit_log
                (tenant_id, actor, action, resource_type, resource_id, details)
            VALUES ($1, $2, $3, 'social_content', $4, $5::jsonb)
            """,
            str(row["tenant_id"]),
            body.reviewer_id,
            f"hitl.gate3_social.{body.status}",
            social_id,
            json.dumps({"notes": body.notes, "reviewer_id": body.reviewer_id}),
        )

    logger.info("gate3_social_decision social_id=%s status=%s reviewer=%s",
                social_id, body.status, body.reviewer_id)
    return _row_to_dict(row)
