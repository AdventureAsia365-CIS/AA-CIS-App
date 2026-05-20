from pydantic import BaseModel
from typing import Optional


class VoiceExamples(BaseModel):
    tone_traits: list[str]
    good_example: Optional[str]
    preferred: list[str]
    should_not_write: list[str]


class ParsedBrief(BaseModel):
    brand_name: str
    brand_type: Optional[str]
    core_idea: Optional[str]
    target_markets: list[str]
    customer_segment: Optional[str]
    customer_mindset: Optional[str]
    voice_examples: VoiceExamples
    style_guide: Optional[str]
    forbidden_words: list[str]
    confidence: float


class BrandRulesRow(BaseModel):
    tenant_id: str
    brand_type: Optional[str]
    core_idea: Optional[str]
    target_markets: list[str]
    customer_segment: Optional[str]
    customer_mindset: Optional[str]
    voice_examples: dict
    style_guide: Optional[str]
    forbidden_words: list[str]
    system_prompt: str
    source_docx_s3_key: str
    updated_at: str
