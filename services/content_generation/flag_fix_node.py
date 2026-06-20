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
from .seo_meta_utils import best_meta_candidate, meta_in_band, SEO_META_MIN, SEO_META_MAX

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
    "ITINERARY_MEAL_TIME_INVENTED": "itineraries",
    "ITINERARY_DAY_TITLE_GENERIC":  "itineraries",
    "SEO_TITLE_WEAK":               "seo_title",
    "SEO_TITLE_WRONG_ACTIVITY":     "seo_title",
    "META_INCOMPLETE_SENTENCE":     "seo_meta",
    "META_TOO_SHORT":               "seo_meta",
    "SEO_META_TOO_LONG":            "seo_meta",   # AA-204: over-length now routes to repair
    "META_OPENER_ROBOTIC":          "seo_meta",
    "META_PACKAGE_WORD":            "seo_meta",
    "META_DFS_VERBATIM":            "seo_meta",
    "DFS_INTENT_UNDERUSED":         "seo_meta",
    "NAME_ALL_CAPS":                "name",
    "NAME_SUPERLATIVE":             "name",
}

# AA-204: deterministic SEO length/sentence codes raised by validate_node. These must drive a
# repair pass independently of the (non-deterministic) brand_audit "flagged" status.
_DETERMINISTIC_SEO_CODES = {"SEO_META_TOO_LONG", "META_TOO_SHORT", "META_INCOMPLETE_SENTENCE"}


def _should_fix(state: dict) -> bool:
    """AA-204: run the fix pass when the brand audit flagged OR when a deterministic SEO
    length/sentence code fired in validate. A fully-clean pass (neither) still skips."""
    if state.get("brand_audit_status", "pass") == "flagged":
        return True
    return any(c in _DETERMINISTIC_SEO_CODES for c in state.get("failure_codes", []))


def _build_fix_keys(state: dict) -> set:
    """Collect generated-dict keys to repair: brand-audit codes/fields (AA-134) plus AA-204
    deterministic SEO codes carried from validate's failure_codes."""
    fix_keys: set[str] = set()
    for code in state.get("brand_audit_codes", []):
        mapped = STAGE2_FIX_MAPPING.get(code)
        if mapped:
            fix_keys.add(mapped)
    for f in state.get("brand_audit_fields", []):
        key = f.lower().replace("aa_", "")
        if key in STAGE2_FIX_MAPPING.values():
            fix_keys.add(key)
    for code in state.get("failure_codes", []):
        if code in _DETERMINISTIC_SEO_CODES:
            mapped = STAGE2_FIX_MAPPING.get(code)
            if mapped:
                fix_keys.add(mapped)
    return fix_keys

FIX_SYSTEM = """You are Adventure Asia's editorial fixer.
Fix ONLY the specified fields. Keep all other fields exactly as-is.
Preserve all product facts. Return strict JSON only."""


def _rerepair_meta(post: str, tour: dict, content: dict, model_tier: str) -> str:
    """AA-205 C-full: one bounded re-repair for seo_meta still out of band. Single LLM call,
    no loop. Returns in-band candidate if produced, else the incoming post (graceful)."""
    from .seo_meta_utils import meta_in_band as _in_band, SEO_META_MIN as _MIN, SEO_META_MAX as _MAX
    cur = (post or "").strip()
    try:
        prompt = (
            "Rewrite this SEO meta description to be " + str(_MIN) + "-" + str(_MAX)
            + " characters and a COMPLETE sentence ending in a period.\n\n"
            + "Current (" + str(len(cur)) + " chars): " + json.dumps(cur) + "\n"
            + "Tour: " + str(content.get("name")) + " - " + str(tour.get("country", "")) + "\n\n"
            + "Rules:\n- MUST be " + str(_MIN) + "-" + str(_MAX) + " characters "
            + "(current is " + ("too short" if len(cur) < _MIN else "out of band") + ").\n"
            + "- MUST end with a period and read as one complete sentence "
            + "(no trailing preposition/conjunction).\n"
            + "- Do NOT pad with filler — add a real intent clue or practical reassurance.\n"
            + "- Return JSON: {\"seo_meta\": \"...\"}"
        )
        resp = LLMClient().generate(LLMRequest(
            system_prompt=FIX_SYSTEM, user_prompt=prompt, model_tier=model_tier,
        ))
        raw = resp.content.strip()
        fence = chr(96) * 3
        if raw[:3] == fence:
            raw = raw.split(fence)[1]
            if raw[:4] == "json":
                raw = raw[4:]
            raw = raw.strip()
        candidate = (json.loads(raw).get("seo_meta") or "").strip()
        logger.info("meta_rerepair_done", before_len=len(cur), after_len=len(candidate))
        return candidate if _in_band(candidate) else post
    except Exception as e:
        logger.warning("meta_rerepair_failed_graceful", error=str(e))
        return post


