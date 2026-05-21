"""
AA-46 — S4 Blog Engine: LangGraph StateGraph.

Flow:
  brief_node → draft_node → post_process_node → evaluate_node → validate_node → seo_node → save_node

Rewrite loops:
  post_process_node: violation + rewrite_count < 2 → draft_node
  evaluate_node:     score < 7.5 + rewrite_count < 2 → draft_node
  validate_node:     always → seo_node (validation failure routes to hitl_gate3_status=flagged_human)
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Optional, TypedDict

import asyncpg
import boto3
import structlog
from langgraph.graph import StateGraph, END

from api.services.acp_post_processor import apply_output_rules, OutputRuleViolation
from services.acp_s4_blog.validator import ValidatorAgent

logger = structlog.get_logger()

_BEDROCK = boto3.client("bedrock-runtime", region_name="us-west-1")
_LAMBDA = boto3.client("lambda", region_name="us-west-1")

DRAFT_MODEL = "us.anthropic.claude-sonnet-4-5-20251001-v1:0"
EVAL_FUNCTION = "aa-cis-dev-acp-s4-evaluate"
EVAL_THRESHOLD = 7.5
MAX_REWRITE = 2

BLOG_SYSTEM_PROMPT = """You are Adventure Asia's expert travel blog writer.
Adventure Asia is a premium bespoke travel brand for discerning senior professionals (40-60, US/UK/AU).

Voice: calm, assured, credible, specific, well-travelled, operator-led, quietly premium.
Must NOT feel like: AI filler, SEO sludge, checklist tourism copy, internal project notes.

Writing rules:
- 1500-3000 words, reader-facing prose only
- Prove one central thesis with route-level specificity and concrete proof points
- Opening: scene / contrast / surprising grounded claim — then explicit thesis
- Include an honest caveat naturally (humidity, harder day, transfer friction)
- FAQ answers must each have one specific qualifier (place, km, season, transport, fitness, trade-off)
- No scaffolding language: no "calendar brief", "operational note", "verify provider", "this section follows"
- No hype: no "breathtaking", "stunning", "iconic", "unforgettable", "trip of a lifetime"

Return ONLY valid JSON matching this schema exactly:
{
  "content_md": "<full markdown blog post>",
  "seo_title": "<50-70 chars>",
  "seo_meta": "<150-170 chars>",
  "slug": "<url-safe-slug>"
}"""


class S4BlogState(TypedDict):
    # Input / brief
    tenant_id: str
    run_id: str
    calendar_item_id: str
    primary_keyword: str
    outline: list
    target_keywords: list
    title: str
    # Draft output
    content_md: str
    seo_title: str
    seo_meta: str
    slug: str
    # Post-process output
    review_flags: list
    rules_applied: list
    # Evaluator output
    evaluator_score: Optional[float]
    evaluator_input_hash: Optional[str]
    # Validator output
    validation_passed: Optional[bool]
    validation_score: Optional[float]
    failing_checks: list
    repair_targets: list
    # SEO output
    seo_score: Optional[float]
    seo_issues: list
    # Pipeline tracking
    rewrite_count: int
    rewrite_feedback: str
    error: str
    status: str
    draft_id: Optional[str]
    # DB connection (injected at runtime, not serialized)
    db: Optional[object]
    db_rules: list


# ── Node 1: brief_node ────────────────────────────────────────────────────────

async def brief_node(state: S4BlogState) -> S4BlogState:
    """Validate and enrich brief — content_calendars not yet in DB, use inline data."""
    if not state.get("primary_keyword") or not state.get("title"):
        return {**state, "status": "error", "error": "primary_keyword and title are required"}
    logger.info("s4_brief_ready", keyword=state["primary_keyword"], title=state["title"])
    return {**state, "status": "drafting"}


# ── Node 2: draft_node ────────────────────────────────────────────────────────

async def draft_node(state: S4BlogState) -> S4BlogState:
    """Generate blog draft via Bedrock Sonnet."""
    outline_text = "\n".join(f"- {p}" for p in (state.get("outline") or []))
    kw_text = ", ".join(state.get("target_keywords") or [])
    feedback = state.get("rewrite_feedback", "")

    user_prompt = f"""Write a travel blog post with these specifications:

