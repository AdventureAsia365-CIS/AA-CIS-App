"""AA-83: SocialContent model — mirrors acp_silver_s4.social_content."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class SocialContent(BaseModel):
    social_id: Optional[str] = None
    run_id: str
    tenant_id: str
    tour_id: str
    tour_name: Optional[str] = None
    tiktok: Optional[dict] = None
    facebook_post: Optional[dict] = None
    facebook_ad: Optional[dict] = None
    strategy_notes: Optional[dict] = None
    validation_status: Optional[str] = None
    validation_issues: Optional[list[str]] = None
    rewrite_attempt: Optional[int] = 0
    hitl_gate_3_social_status: Optional[str] = None
    hitl_reviewer_id: Optional[str] = None
    hitl_decided_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class SocialContentCreate(BaseModel):
    run_id: str
    tenant_id: str
    tour_id: str
    tour_name: Optional[str] = None
    tiktok: Optional[dict] = None
    facebook_post: Optional[dict] = None
    facebook_ad: Optional[dict] = None
    strategy_notes: Optional[dict] = None


class SocialContentResponse(BaseModel):
    social_id: str
    run_id: str
    tenant_id: str
    tour_id: str
    tour_name: Optional[str] = None
    tiktok: Optional[dict] = None
    facebook_post: Optional[dict] = None
    facebook_ad: Optional[dict] = None
    strategy_notes: Optional[dict] = None
    validation_status: Optional[str] = None
    validation_issues: Optional[list[str]] = None
    rewrite_attempt: Optional[int] = None
    hitl_gate_3_social_status: Optional[str] = None
    hitl_reviewer_id: Optional[str] = None
    hitl_decided_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
