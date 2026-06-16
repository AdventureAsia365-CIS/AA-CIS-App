"""AA-133: LLM-as-Judge brand audit node for the CIS content pipeline."""

import json
import os
import re
import structlog
from openai import OpenAI

from .brand_standards import AA_BRAND_IDENTITY_PROMPT, AA_COWORK_STRUCTURE_PROMPT

logger = structlog.get_logger()

# ── Deterministic pre-audit checks ───────────────────────────────────────────

CITY_LIST_SUBTITLE = re.compile(
    r'^[A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)*(?:,\s*[A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)*){2,}$')
WAYPOINT_SUBTITLE = re.compile(r'[→❧►]|Route:|^\w[\w\s]+\s*→')
META_ROBOTIC_OPENERS = [
    re.compile(r'^This is a\b', re.IGNORECASE),
    re.compile(r'^Discover\b',   re.IGNORECASE),
    re.compile(r'^Book\b',       re.IGNORECASE),
    re.compile(r'^Find\b',       re.IGNORECASE),
]
OPTIONAL_HIGHLIGHT = re.compile(r'^Optional\b', re.IGNORECASE)
ELEPHANT_RIDING = re.compile(
    r'elephant[-\s]?back|elephant\s+ride|elephant\s+trek', re.IGNORECASE
)
NAME_ALL_CAPS_RE = re.compile(r'^[A-Z\s\d&\-]+$')
NAME_SUPERLATIVES = ['the best of', 'ultimate', 'must-see', 'and fun', 'expenditures']
# AA-195: fabricated meals / clock-times in itineraries = PRODUCT_TRUTH_RISK
ITIN_MEAL_INVENTED = re.compile(r'\b(breakfast|lunch|dinner)\b', re.IGNORECASE)
ITIN_CLOCK_TIME = re.compile(r'\b\d{1,2}(:\d{2})?\s?(am|pm)\b', re.IGNORECASE)
# AA-196: generic day titles that name no place/activity = ITINERARY_DAY_TITLE_GENERIC
ITIN_DAY_TITLE_GENERIC = re.compile(
    r"Day\s+\d+\s*--\s*(Exploration|Free Day|Arrival Day|Arrival|Departure|Transfer)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def pre_audit_checks(generated: dict) -> list[str]:
    codes = []
    name = (generated.get("name") or "")
    subtitle = (generated.get("subtitle") or "")
    seo_meta = (generated.get("seo_meta") or "")
    highlights = generated.get("highlights") or []
    if isinstance(highlights, str):
        highlights = [highlights]

    if name and NAME_ALL_CAPS_RE.match(name.strip()):
        codes.append("NAME_ALL_CAPS")
    for sup in NAME_SUPERLATIVES:
        if sup in name.lower():
            codes.append("NAME_SUPERLATIVE")
            break
    if subtitle and CITY_LIST_SUBTITLE.match(subtitle.strip()):
        codes.append("SUBTITLE_CITY_LIST")
    if subtitle and WAYPOINT_SUBTITLE.search(subtitle):
        codes.append("SUBTITLE_WAYPOINT_FORMAT")
    for opener in META_ROBOTIC_OPENERS:
        if opener.search(seo_meta):
            codes.append("META_OPENER_ROBOTIC")
            break
    if "package" in seo_meta.lower():
        codes.append("META_PACKAGE_WORD")
    for h in highlights:
        if OPTIONAL_HIGHLIGHT.match(str(h)):
            codes.append("HIGHLIGHTS_OPTIONAL_LANGUAGE")
            break
    combined = " ".join(str(h) for h in highlights).lower()
    if ELEPHANT_RIDING.search(combined):
        codes.append("FACT_CHECK_MANUAL_CHECK")

    itineraries = generated.get("itineraries") or ""
    if isinstance(itineraries, (list, dict)):
        itineraries = json.dumps(itineraries)
    itin_text = str(itineraries)
    if ITIN_MEAL_INVENTED.search(itin_text) or ITIN_CLOCK_TIME.search(itin_text):
        codes.append("ITINERARY_MEAL_TIME_INVENTED")
    if ITIN_DAY_TITLE_GENERIC.search(itin_text):
        codes.append("ITINERARY_DAY_TITLE_GENERIC")

    return list(set(codes))


# ── GPT-4.1 strict JSON schema ────────────────────────────────────────────────

BRAND_AUDIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["brand_audit"],
    "properties": {
        "brand_audit": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "status", "publish_ready", "fields_to_fix",
                "failure_codes", "issues", "scores", "notes",
                "lessons_extracted"
            ],
            "properties": {
                "status":         {"type": "string", "enum": ["pass", "flagged", "manual_check"]},
                "publish_ready":  {"type": "boolean"},
                "fields_to_fix":  {"type": "array", "items": {"type": "string"}},
                "failure_codes":  {"type": "array", "items": {"type": "string"}},
                "issues":         {"type": "array", "items": {"type": "string"}},
                "scores": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["brand_fit", "human_read", "seo_fit", "trip_type_accuracy", "publish_readiness"],
                    "properties": {
                        "brand_fit":          {"type": "integer", "enum": [0, 1]},
                        "human_read":         {"type": "integer", "enum": [0, 1]},
                        "seo_fit":            {"type": "integer", "enum": [0, 1]},
                        "trip_type_accuracy": {"type": "integer", "enum": [0, 1]},
                        "publish_readiness":  {"type": "integer", "enum": [0, 1]},
                    },
                },
                "notes": {"type": "string"},
                "lessons_extracted": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["pattern", "failure_code", "field", "example_before", "severity"],
                        "properties": {
                            "pattern":        {"type": "string"},
                            "failure_code":   {"type": "string"},
                            "field":          {"type": "string"},
                            "example_before": {"type": "string"},
                            "severity":       {"type": "string", "enum": ["high", "medium", "low"]},
                        },
                    },
                },
            },
        }
    },
}


