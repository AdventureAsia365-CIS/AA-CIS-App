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
    competitor_count: int
    informational_intent_pct: Optional[float]
    confidence_score: Optional[float]
    # Tracking fields for confidence scorer (AA-105)
    dataforseo_cache_hit: bool
    apify_cache_hit: bool
    gsc_data_present: bool
    # Circuit breaker tracking (AA-113)
    expand_attempts: int
    gate1_override: Optional[str]   # 'manual_required' blocks Gate 1 auto-approve
    data_quality: Optional[str]     # 'low' when circuit breaker fires
    iteration: int
    completed_tools: list[str]
    error: Optional[str]
    existing_content_risk: bool
