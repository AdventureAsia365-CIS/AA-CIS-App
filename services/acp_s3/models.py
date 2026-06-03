from typing import Optional
from pydantic import BaseModel


class Post(BaseModel):
    title_topic: str
    primary_keyword: str
    secondary_keywords: list[str]
    search_intent: str
    word_count: int
    format: str
    brief_outline: list[str]
    lead_magnet_cta: str


class Week(BaseModel):
    week: int
    posts: list[Post]


class CalendarSkeleton(BaseModel):
    document_title: str
    weeks: list[Week]


class AdGroup(BaseModel):
    name: str
    keywords: list[str]
    headlines: list[str]
    descriptions: list[str]


class Campaign(BaseModel):
    campaign_name: str
    objective: str
    ad_groups: list[AdGroup]


class AdsOutput(BaseModel):
    campaigns: list[Campaign]


class SystemPromotion(BaseModel):
    content: str
    confidence: float = 0.0


class LessonUpdateOutput(BaseModel):
    job_lessons: list[str]
    root_lessons_append: list[str]
    system_promotions: list[SystemPromotion] = []


class CompactPacket(BaseModel):
    top_keywords: list[dict]
    funnel_mix: dict
    cadence_weeks: int
    posts_per_week: int
    country: str
    lesson_summary: str


class ValidationResult(BaseModel):
    passed: bool
    errors: list[str]


class S3RunResult(BaseModel):
    run_id: str
    status: str
    calendar_id: Optional[str] = None
    ads_plan_id: Optional[str] = None
    validation_errors: list[str] = []
    input_tokens: int = 0
    output_tokens: int = 0