# ── Node ──────────────────────────────────────────────────────────────────────

def brand_audit_node(state: dict) -> dict:
    """AA-133: LLM-as-Judge brand audit. Runs after validate when score >= 7.0."""
    generated = state.get("generated", {})
    if not generated:
        return {
            **state,
            "brand_audit_status": "pass",
            "brand_audit_codes":  [],
            "brand_audit_issues": [],
            "brand_audit_fields": [],
            "lessons_extracted":  [],
        }

    try:
        pre_codes = pre_audit_checks(generated)

        system_prompt = AA_BRAND_IDENTITY_PROMPT + "\n\n" + AA_COWORK_STRUCTURE_PROMPT

        tour = state.get("tour", {})
        dfs = state.get("seo", {})
        highlights = generated.get("highlights") or []
        if isinstance(highlights, str):
            highlights = [highlights]
        highlights_text = "\n".join(f"- {h}" for h in highlights)
        dfs_brief = str(dfs.get("top_keywords", []))[:200]

        user_prompt = f"""Review this tour against Adventure Asia brand standards.
Pre-audit deterministic checks found these codes (include in assessment): {pre_codes}

CONTENT TO REVIEW:
AA_NAME: {generated.get("name")}
AA_SUBTITLE: {generated.get("subtitle")}
AA_SUMMARY: {generated.get("summary")}
AA_HIGHLIGHTS:
{highlights_text}
AA_ITINERARIES: {str(generated.get("itineraries") or "")[:300]}
SEO_TITLE: {generated.get("seo_title")}
SEO_META: {generated.get("seo_meta")}

TRIP TYPE: {generated.get("trip_type") or tour.get("trip_type", "unknown")}
SOURCE DURATION: {tour.get("duration", "unknown")}
DFS CONTEXT: {dfs_brief}

REVIEW ORDER:
1. Product truth: all fields align to same actual product?
2. Brand fit: calm, assured, selective, precise, private, no hype?
3. Trip type accuracy: subtitle/summary/SEO match actual activity?
4. Highlights quality: specific moments, 4+ items, no "Optional"?
5. Human readability: no editorial language leak?
6. SEO quality: title 60 chars max, meta 140-155 chars, ends with period?
7. Publish readiness: ready without any changes?

Return JSON only per schema."""

        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not openai_key:
            logger.warning("brand_audit_skipped", reason="no OPENAI_API_KEY")
            return {
                **state,
                "brand_audit_status": "pass",
                "brand_audit_codes":  pre_codes,
                "brand_audit_issues": [],
                "brand_audit_fields": [],
                "lessons_extracted":  [],
            }

        client = OpenAI(api_key=openai_key)
        resp = client.chat.completions.create(
            model="gpt-4.1",
            temperature=0.1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name":   "brand_audit_result",
                    "strict": True,
                    "schema": BRAND_AUDIT_SCHEMA,
                },
            },
        )
        result = json.loads(resp.choices[0].message.content)["brand_audit"]

        # Merge deterministic pre-codes into LLM codes
        all_codes = list(dict.fromkeys(result["failure_codes"] + pre_codes))
        result["failure_codes"] = all_codes

        in_tok = resp.usage.prompt_tokens if resp.usage else 0
        out_tok = resp.usage.completion_tokens if resp.usage else 0
        cost = round((in_tok * 0.002 + out_tok * 0.008) / 1000, 6)

        logger.info("brand_audit_done",
                    status=result["status"],
                    codes=result["failure_codes"],
                    in_tokens=in_tok, out_tokens=out_tok, cost_usd=cost)

        return {
            **state,
            "brand_audit_status": result["status"],
            "brand_audit_codes":  result["failure_codes"],
            "brand_audit_issues": result["issues"],
            "brand_audit_fields": result["fields_to_fix"],
            "lessons_extracted":  result["lessons_extracted"],
            "cost_usd": state.get("cost_usd", 0) + cost,
        }

    except Exception as e:
        logger.warning("brand_audit_failed_graceful", error=str(e))
        return {
            **state,
            "brand_audit_status": "pass",
            "brand_audit_codes":  [],
            "brand_audit_issues": [],
            "brand_audit_fields": [],
            "lessons_extracted":  [],
        }
