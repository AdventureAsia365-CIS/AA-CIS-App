"""Formula selector for S4.2 Social Media Content Engine (AA-93).

Sourced from Ms. Thư's content_agent.py SKILL.md + references/.
14 copywriting formulas mapped by channel × goal combination.
"""
from pathlib import Path

REFERENCES_DIR = Path(__file__).parent / "references"

# Primary formula map: (channel, goal) → formula_name
_FORMULA_MAP: dict[tuple[str, str], str] = {
    ("facebook", "awareness"): "aida",
    ("facebook", "conversion"): "pas",
    ("facebook", "engagement"): "hook-value-cta",
    ("facebook", "retargeting"): "bab",
    ("linkedin", "thought_leadership"): "storytelling",
    ("linkedin", "lead_gen"): "fab",
    ("linkedin", "awareness"): "acc",
    ("linkedin", "conversion"): "pppp",
    ("tiktok", "engagement"): "hook-value-cta",
    ("tiktok", "awareness"): "sss",
    ("tiktok", "viral"): "slap",
    ("instagram", "brand"): "sss",
    ("instagram", "awareness"): "aida",
    ("instagram", "conversion"): "fab",
    ("email", "nurture"): "bab",
    ("email", "conversion"): "pas",
    ("email", "onboarding"): "aida",
    ("newsletter", "education"): "acc",
    ("newsletter", "engagement"): "storytelling",
    ("landing_page", "conversion"): "pppp",
    ("landing_page", "lead_gen"): "aida",
    ("ads", "direct_response"): "slap",
    ("ads", "awareness"): "aida",
    ("ads", "retargeting"): "pas",
}

# All available formula names (matches files in references/)
ALL_FORMULAS = [
    "aida", "pas", "fab", "acc", "slap", "bab", "pppp", "sss",
    "storytelling", "hook-value-cta", "4cs", "coc", "funnel", "5w1h",
]


def get_formula_name(channel: str, goal: str) -> str:
    """Return formula name for a given channel+goal pair. Falls back to 'aida'."""
    key = (channel.lower(), goal.lower())
    return _FORMULA_MAP.get(key, "aida")


def load_formula_file(formula_name: str) -> str:
    """Load formula reference markdown from references/. Returns '' if not found."""
    path = REFERENCES_DIR / f"{formula_name}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def load_skill() -> str:
    """Load SKILL.md system instructions."""
    path = REFERENCES_DIR / "SKILL.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def load_context() -> str:
    """Load CONTEXT.md glossary."""
    path = REFERENCES_DIR / "CONTEXT.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


# v2: 9-goal system with formula mapping and selective references
GOALS: dict[str, dict] = {
    "1": {
        "name": "Promotion",
        "formulas": ["aida"],
        "references": ["aida.md"],
    },
    "2": {
        "name": "Lead generation",
        "formulas": ["aida", "pas"],
        "references": ["aida.md", "pas.md"],
    },
    "3": {
        "name": "Conversion",
        "formulas": ["aida", "slap"],
        "references": ["aida.md", "slap.md"],
    },
    "4": {
        "name": "Introduction / Awareness",
        "formulas": ["hook-value-cta", "5w1h"],
        "references": ["hook-value-cta.md", "5w1h.md"],
    },
    "5": {
        "name": "Trust-building",
        "formulas": ["fab", "5w1h"],
        "references": ["fab.md", "5w1h.md"],
    },
    "6": {
        "name": "Engagement / Conversation",
        "formulas": ["hook-value-cta", "bab"],
        "references": ["hook-value-cta.md", "bab.md"],
    },
    "7": {
        "name": "Event announcement",
        "formulas": ["5w1h", "aida"],
        "references": ["5w1h.md", "aida.md"],
    },
    "8": {
        "name": "Product or service explanation",
        "formulas": ["fab"],
        "references": ["fab.md"],
    },
    "9": {
        "name": "Partner / supplier communication",
        "formulas": ["fab", "5w1h"],
        "references": ["fab.md", "5w1h.md"],
    },
}

GOAL_NAME_TO_KEY: dict[str, str] = {
    "promotion": "1", "promo": "1",
    "lead generation": "2", "lead": "2",
    "conversion": "3", "convert": "3",
    "introduction": "4", "awareness": "4", "intro": "4",
    "trust-building": "5", "trust": "5",
    "engagement": "6", "conversation": "6",
    "event announcement": "7", "event": "7",
    "product or service explanation": "8", "product": "8", "service": "8",
    "partner / supplier communication": "9", "partner": "9", "supplier": "9",
}


def normalize_goal_key(value: str) -> str | None:
    """Return canonical goal key ("1"-"9") from a numeric key or name alias. None if unknown."""
    v = value.strip().lower()
    if v in GOALS:
        return v
    return GOAL_NAME_TO_KEY.get(v)


def get_goal_primary_formula(goal_key: str) -> str:
    """Return primary formula name for a goal key. Falls back to 'aida'."""
    return GOALS.get(goal_key, {}).get("formulas", ["aida"])[0]


def load_goal_references(goal_key: str) -> str:
    """Load and concatenate all reference files for a goal key."""
    refs = GOALS.get(goal_key, {}).get("references", ["aida.md"])
    texts = []
    for ref in refs:
        path = REFERENCES_DIR / ref
        if path.exists():
            texts.append(path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(texts)
