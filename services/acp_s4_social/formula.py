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
