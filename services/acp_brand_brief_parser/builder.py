from .models import BrandRulesRow, ParsedBrief
from datetime import datetime, timezone


def build_system_prompt(parsed: ParsedBrief) -> str:
    traits = ", ".join(parsed.voice_examples.tone_traits[:5])
    markets = ", ".join(parsed.target_markets[:3])
    forbidden = "; ".join(parsed.forbidden_words[:10])
    style = parsed.style_guide[:300] if parsed.style_guide else ""
    return (
        f"You are writing travel content for {parsed.brand_name}. "
        f"Brand type: {parsed.brand_type}. "
        f"Core idea: {parsed.core_idea}. "
        f"Target markets: {markets}. "
        f"Customer: {parsed.customer_segment}. "
        f"Tone: {traits}. "
        f"Style: {style}. "
        f"Never use: {forbidden}."
    )


def build_rules_row(parsed: ParsedBrief, tenant_id: str, s3_key: str) -> BrandRulesRow:
    return BrandRulesRow(
        tenant_id=tenant_id,
        brand_type=parsed.brand_type,
        core_idea=parsed.core_idea,
        target_markets=parsed.target_markets,
        customer_segment=parsed.customer_segment,
        customer_mindset=parsed.customer_mindset,
        voice_examples=parsed.voice_examples.model_dump(),
        style_guide=parsed.style_guide,
        forbidden_words=parsed.forbidden_words,
        system_prompt=build_system_prompt(parsed),
        source_docx_s3_key=s3_key,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