def flag_fix_node(state: dict) -> dict:
    """AA-134: Fix only the flagged fields identified by brand_audit_node."""
    # AA-204: run if brand-flagged OR a deterministic SEO length/sentence code fired.
    # Pass-through a fully-clean pass ("pass"/"manual_check" with no det SEO codes) unchanged.
    if not _should_fix(state):
        return {
            **state,
            "fix_pass_applied": False,
            "fix_pass_fields":  [],
        }

    try:
        fix_keys = _build_fix_keys(state)

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

        # AA-201/AA-204: seo_meta repair-to-band rules (port of v5 repair_seo_fields)
        meta_rules = ""
        if "seo_meta" in fix_keys:
            _cur_meta = current_content.get("seo_meta") or ""
            meta_rules = f"""

SEO_META RULES:
- SEO_META MUST be 140-155 characters and a COMPLETE sentence (ends with a period, \
not ending on a preposition/conjunction, contains a clear verb).
- Include the DFS primary topic + one intent clue + one practical reassurance when available.
- Do NOT pad with filler to reach length; rewrite naturally to land in band.
- NEVER return meta under 140 chars.
- If the current SEO_META exceeds 155 chars, SHORTEN it to land within 140-155 as a COMPLETE \
sentence ending in a period — do NOT truncate mid-phrase.
Current SEO_META ({len(_cur_meta)} chars): {json.dumps(_cur_meta)}"""

        user_prompt = f"""Fix these fields for Adventure Asia brand standards.

FIELDS TO FIX:
{fields_display}

AUDIT ISSUES FOUND:
{issues_text}

TOUR CONTEXT:
Name: {current_content.get("name")}
Trip type: {current_content.get("trip_type") or tour.get("trip_type")}
Duration: {tour.get("duration")}{meta_rules}

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

        # AA-205: deterministic post-repair band guard for seo_meta (no pad, no escalate).
        # LLM repair can overshoot under SEO_META_MIN (e.g. 132). AA-215 revalidate re-runs
        # validate and fires META_TOO_SHORT but that is only -0.5 sub-score, so the under-band
        # meta still clears the 7.0 gate and reaches gold. Enforce the band here at the source.
        if "seo_meta" in fix_keys:
            _pre_meta = current_content.get("seo_meta", "") or ""
            _guarded = best_meta_candidate(new_generated.get("seo_meta", "") or "", _pre_meta)
            if not meta_in_band(_guarded):
                _guarded = _rerepair_meta(
                    _guarded, tour, new_generated, state.get("model_tier", "haiku"),
                )
            new_generated["seo_meta"] = _guarded

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
        batch = state.get("tour", {}).get("batch_name", "")
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

    def freq_key(les):
        return (
            f"{les.get('failure_code', '')}:{les.get('field', '')}:"
            f"{les.get('pattern', '')[:50].lower().strip()}"
        )
    freq = Counter(freq_key(les) for les in lessons)

    eligible = [les for les in lessons if freq[freq_key(les)] >= min_frequency]
    if not eligible:
        return 0

    seen: set = set()
    unique_lessons = []
    for les in eligible:
        k = freq_key(les)
        if k not in seen:
            seen.add(k)
            unique_lessons.append(les)

    conn = await asyncpg.connect(get_database_url())
    inserted = 0
    try:
        for lesson in unique_lessons:
            stage = "audit"
            field = lesson.get("field", "")
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
                f"Failure code: {lesson.get('failure_code', '')} — severity: {lesson.get('severity', '')}",
                f"Fix field {field} — failure code {lesson.get('failure_code', '')}",
                lesson.get("example_before", ""),
            )
            inserted += 1
    finally:
        await conn.close()
    return inserted