Title: {state['title']}
Primary keyword: {state['primary_keyword']}
Target keywords: {kw_text}
Outline:
{outline_text or "- Introduction\n- Main sections\n- FAQ\n- Conclusion"}

{f'PREVIOUS ATTEMPT FEEDBACK (fix these issues):{chr(10)}{feedback}' if feedback else ''}

Return ONLY the JSON object — no preamble, no explanation."""

    try:
        response = _BEDROCK.invoke_model(
            modelId=DRAFT_MODEL,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "system": BLOG_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            }),
            contentType="application/json",
            accept="application/json",
        )
        raw = json.loads(response["body"].read())
        content_text = raw["content"][0]["text"].strip()
        # Strip markdown fences
        if content_text.startswith("```"):
            parts = content_text.split("```")
            content_text = parts[1]
            if content_text.startswith("json"):
                content_text = content_text[4:]
            content_text = content_text.strip()
        draft = json.loads(content_text)
        logger.info("s4_draft_generated", slug=draft.get("slug", ""), chars=len(draft.get("content_md", "")))
        return {
            **state,
            "content_md": draft.get("content_md", ""),
            "seo_title": draft.get("seo_title", ""),
            "seo_meta": draft.get("seo_meta", ""),
            "slug": draft.get("slug", re.sub(r"[^a-z0-9-]", "-", state["title"].lower())),
            "status": "post_processing",
            "error": "",
        }
    except Exception as e:
        logger.error("s4_draft_failed", error=str(e))
        return {**state, "status": "error", "error": f"Draft generation failed: {e}"}


# ── Node 3: post_process_node ─────────────────────────────────────────────────

async def post_process_node(state: S4BlogState) -> S4BlogState:
    """Apply deterministic output rules from acp_output_rules."""
    if state.get("status") == "error":
        return state
    output = {
        "content_md": state.get("content_md", ""),
        "seo_title": state.get("seo_title", ""),
        "seo_meta": state.get("seo_meta", ""),
    }
    db = state.get("db")
    if db is None:
        logger.warning("s4_post_process_no_db")
        return {**state, "review_flags": [], "rules_applied": [], "status": "evaluating"}

    try:
        output = await apply_output_rules(
            output=output, stage=None, tenant_id=state["tenant_id"], db=db
        )
        return {
            **state,
            "content_md": output.get("content_md", state["content_md"]),
            "seo_title": output.get("seo_title", state["seo_title"]),
            "seo_meta": output.get("seo_meta", state["seo_meta"]),
            "review_flags": output.get("review_flags", []),
            "rules_applied": output.get("rules_applied", []),
            "status": "evaluating",
        }
    except OutputRuleViolation as e:
        count = state.get("rewrite_count", 0) + 1
        logger.warning("s4_rule_violation", rule_id=e.rule_id, rewrite_count=count)
        return {
            **state,
            "rewrite_count": count,
            "rewrite_feedback": f"Rule violation: {e}. Rephrase content to avoid this pattern.",
            "status": "rewriting" if count < MAX_REWRITE else "blocked",
            "error": str(e) if count >= MAX_REWRITE else "",
        }


# ── Node 4: evaluate_node ─────────────────────────────────────────────────────

async def evaluate_node(state: S4BlogState) -> S4BlogState:
    """Call isolated acp-s4-evaluate Lambda (text-only)."""
    if state.get("status") in ("error", "blocked"):
        return state

    content_text = state.get("content_md", "")
    try:
        resp = _LAMBDA.invoke(
            FunctionName=EVAL_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps({"text": content_text}),
        )
        body = json.loads(resp["Payload"].read())
        if body.get("statusCode") != 200:
            raise RuntimeError(f"Evaluator error: {body.get('body')}")
        result = json.loads(body["body"])
        score = float(result.get("evaluator_score", 0))
        hash_val = result.get("evaluator_input_hash", "")
        logger.info("s4_evaluated", score=score, hash=hash_val[:12])

        if score < EVAL_THRESHOLD:
            count = state.get("rewrite_count", 0) + 1
            issues = "; ".join(result.get("issues", [])[:3])
            return {
                **state,
                "evaluator_score": score,
                "evaluator_input_hash": hash_val,
                "rewrite_count": count,
                "rewrite_feedback": f"Evaluator score {score:.1f} < {EVAL_THRESHOLD}. Issues: {issues}",
                "status": "rewriting" if count < MAX_REWRITE else "validating",
            }
        return {
            **state,
            "evaluator_score": score,
            "evaluator_input_hash": hash_val,
            "status": "validating",
        }
    except Exception as e:
        logger.error("s4_evaluate_failed", error=str(e))
        return {**state, "evaluator_score": None, "evaluator_input_hash": None, "status": "validating"}


# ── Node 5: validate_node ─────────────────────────────────────────────────────

async def validate_node(state: S4BlogState) -> S4BlogState:
    """Run ValidatorAgent 30+ checks. Failure → HITL (no auto-rewrite)."""
    if state.get("status") == "blocked":
        return state

    db_rules = state.get("db_rules") or []
    validator = ValidatorAgent(db_rules=db_rules)
    blog = {
        "content_md": state.get("content_md", ""),
        "title": state.get("title", ""),
        "seo_title": state.get("seo_title", ""),
        "seo_meta": state.get("seo_meta", ""),
        "draft_id": state.get("draft_id"),
    }
    brief = {
        "primary_keyword": state.get("primary_keyword", ""),
        "outline": state.get("outline") or [],
        "destination": _extract_destination(state.get("primary_keyword", "")),
    }
    try:
        result = await validator.validate(blog=blog, brief=brief)
        failing = [c.check_name for c in result.checks if not c.passed]
        repair = result.repair_targets
        logger.info("s4_validated", passed=result.overall_passed, score=result.overall_score,
                    failing=len(failing))
        return {
            **state,
            "validation_passed": result.overall_passed,
            "validation_score": round(result.overall_score * 10, 2),
            "failing_checks": failing,
            "repair_targets": repair,
            "status": "seo_scoring",
        }
    except Exception as e:
        logger.error("s4_validate_failed", error=str(e))
        return {**state, "validation_passed": False, "validation_score": 0.0,
                "failing_checks": [str(e)], "repair_targets": [], "status": "seo_scoring"}


# ── Node 6: seo_node ──────────────────────────────────────────────────────────

async def seo_node(state: S4BlogState) -> S4BlogState:
    """Deterministic SEO checks — no external API calls."""
    issues: list[str] = []
    score = 10.0
    text = state.get("content_md", "").lower()
    seo_title = state.get("seo_title", "")
    seo_meta = state.get("seo_meta", "")
    kw = state.get("primary_keyword", "").lower()

    # Keyword presence
    if kw and kw not in text:
        issues.append(f"Primary keyword '{kw}' not found in body")
        score -= 2.0
    if kw and kw not in seo_title.lower():
        issues.append(f"Primary keyword '{kw}' not in seo_title")
        score -= 1.5

    # Title length
    title_len = len(seo_title)
    if title_len < 50:
        issues.append(f"seo_title too short: {title_len} chars (need 50-70)")
        score -= 1.0
    elif title_len > 70:
        issues.append(f"seo_title too long: {title_len} chars (need 50-70)")
        score -= 1.0

    # Meta length
    meta_len = len(seo_meta)
    if meta_len < 150:
        issues.append(f"seo_meta too short: {meta_len} chars (need 150-170)")
        score -= 1.0
    elif meta_len > 170:
        issues.append(f"seo_meta too long: {meta_len} chars (need 150-170)")
        score -= 0.5

    # Keyword density (rough)
    words = re.findall(r"\b\w+\b", text)
    kw_words = re.findall(r"\b\w+\b", kw) if kw else []
    if kw_words and words:
        density = sum(text.count(w) for w in kw_words) / max(len(words), 1) * 100
        if density < 0.5:
            issues.append(f"Keyword density low: {density:.1f}% (aim for 0.5-2%)")
            score -= 1.0

    seo_score = max(0.0, min(10.0, score))
    logger.info("s4_seo_scored", score=seo_score, issues=len(issues))
    return {**state, "seo_score": round(seo_score, 2), "seo_issues": issues, "status": "saving"}


# ── Node 7: save_node ─────────────────────────────────────────────────────────

async def save_node(state: S4BlogState) -> S4BlogState:
    """INSERT into acp_silver_s4.blog_drafts."""
    db = state.get("db")
    if db is None:
        return {**state, "status": "error", "error": "No DB connection for save_node"}

    validation_passed = state.get("validation_passed")
    hitl_status = "pending" if validation_passed else "flagged_human"
    if state.get("status") == "blocked":
        hitl_status = "flagged_human"

    try:
        row = await db.fetchrow(
            """INSERT INTO acp_silver_s4.blog_drafts
               (run_id, tenant_id, calendar_item_id, title, slug, content_md,
                word_count, seo_title, seo_meta, target_keywords, status,
                evaluator_score, evaluator_input_hash, review_flags, rules_applied,
                validation_passed, validation_score, failing_checks, repair_targets,
                seo_score, seo_issues, hitl_gate3_status, rewrite_count, pipeline_version)
             VALUES ($1::uuid, $2, $3::uuid, $4, $5, $6,
                     $7, $8, $9, $10::jsonb, 'draft',
                     $11, $12, $13::jsonb, $14::jsonb,
                     $15, $16, $17::jsonb, $18::jsonb,
                     $19, $20::jsonb, $21, $22, 'v1')
             RETURNING draft_id::text""",
            state["run_id"],
            state["tenant_id"],
            state.get("calendar_item_id") or str(uuid.uuid4()),
            state.get("title", ""),
            state.get("slug", ""),
            state.get("content_md", ""),
            len(state.get("content_md", "").split()),
            state.get("seo_title", ""),
            state.get("seo_meta", ""),
            json.dumps(state.get("target_keywords") or []),
            state.get("evaluator_score"),
            state.get("evaluator_input_hash"),
            json.dumps(state.get("review_flags") or []),
            json.dumps(state.get("rules_applied") or []),
            state.get("validation_passed"),
            state.get("validation_score"),
            json.dumps(state.get("failing_checks") or []),
            json.dumps(state.get("repair_targets") or []),
            state.get("seo_score"),
            json.dumps(state.get("seo_issues") or []),
            hitl_status,
            state.get("rewrite_count", 0),
        )
        draft_id = row["draft_id"]
        logger.info("s4_draft_saved", draft_id=draft_id, hitl_status=hitl_status)
        return {**state, "draft_id": draft_id, "status": "done"}
    except Exception as e:
        logger.error("s4_save_failed", error=str(e))
        return {**state, "status": "error", "error": f"Save failed: {e}"}


# ── Conditional edges ─────────────────────────────────────────────────────────

def _route_post_process(state: S4BlogState) -> str:
    if state.get("status") == "rewriting":
        return "draft_node"
    if state.get("status") in ("blocked", "error"):
        return "save_node"
    return "evaluate_node"


def _route_evaluate(state: S4BlogState) -> str:
    if state.get("status") == "rewriting":
        return "draft_node"
    return "validate_node"


def _extract_destination(keyword: str) -> str:
    kw = keyword.lower()
    if "korea" in kw or "korean" in kw:
        return "south korea"
    if "nepal" in kw or "himalaya" in kw:
        return "nepal"
    if "japan" in kw or "japanese" in kw:
        return "japan"
    return kw.split()[0] if kw.split() else ""


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_s4_graph() -> StateGraph:
    builder = StateGraph(S4BlogState)

    builder.add_node("brief_node", brief_node)
    builder.add_node("draft_node", draft_node)
    builder.add_node("post_process_node", post_process_node)
    builder.add_node("evaluate_node", evaluate_node)
    builder.add_node("validate_node", validate_node)
    builder.add_node("seo_node", seo_node)
    builder.add_node("save_node", save_node)

    builder.set_entry_point("brief_node")
    builder.add_edge("brief_node", "draft_node")
    builder.add_edge("draft_node", "post_process_node")
    builder.add_conditional_edges(
        "post_process_node",
        _route_post_process,
        {"draft_node": "draft_node", "evaluate_node": "evaluate_node", "save_node": "save_node"},
    )
    builder.add_conditional_edges(
        "evaluate_node",
        _route_evaluate,
        {"draft_node": "draft_node", "validate_node": "validate_node"},
    )
    builder.add_edge("validate_node", "seo_node")
    builder.add_edge("seo_node", "save_node")
    builder.add_edge("save_node", END)

    return builder.compile()
