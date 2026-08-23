"""
services.acp_angle_gate.goals — the 8-value Goal table (T8 workflow step 2).

Verbatim from Bang 1, docs/claude_tasks/AA-449-00-step0-t8-angle-gate-investigation.md — the
table Nghiep supplied directly (round 2), itself a merge of SKILL_v2.md's per-goal "logic" text
+ `writing formulars.xlsx`'s "Marketing term" column (STEP0 §1a already confirmed this, both
prior sources already found in AA-439-07, not re-derived here).

STEP0 flagged 2 wording discrepancies against SKILL_v2.md in Bang 1 (header said "7 loại" but
lists 8; Conversion's SLAP expands "Purchase" here vs. SKILL_v2.md's own "Proceed") — kept
EXACTLY as Bang 1 states, not silently "corrected" back to SKILL_v2.md, since the build task
re-supplied Bang 1 unchanged and did not ask for either correction. If Nghiep decides otherwise
later, only this file's `logic`/`marketing_term` strings need editing — nothing downstream reads
those specific words structurally (they only ever get interpolated into the LLM prompt).

`key` values are new (Bang 1 has no machine-readable slug column) — snake_case of `name`, chosen
here, not from any source document.
"""
from __future__ import annotations

from typing import TypedDict


class Goal(TypedDict):
    key: str
    name: str
    description: str
    logic: str
    marketing_term: str


GOALS: list[Goal] = [
    {
        "key": "promotion",
        "name": "Promotion",
        "description": "Quảng bá điểm đến/route/trip/ưu đãi/launch/campaign",
        "logic": "Attention-Interest-Desire-Action",
        "marketing_term": "AIDA",
    },
    {
        "key": "lead_generation",
        "name": "Lead Generation",
        "description": (
            "AIDA nếu offer tích cực; PAS nếu nỗi đau là lập kế hoạch quá tải, trip chung "
            "chung, route kém, đông đúc, bất định"
        ),
        "logic": "Problem-Agitate-Solve",
        "marketing_term": "AIDA hoặc PAS",
    },
    {
        "key": "conversion",
        "name": "Conversion",
        "description": "Đẩy người đọc tới enquiry/booking/waitlist/consultation/purchase",
        "logic": "Stop-Look-Act-Purchase",
        "marketing_term": "SLAP",
    },
    {
        "key": "introduction_awareness",
        "name": "Introduction / Awareness",
        "description": "Giới thiệu quốc gia/điểm đến/route style/xu hướng/quan điểm AA",
        "logic": "Hook-Insight-CTA",
        "marketing_term": "Hook-Insight-CTA hoặc 5W1H",
    },
    {
        "key": "trust_building",
        "name": "Trust-building",
        "description": "Xây niềm tin vào năng lực thiết kế route của AA",
        "logic": "Problem-Insight-Proof-Action (Proof phải cụ thể, KHÔNG bịa claim)",
        "marketing_term": "FAB",
    },
    {
        "key": "engagement_conversation",
        "name": "Engagement / Conversation",
        "description": "Mời comment/share/save/thảo luận",
        "logic": "Hook-Value-CTA (câu hỏi có căn cứ)",
        "marketing_term": "BAB",
    },
    {
        "key": "event_announcement",
        "name": "Event Announcement",
        "description": "Thông báo hội chợ/sự kiện/launch/Web Summit/gặp supplier/đối tác",
        "logic": "What-Why-Who-Where/When-Why AA có mặt-CTA",
        "marketing_term": "5W1H + AIDA",
    },
    {
        "key": "product_service_explanation",
        "name": "Product or Service Explanation",
        "description": (
            "Giải thích AA làm gì, dịch vụ trip, itinerary design, supplier curation, "
            "partner portal, năng lực AI/data"
        ),
        "logic": "Feature-Advantage-Benefit",
        "marketing_term": "FAB",
    },
]

GOALS_BY_KEY: dict[str, Goal] = {g["key"]: g for g in GOALS}


def get_goal(key: str) -> Goal | None:
    return GOALS_BY_KEY.get(key)


__all__ = ["Goal", "GOALS", "GOALS_BY_KEY", "get_goal"]
