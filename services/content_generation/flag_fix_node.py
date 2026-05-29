"""AA-134: Targeted flag-fix node — rewrites only brand-flagged fields.
AA-132: write_lessons_log — persists audit lessons to shared.pipeline_lessons.
"""

import asyncio
import json
import structlog
import asyncpg

from shared.secrets import get_database_url

from shared.llm_client.client import LLMClient
from shared.llm_client.models import LLMRequest

logger = structlog.get_logger()

# Failure code → generated dict key (keys match generate_node output, no "aa_" prefix)
STAGE2_FIX_MAPPING = {
    "SUBTITLE_TRIP_TYPE_MISMATCH":  "subtitle",
    "SUBTITLE_CITY_LIST":           "subtitle",
    "SUBTITLE_WAYPOINT_FORMAT":     "subtitle",
    "SUMMARY_OFF_BRAND":            "summary",
    "SUMMARY_HONEYMOON_LANGUAGE":   "summary",
    "SUMMARY_SELF_REFERENTIAL":     "summary",
    "GENERIC_AI_WORDING":           "summary",
    "HIGHLIGHTS_TOO_GENERIC":       "highlights",
    "HIGHLIGHTS_ORDERING_WRONG":    "highlights",
    "HIGHLIGHTS_OPTIONAL_LANGUAGE": "highlights",
    "ITINERARY_STRUCTURE_WEAK":     "itineraries",
    "SEO_TITLE_WEAK":               "seo_title",
    "SEO_TITLE_WRONG_ACTIVITY":     "seo_title",
    "META_INCOMPLETE_SENTENCE":     "seo_meta",
    "META_OPENER_ROBOTIC":          "seo_meta",
    "META_PACKAGE_WORD":            "seo_meta",
    "META_DFS_VERBATIM":            "seo_meta",
    "DFS_INTENT_UNDERUSED":         "seo_meta",
    "NAME_ALL_CAPS":                "name",
    "NAME_SUPERLATIVE":             "name",
}

FIX_SYSTEM = """You are Adventure Asia's editorial fixer.
Fix ONLY the specified fields. Keep all other fields exactly as-is.
Preserve all product facts. Return strict JSON only."""


def flag_fix_node(state: dict) -> dict:
    """AA-134: Fix only the flagged fields identified by brand_audit_node."""
    status = state.get("brand_audit_status", "pass")

    # Only fix "flagged" — pass through "pass" and "manual_check" unchanged
    if status != "flagged":
        return {
            **state,
            "fix_pass_applied": False,
            "fix_pass_fields":  [],
        }

    try:
        fix_keys: set[str] = set()
        for code in state.get("brand_audit_codes", []):
            mapped = STAGE2_FIX_MAPPING.get(code)
            if mapped:
                fix_keys.add(mapped)
        for f in state.get("brand_audit_fields", []):
            key = f.lower().replace("aa_", "")
            if key in STAGE2_FIX_MAPPING.values():
                fix_keys.add(key)

        if not fix_keys:
            return {
                **state,
                "fix_pass_applied": False,
                "fix_pass_fields":  [],
            }

        current_content = state.get("generated", {})
        issues_text = "\n".join(state.get("brand_audit_issues", []))
        fields_display = "\n".join(
            f"- {k}: {json.dumps(current_content.get(k))}"
            for k in fix_keys if k in current_content
        )
        tour = state.get("tour", {})

        user_prompt = f"""Fix these fields for Adventure Asia brand standards.

FIELDS TO FIX:
{fields_display}

AUDIT ISSUES FOUND:
{issues_text}

TOUR CONTEXT:
Name: {current_content.get("name")}
Trip type: {current_content.get("trip_type") or tour.get("trip_type")}
Duration: {tour.get("duration")}

Return JSON with ONLY these keys: {list(fix_keys)}
Keep all other fields unchanged."""

        llm_client = LLMClient()
        request = LLMRequest(
            system_prompt=FIX_SYSTEM,
            user_prompt=user_prompt,
            model_tier=state.get("model_tier", "haiku"),
        )
        resp = llm_client.generate(request)

        raw = resp.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        fixed_fields = json.loads(raw)

        new_generated = dict(current_content)
        for k, v in fixed_fields.items():
            if k in fix_keys:
                new_generated[k] = v

        logger.info("flag_fix_done", fixed_keys=list(fix_keys), cost=resp.cost_usd)

        # AA-132: write lessons back to shared.pipeline_lessons
        lessons = state.get("lessons_extracted", [])
        if lessons:
            _write_lessons_safe(lessons, state)

        return {
            **state,
            "generated":       new_generated,
            "cost_usd":        state.get("cost_usd", 0) + resp.cost_usd,
            "fix_pass_applied": True,
            "fix_pass_fields":  list(fix_keys),
        }

    except Exception as e:
        logger.warning("flag_fix_failed_graceful", error=str(e))
        return {
            **state,
            "fix_pass_applied": False,
            "fix_pass_fields":  [],
        }


def _write_lessons_safe(lessons: list, state: dict) -> None:
    """Fire-and-forget lessons write-back — swallows all errors."""
    try:
        batch   = state.get("tour", {}).get("batch_name", "")
        country = state.get("tour", {}).get("country", "")
        loop = asyncio.get_event_loop()
        new_count = loop.run_until_complete(
            write_lessons_log(lessons, batch=batch, country=country)
        )
        logger.info("lessons_writeback", new_count=new_count)
    except Exception as e:
        logger.warning("lessons_writeback_failed", error=str(e))


# ── AA-132: lessons write-back ────────────────────────────────────────────────

async def write_lessons_log(
    lessons: list[dict],
    batch: str = "",
    country: str = "",
    min_frequency: int = 2,
) -> int:
    """
    Insert new lessons into shared.pipeline_lessons.
    Deduplicates by (stage, field, pattern). Only inserts patterns that appear
    >= min_frequency times within the provided lessons batch.
    Returns count inserted.
    """
    if not lessons:
        return 0

    from collections import Counter

    def freq_key(lesson): (
        f"{l.get('failure_code','')}:{l.get('field','')}:{l.get('pattern','')[:50].lower().strip()}"
    )
    freq = Counter(freq_key(lesson) for lesson in lessons)

    eligible = [lesson for lesson in lessons if freq[freq_key(lesson)] >= min_frequency]
    if not eligible:
        return 0

    seen: set = set()
    unique_lessons = []
    for lesson in eligible:
        k = freq_key(l)
        if k not in seen:
            seen.add(k)
            unique_lessons.append(l)

    conn = await asyncpg.connect(get_database_url())
    inserted = 0
    try:
        for lesson in unique_lessons:
            stage   = "audit"
            field   = lesson.get("field", "")
            pattern = lesson.get("pattern", "")
            existing = await conn.fetchval(
                "SELECT id FROM shared.pipeline_lessons WHERE stage=$1 AND field=$2 AND pattern=$3 LIMIT 1",
                stage, field, pattern,
            )
            if existing:
                continue
            await conn.execute(
                """INSERT INTO shared.pipeline_lessons
                   (batch, country, stage, field, pattern, why_it_matters,
                    what_to_do, example_before, is_active)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,true)""",
                batch,
                country,
                stage,
                field,
                pattern,
                f"Failure code: {lesson.get('failure_code','')} — severity: {lesson.get('severity','')}",
                f"Fix field {field} — failure code {lesson.get('failure_code','')}",
                lesson.get("example_before", ""),
            )
            inserted += 1
    finally:
        await conn.close()
    return inserted
