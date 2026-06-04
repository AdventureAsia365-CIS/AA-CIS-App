"""ContentBrief dataclass for S4.2 Social Media Content Engine (AA-93)."""
from dataclasses import dataclass, field

VALID_CHANNELS = [
    "facebook", "linkedin", "tiktok", "instagram",
    "email", "newsletter", "landing_page", "ads",
]

ALLOWED_TOUR_FIELDS = frozenset({
    'aa_name', 'aa_subtitle', 'aa_summary',
    'aa_highlights', 'aa_itineraries', 'duration',
    'activities', 'links'
})


def extract_tour_fields(tour: dict) -> dict:
    """Whitelist-filter a published_tours row before building ContentBrief.

    Only ALLOWED_TOUR_FIELDS pass through — unknown/sensitive fields are silently dropped.
    Args:
        tour: raw dict from published_tours DB row
    Returns:
        filtered dict containing only allowed keys that exist in tour
    """
    return {k: v for k, v in tour.items() if k in ALLOWED_TOUR_FIELDS}


@dataclass
class ContentBrief:
    brand: str
    audience: str
    channel: str
    goal: str
    topic: str
    tone: str
    cta: str
    must_include: list[str] = field(default_factory=list)
    must_avoid: list[str] = field(default_factory=list)
    destination: str = ""
    tour_name: str = ""

    def validate_anchors(self) -> list[str]:
        """Return list of missing/invalid anchor fields."""
        missing: list[str] = []
        if not self.brand.strip():
            missing.append("brand")
        if not self.audience.strip():
            missing.append("audience")
        if not self.channel or self.channel not in VALID_CHANNELS:
            missing.append("channel")
        if not self.goal.strip():
            missing.append("goal")
        if not self.topic.strip():
            missing.append("topic")
        if not self.tone.strip():
            missing.append("tone")
        if not self.cta.strip():
            missing.append("cta")
        return missing

    def to_dict(self) -> dict:
        return {
            "brand": self.brand,
            "audience": self.audience,
            "channel": self.channel,
            "goal": self.goal,
            "topic": self.topic,
            "tone": self.tone,
            "cta": self.cta,
            "must_include": self.must_include,
            "must_avoid": self.must_avoid,
            "destination": self.destination,
            "tour_name": self.tour_name,
        }
