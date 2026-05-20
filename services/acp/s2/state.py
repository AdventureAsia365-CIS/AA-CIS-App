from __future__ import annotations
from typing import Optional
from typing_extensions import TypedDict


class S2AgentState(TypedDict):
    run_id: str
    country: str
    tenant_id: str
    keywords_s3_key: Optional[str]
    competitors_s3_key: Optional[str]
    trends_s3_key: Optional[str]
    reddit_s3_key: Optional[str]
    gsc_s3_key: Optional[str]
    keyword_count: int
    informational_intent_pct: Optional[float]
    confidence_score: Optional[float]
    iteration: int
    completed_tools: list[str]
    error: Optional[str]
    existing_content_risk: bool
