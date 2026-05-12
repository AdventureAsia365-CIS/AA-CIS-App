import json
import structlog
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END

from shared.llm_client.client import LLMClient
from shared.llm_client.models import LLMRequest
from .prompts import SYSTEM_PROMPT, build_rewrite_prompt

logger = structlog.get_logger()

MAX_RETRIES = 3
MIN_QUALITY = 7.0

class ContentState(TypedDict):
    tour:                   dict
    seo:                    dict
    few_shots:              list
    generated:              dict
    quality_score:          float
    retry_count:            int
    feedback:               str
    error:                  str
    cost_usd:               float
    model_used:             str
    brand_system_prompt:    str
    brand_style_guide:      str
    brand_forbidden_words:  list
    rewrite_language:       str
    model_tier:             str
    is_tenant_rewrite:      bool

def generate_node(state: ContentState) -> ContentState:
    """Node 1: Generate content via LLMClient."""
    import asyncio

    client = LLMClient()
    prompt = build_rewrite_prompt(
        state["tour"],
        state["seo"],
        state.get("few_shots", []),
    )

    # Inject feedback nếu đang retry
    if state.get("feedback"):
        prompt += f"\n\nPREVIOUS ATTEMPT FEEDBACK:\n{state['feedback']}\nPlease fix these issues."

    # P3-S3: Build system prompt = AA core + tenant append
    brand_sp   = state.get("brand_system_prompt", "") or ""
    style_guide = state.get("brand_style_guide", "") or ""
    language   = state.get("rewrite_language", "en-US") or "en-US"

    system = SYSTEM_PROMPT
    if language == "en-GB":
        system += (
            "\n\nLANGUAGE: Use British English spelling and conventions "
            "(e.g. 'colour', 'travelling', 'organised')."
        )
    else:
        system += "\n\nLANGUAGE: Use American English spelling and conventions."
    if brand_sp:
        system += f"\n\nCLIENT BRAND CONTEXT (append only — do not override AA rules):\n{brand_sp}"
    if style_guide:
        prompt += f"\n\nSTYLE GUIDE FOR THIS CLIENT:\n{style_guide}"

    request = LLMRequest(
        system_prompt=system,
        user_prompt=prompt,
        model_tier=state.get("model_tier", "haiku"),
    )

    try:
        resp = asyncio.get_event_loop().run_until_complete(client.generate(request))
        # Strip markdown fences nếu LLM wrap JSON trong ```json ... ```
        raw = resp.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        generated = json.loads(raw)
        logger.info("content_generated", retry=state.get("retry_count", 0),
                    model=resp.model_used, cost=resp.cost_usd)
        return {
            **state,
            "generated":  generated,
            "cost_usd":   state.get("cost_usd", 0) + resp.cost_usd,
            "model_used": resp.model_used,
            "error":      "",
        }
    except json.JSONDecodeError as e:
        logger.warning("json_parse_failed", error=str(e))
        return {**state, "generated": {}, "error": f"JSON parse error: {e}"}
    except Exception as e:
        logger.error("generation_failed", error=str(e))
        return {**state, "generated": {}, "error": str(e)}

