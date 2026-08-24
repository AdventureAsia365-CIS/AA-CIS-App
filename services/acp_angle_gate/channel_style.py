"""
services.acp_angle_gate.channel_style — the 7-channel style table (T8 workflow step 4/5: "Best
final style" is tra'd from here, per the `channel` already known from the request's input).

Verbatim from Bang 2, docs/claude_tasks/AA-449-00-step0-t8-angle-gate-investigation.md — STEP0
§1b confirmed this is `Channel Output Structures.xlsx` (found earlier, AA-439-07 §A3), not
SKILL_v2.md's own much shorter "Channel Rules" prose section.

Keys match services.acp_planning.models.Channel's Literal exactly (snake_case for the two
multi-word channels: "landing_page"). "email" here maps to Bang 2's "Email / Newsletter" row.

"blog" has NO row in Bang 2 at all (STEP0 §5 flagged this gap explicitly) — kept as a Channel
value for backward compatibility (T7 already had it), but its entry below is a NEW, self-authored
fallback (not from Bang 2 or any other source document), consistent with the existing
FRAMEWORK_TABLE's own "hub"/long-form treatment of blog elsewhere in services/acp_planning. If
Ms. Thu supplies a real blog row for this table later, replace this entry, don't extend it.
"""
from __future__ import annotations

from typing import TypedDict


class ChannelStyle(TypedDict):
    channel: str
    display_name: str
    use_when: str
    structure: str
    style: str
    avoid: str


CHANNEL_STYLES: list[ChannelStyle] = [
    {
        "channel": "linkedin",
        "display_name": "LinkedIn",
        "use_when": "Thought leadership, founder voice, B2B/investor/partner, premium positioning",
        "structure": "Hook insight→đoạn ngắn→1 insight rõ→AA positioning→CTA nhẹ/reflective",
        "style": "professional, calm, insight-led, editorial, premium không kiêu",
        "avoid": (
            "emoji nhiều, travel copy chung chung, hard sell, liệt kê itinerary dài, "
            "storytelling quá cảm xúc, cliché (\"hidden gem\", \"bucket list\", \"paradise awaits\")"
        ),
    },
    {
        "channel": "facebook",
        "display_name": "Facebook",
        "use_when": "Engagement, giới thiệu điểm đến, community trust, soft promotion",
        "structure": (
            "Mở ấm-cụ-thể→cảm giác điểm đến+chi tiết cụ thể→ý tưởng trip thực tế→vì sao hợp "
            "audience AA→CTA thân thiện"
        ),
        "style": "human, warm, clear, travel-led, thoải mái hơn LinkedIn",
        "avoid": (
            "corporate tone, \"discover paradise\" chung chung, quá nhiều fact thiếu cảm xúc, "
            "wording rẻ tiền, ngôn ngữ cảnh quan mơ hồ"
        ),
    },
    {
        "channel": "instagram",
        "display_name": "Instagram",
        "use_when": "Visual inspiration, mood điểm đến, brand awareness, engagement ngắn",
        "structure": (
            "Hook giác quan ngắn→dòng dễ lướt→3-5 chi tiết cụ thể→AA positioning nhẹ→CTA đơn giản"
        ),
        "style": "visual, precise, sensory, minimal, elegant",
        "avoid": "đoạn dài, caption mơ hồ, nhồi hashtag, tính từ chung chung, ngôn ngữ quá kịch",
    },
    {
        "channel": "tiktok",
        "display_name": "TikTok",
        "use_when": "Attention ngắn, tò mò, giáo dục, reframe điểm đến",
        "structure": (
            "Câu mở sắc→setup nói chuyện đơn giản→3 điểm nhanh→tò mò không clickbait→direction "
            "hình ảnh (tuỳ chọn)"
        ),
        "style": "direct, clear, conversational, fast-moving, useful",
        "avoid": (
            "hook viral rẻ tiền, phóng đại nguy hiểm, urgency giả, luxury flexing, thuật ngữ "
            "travel phức tạp"
        ),
    },
    {
        "channel": "email",
        "display_name": "Email / Newsletter",
        "use_when": (
            "Nurture, trust-building, giải thích sản phẩm, thông báo trip, gợi ý theo mùa, "
            "đối tác"
        ),
        "structure": "Subject rõ→mở đầu bình tĩnh→1 ý chính→giải thích editorial hữu ích→1 CTA rõ",
        "style": "personal nhưng polished, calm, useful, trust-building, editorial",
        "avoid": "quá nhiều link, quá nhiều CTA, ngôn ngữ promo chung chung, block text dài, urgency giả",
    },
    {
        "channel": "landing_page",
        "display_name": "Landing Page / Sales Page",
        "use_when": "Conversion, giải thích sản phẩm, campaign landing, trang điểm đến/trip",
        "structure": (
            "Value prop rõ→đối tượng phù hợp→vì sao điểm đến/trải nghiệm này quan trọng→AA xử "
            "lý gì→trust signal/process→CTA rõ"
        ),
        "style": "precise, benefit-led, premium, grounded, dễ scan",
        "avoid": (
            "overwriting, luxury claim chung chung, superlative không có bằng chứng, itinerary "
            "detail rối, quá nhiều brand philosophy trước khi giải thích offer"
        ),
    },
    {
        "channel": "ads",
        "display_name": "Ads",
        "use_when": "Lead gen, retargeting, quảng bá điểm đến, test campaign",
        "structure": "1 hook rõ→1 benefit theo audience→1 điểm khác biệt AA→1 CTA",
        "style": "clear, specific, benefit-led, calm nhưng thuyết phục",
        "avoid": (
            "clickbait, slogan travel chung chung, quá nhiều ý trong 1 ad, urgency không có "
            "căn cứ, over-promise"
        ),
    },
    # NEW, self-authored fallback — NOT in Bang 2 (STEP0 §5). See module docstring.
    {
        "channel": "blog",
        "display_name": "Blog",
        "use_when": "Long-form SEO content, hub/pillar pages, in-depth destination guides",
        "structure": "Hook→context/why this destination→structured H2 sections→FAQ (if TOFU)→CTA",
        "style": "informative, structured, SEO-aware, still specific (not generic travel copy)",
        "avoid": "keyword stuffing, generic listicle tone, no cliché superlatives without proof",
    },
]

CHANNEL_STYLES_BY_KEY: dict[str, ChannelStyle] = {c["channel"]: c for c in CHANNEL_STYLES}


def get_channel_style(channel: str) -> ChannelStyle | None:
    return CHANNEL_STYLES_BY_KEY.get(channel)


__all__ = ["ChannelStyle", "CHANNEL_STYLES", "CHANNEL_STYLES_BY_KEY", "get_channel_style"]