def validate_node(state: ContentState) -> ContentState:
    """Node 2: Quality check — score 0-10."""
    generated = state.get("generated", {})
    tour      = state.get("tour", {})
    issues    = []
    score     = 10.0

    # Required fields
    for field in ["name", "subtitle", "summary", "highlights", "itineraries",
                  "seo_title", "seo_meta"]:
        if not generated.get(field):
            issues.append(f"Missing field: {field}")
            score -= 1.5

    # highlights must be list with 3+ items
    highlights = generated.get("highlights", [])
    if not isinstance(highlights, list):
        issues.append("highlights must be a list")
        score -= 1.0
    elif len(highlights) < 3:
        issues.append(f"highlights has only {len(highlights)} items, need 3+")
        score -= 0.5

    # Name must not be modified — skip for tenant rewrites (AA name is the source,
    # minor normalisation differences are acceptable and should not tank the score)
    if not state.get("is_tenant_rewrite"):
        src_name = (tour.get("name") or "").strip().lower()
        ai_name  = (generated.get("name") or "").strip().lower()
        if src_name and ai_name and src_name != ai_name:
            issues.append(f"Name modified: '{tour.get('name')}' → '{generated.get('name')}'")
            score -= 2.0

    # Subtitle must not be generic
    subtitle = generated.get("subtitle", "").lower()
    generic_subtitle_flags = [
        "kingdom of happiness", "land of thunder dragon",
        "last shangri-la", "pristine wilderness",
    ]
    for flag in generic_subtitle_flags:
        if flag in subtitle:
            issues.append(f"Generic subtitle phrase: '{flag}'")
            score -= 1.0

    # Forbidden words — AA core list + tenant custom list
    forbidden = [
        "curated", "pristine", "refined", "tailored", "bespoke",
        "stunning", "breathtaking", "magical", "paradise",
        "cheap", "deal", "book now", "instant booking", "discount",
    ]
    # P3-S3: Merge tenant forbidden_words (lowercase, deduplicated)
    tenant_forbidden = [w.lower().strip() for w in (state.get("brand_forbidden_words") or []) if w]
    all_forbidden = list(dict.fromkeys(forbidden + tenant_forbidden))  # preserve order, dedupe

    content_text = json.dumps(generated).lower()
    for word in all_forbidden:
        if word in content_text:
            issues.append(f"Forbidden word: '{word}'")
            score -= 0.5

    # Highlights specificity — must not be pure generic
    generic_highlight_patterns = [
        "panoramic views", "beautiful landscapes", "stunning scenery",
        "breathtaking views", "pristine nature", "gross national happiness",
    ]
    highlights_text = " ".join(highlights).lower()
    for pattern in generic_highlight_patterns:
        if pattern in highlights_text:
            issues.append(f"Generic highlight phrase: '{pattern}'")
            score -= 0.5

    # SEO field lengths
    if len(generated.get("seo_title", "")) > 70:
        issues.append("seo_title exceeds 70 chars")
        score -= 0.5
    if len(generated.get("seo_meta", "")) > 170:
        issues.append("seo_meta exceeds 170 chars")
        score -= 0.5

    # Summary generic opener check
    summary = generated.get("summary", "")
    generic_openers = [
        "journey into", "journey along", "embark on", "discover the magic",
        "experience the wonder", "this refined", "this carefully",
        "this curated", "designed for discerning",
    ]
    for opener in generic_openers:
        if summary.lower().startswith(opener):
            issues.append(f"Generic summary opener: '{opener}'")
            score -= 1.0
            break

    score = max(0.0, score)
    feedback = "; ".join(issues) if issues else ""

    logger.info("validation_done", score=score, issues=len(issues),
                retry=state.get("retry_count", 0))

    return {**state, "quality_score": score, "feedback": feedback}

def should_retry(state: ContentState) -> str:
    """Edge: decide retry / done / hitl."""
    retry_count = state.get("retry_count", 0)
    score       = state.get("quality_score", 0)

    if score >= MIN_QUALITY:
        return "done"
    if retry_count < MAX_RETRIES - 1:
        return "retry"
    return "hitl"

def increment_retry(state: ContentState) -> ContentState:
    return {**state, "retry_count": state.get("retry_count", 0) + 1}

def build_graph() -> StateGraph:
    graph = StateGraph(ContentState)

    graph.add_node("generate", generate_node)
    graph.add_node("validate", validate_node)
    graph.add_node("increment_retry", increment_retry)

    graph.set_entry_point("generate")
    graph.add_edge("generate", "validate")
    graph.add_conditional_edges("validate", should_retry, {
        "done":  END,
        "retry": "increment_retry",
        "hitl":  END,
    })
    graph.add_edge("increment_retry", "generate")

    return graph.compile()
