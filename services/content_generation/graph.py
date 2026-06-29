import json
import re
import structlog
from json_repair import repair_json
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END

from shared.llm_client.client import LLMClient
from shared.llm_client.models import LLMRequest
from .prompts import SYSTEM_PROMPT, build_rewrite_prompt
from .brand_audit_node import brand_audit_node
from .flag_fix_node import flag_fix_node
from .judge_node import judge_node
from .seo_meta_utils import SEO_META_MIN, SEO_META_MAX, meta_complete_sentence, SEO_META_FORBIDDEN

logger = structlog.get_logger()

MAX_RETRIES = 3
MIN_QUALITY = 7.0
# AA-216: structural failure (empty/missing field) caps quality below the gate regardless of
# other sub-scores. Empty content scores brand/quality=10 (no rule to violate) which the
# 4-bucket average can't pull under 7 — mirror judge's _MISSION_ABSENT_CAP pattern.
MISSING_FIELD_CAP = 4.0
# AA-234: failure codes that HARD-BLOCK approve of a human-edited version even when the
# overall score clears MIN_QUALITY. These are rule violations that must never reach gold
# (SEO length/floor, brand deny-list, forbidden words, missing fields) — the exact class
# the Review Queue exists to catch. Soft codes (HIGHLIGHTS_*, *_GENERIC, SUMMARY_OFF_BRAND)
# are surfaced to the reviewer but do NOT block.
_HARD_BLOCK_CODES = frozenset({
    "META_TOO_SHORT", "SEO_META_TOO_LONG", "SEO_TITLE_TOO_LONG",
    "META_INCOMPLETE_SENTENCE", "BRAND_SEO_META_VIOLATION",
    "FORBIDDEN_WORD", "MISSING_FIELD",
})

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
    # brand differentiation fields (AA-202)
    brand_core_idea:        str
    brand_customer_segment: str
    brand_customer_mindset: str
    brand_voice_examples:   list
    brand_good_examples:    str
    model_tier:             str
    fallback_used:          bool   # AA-213: True khi Sonnet T1 fell back to Haiku T2
    subtitle_focus:         str
    is_tenant_rewrite:      bool
    is_branded:             bool
    failure_codes:          list
    sub_scores:             dict
    passed_count:           int
    failed_count:           int
    seo_mode:               str    # "dataforseo" | "custom_keywords" | "disabled"
    # brand audit fields (AA-133)
    brand_audit_status:     str    # "pass" | "flagged" | "manual_check" | ""
    brand_audit_codes:      list
    brand_audit_issues:     list
    brand_audit_fields:     list
    lessons_extracted:      list
    # flag fix tracking (AA-134)
    fix_pass_applied:       bool
    fix_pass_fields:        list
    # AA-206: GPT-4.1 two-model judge fields (set by judge_node when a brand profile is present)
    judge_brand_fit:            float
    judge_cross_brand_distinct: float
    judge_mission_present:      bool
    judge_feedback:             str
    # AA-209: judge_score must be declared too, else LangGraph strips it from the final state and it
    # never reaches _rewrite_tour → _build_generated_metadata (metadata.judge.judge_score stayed null).
    judge_score:                float
    # AA-215: revalidate-after-flag_fix verification (POST-fix). revalidate_ran=True chi khi
    # fix_pass_applied; revalidate_passed phan anh ket qua re-validate+re-judge tren content da sua.
    revalidate_ran:         bool
    revalidate_passed:      bool

# code → (dimension, deduction)
_FAILURE_MAP: dict[str, tuple[str, float]] = {
    "MISSING_FIELD":             ("structure", 1.5),
    "HIGHLIGHTS_NOT_LIST":       ("structure", 1.0),
    "HIGHLIGHTS_TOO_FEW":        ("structure", 0.5),
    "SUBTITLE_GENERIC":          ("brand",     1.0),
    "SUMMARY_OFF_BRAND":         ("brand",     1.0),
    "BRAND_SEO_META_VIOLATION":  ("brand",     1.5),
    "FORBIDDEN_WORD":            ("quality",   0.5),
    "HIGHLIGHTS_TOO_GENERIC":    ("quality",   0.5),
    "SEO_TITLE_TOO_LONG":        ("seo",       0.5),
    "SEO_META_TOO_LONG":         ("seo",       0.5),
    "META_INCOMPLETE_SENTENCE":  ("seo",       1.0),
    "META_TOO_SHORT":            ("seo",       0.5),
    "ITINERARY_STRUCTURE_WEAK":  ("structure", 1.0),
    "DFS_INTENT_UNDERUSED":      ("seo",       1.0),
}

# AA-240: canonical validate-node forbidden list (single source; validate_node + review-queue
# handler both consume so the re-derived per-field reason can never drift from what fired).
_VALIDATE_FORBIDDEN = [
    "curated", "pristine", "refined", "tailored", "bespoke",
    "stunning", "breathtaking", "magical", "paradise",
    "cheap", "deal", "book now", "instant booking", "discount",
]

# AA-240: failure code -> editable gc field (column) so the review UI marks which field failed.
# Multi-field codes (FORBIDDEN_WORD, MISSING_FIELD) are resolved by re-scanning live content in
# the handler, so they are intentionally NOT in this 1:1 map.
_CODE_FIELD_MAP = {
    "SUBTITLE_GENERIC":          "aa_subtitle",
    "SUMMARY_OFF_BRAND":         "aa_summary",
    "HIGHLIGHTS_NOT_LIST":       "aa_highlights",
    "HIGHLIGHTS_TOO_FEW":        "aa_highlights",
    "HIGHLIGHTS_TOO_GENERIC":    "aa_highlights",
    "ITINERARY_STRUCTURE_WEAK":  "aa_itineraries",
    "SEO_TITLE_TOO_LONG":        "seo_title",
    "SEO_META_TOO_LONG":         "seo_meta",
    "META_TOO_SHORT":            "seo_meta",
    "META_INCOMPLETE_SENTENCE":  "seo_meta",
    "BRAND_SEO_META_VIOLATION":  "seo_meta",
    "DFS_INTENT_UNDERUSED":      "seo_meta",
}

def _build_brand_diff_block(state: ContentState) -> str:
    """AA-202: build the brand-differentiation system block from brand_* state fields.

    Pure string assembly (no I/O) so it can be unit-tested without LLM/DB. Returns "" when
    none of the differentiating signals are present (old/default brands) → backward-compatible.
    """
    core_idea    = state.get("brand_core_idea", "") or ""
    cust_segment = state.get("brand_customer_segment", "") or ""
    cust_mindset = state.get("brand_customer_mindset", "") or ""
    voice_ex     = [v for v in (state.get("brand_voice_examples") or []) if v]
    good_ex      = state.get("brand_good_examples", "") or ""

    if not (core_idea or cust_mindset or voice_ex):
        return ""

    diff_block = "\n\nBRAND DIFFERENTIATION PROFILE (this client's distinct angle — the rewrite MUST reflect it):"
    if core_idea:
        diff_block += f"\n- Core idea: {core_idea}"
    if cust_segment:
        diff_block += f"\n- Who this is for: {cust_segment}"
    if cust_mindset:
        diff_block += f"\n- What this traveller wants: {cust_mindset}"
    if voice_ex:
        diff_block += f"\n- Voice (tone words): {', '.join(voice_ex)}"
    if good_ex:
        diff_block += f"\n- Example of this brand's voice on a single moment: {good_ex}"
    diff_block += (
        "\n\nCONTRAST REQUIREMENT: The summary, highlights, itineraries (including each day-title), "
        "and the overall framing MUST be written from THIS brand's specific angle and mindset above. "
        "Do NOT produce generic copy that would fit any travel brand. If the same tour were rewritten "
        "for a different brand, the wording, emphasis, and framing must be clearly distinct — not a "
        "synonym swap. Lead with what makes THIS brand's take different."
    )
    # AA-206: negative contrast — show the generic register that MUST be avoided so the model has a
    # concrete anti-pattern, not just an abstract instruction.
    diff_block += (
        "\n\nGENERIC PHRASING TO AVOID (these read identically for any brand — do NOT write like this): "
        "'connects the country's primary cultural regions', 'moves through layered geography', "
        "'a journey through diverse landscapes', 'experience the best of' — they describe a route, not "
        "THIS brand's mission. Instead, lead every field with THIS brand's specific mission angle and "
        "let it shape what you foreground; do not merely synonym-swap a generic description."
    )
    return diff_block

def generate_node(state: ContentState) -> ContentState:
    """Node 1: Generate content via LLMClient."""
    client = LLMClient()
    prompt = build_rewrite_prompt(
        state["tour"],
        state["seo"],
        state.get("few_shots", []),
        subtitle_focus=state.get("subtitle_focus", "standard"),
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
    # AA-202: inject brand differentiation profile + contrast rule (no-op for old/default brands)
    system += _build_brand_diff_block(state)
    if style_guide:
        prompt += f"\n\nSTYLE GUIDE FOR THIS CLIENT:\n{style_guide}"
    fw = [w for w in (state.get("brand_forbidden_words") or []) if w]
    if fw:
        system += "\n\nFORBIDDEN WORDS (never use): " + ", ".join(fw)

    is_branded = bool(brand_sp)
    prompt_len = len(system)
    logger.info("llm_prompt_built", prompt_len=prompt_len, is_branded=is_branded,
                retry=state.get("retry_count", 0))
    if not is_branded:
        logger.warning("unbranded_generation", tour_name=state.get("tour", {}).get("name", ""))

    request = LLMRequest(
        system_prompt=system,
        user_prompt=prompt,
        model_tier=state.get("model_tier", "haiku"),
    )

    resp = None
    try:
        resp = client.generate(request)
        # Strip markdown fences nếu LLM wrap JSON trong ```json ... ```
        raw = resp.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        # AA-217: deterministic json-repair salvage on malformed output (no LLM re-ask).
        try:
            generated = json.loads(raw)
        except json.JSONDecodeError as e:
            salvaged = repair_json(raw, return_objects=True)
            if isinstance(salvaged, dict) and salvaged.get("name"):
                generated = salvaged
                logger.info("json_repair_salvaged",
                            tour_id=state.get("tour_id"),
                            model_used=resp.model_used,
                            retry_count=state.get("retry_count"),
                            raw_len=len(raw))
            else:
                logger.warning("json_parse_failed",
                               error=str(e),
                               raw_len=len(raw),
                               char_offset=e.pos,
                               model_used=resp.model_used if resp else None,
                               fallback_used=resp.fallback_used if resp else None,
                               retry_count=state.get("retry_count"))
                return {**state, "generated": {}, "is_branded": is_branded,
                        "cost_usd": state.get("cost_usd", 0) + resp.cost_usd,
                        "error": f"JSON parse error: {e}"}
        logger.info("content_generated", retry=state.get("retry_count", 0),
                    model=resp.model_used, cost=resp.cost_usd)
        # AA-225: persist keywords thực sự inject vào prompt (khớp prompts.py:61 + validate_node normalize)
        _seo_used = state.get("seo", {})
        _kws_raw = _seo_used.get("top_keywords", []) or _seo_used.get("keywords", {}).get("top_keywords", [])
        _kws_norm = [
            (kw["keyword"] if isinstance(kw, dict) else str(kw))
            for kw in _kws_raw[:5] if kw
        ]
        if isinstance(generated, dict):
            generated["seo_keywords_used"] = _kws_norm
        return {
            **state,
            "generated":  generated,
            "cost_usd":   state.get("cost_usd", 0) + resp.cost_usd,
            "model_used": resp.model_used,
            "is_branded": is_branded,
            "error":      "",
            "fallback_used": resp.fallback_used,
        }
    except Exception as e:
        logger.error("generation_failed", error=str(e))
        return {**state, "generated": {}, "is_branded": is_branded,
                "cost_usd": state.get("cost_usd", 0) + (resp.cost_usd if resp else 0),
                "error": str(e)}

def validate_node(state: ContentState) -> ContentState:
    """Node 2: Quality check — structured failure codes, 4 sub-dimensions, score 0-10."""
    generated = state.get("generated", {})
    if generated.get("itineraries"):
        import re as _re
        it = generated["itineraries"]
        if isinstance(it, str):
            it = _re.sub(r"\*\*([^*]+)\*\*", r"\1", it)
            it = it.replace("**", "")
            # AA-228: normalize day-title separator to a single canonical form across model tiers.
            # Haiku emits "Day N -- title | prose ... || Day N+1", Sonnet/GPT emit "Day N — title".
            it = it.replace("||", "\n\n")                         # inter-day inline sep -> blank line
            it = _re.sub(r"\bDay\s+(\d+)\s*[-–—]+\s*", r"Day \1 — ", it)  # any dash -> em-dash
            it = _re.sub(r"(Day\s+\d+\s+—\s+[^\n|]+?)\s*\|\s*", r"\1\n", it)  # "title | prose" -> newline
            # ensure a blank line before each "Day N" that isn't already at start/after blank line
            it = _re.sub(r"(?<=\S)\n?(?=Day\s+\d+\s+—)", "\n\n", it.lstrip())
            it = _re.sub(r"[ \t]+\n", "\n", it)                   # strip trailing spaces before newline
            it = _re.sub(r"\n[ \t]+", "\n", it)                   # strip leading spaces after newline
            it = _re.sub(r"\n{3,}", "\n\n", it)                   # collapse extra blank lines
        elif isinstance(it, dict):
            parts = [f"{k}: {v}" for k, v in it.items()]
            it = "\n\n".join(parts)
        elif isinstance(it, list):
            parts = []
            for item in it:
                if isinstance(item, dict):
                    day   = item.get("day", "")
                    title = item.get("title", "")
                    desc  = item.get("description", "")
                    acts  = item.get("activities", [])
                    day_str = f"Day {day}"
                    if title:
                        day_str += f" — {title}"
                    if desc:
                        day_str += f"\n{desc}"
                    if acts:
                        act_list = ", ".join(str(a) for a in acts) if isinstance(acts, list) else str(acts)
                        day_str += f"\n*Activities: {act_list}*"
                    parts.append(day_str)
                else:
                    parts.append(str(item))
            it = "\n\n---\n\n".join(parts)
        else:
            it = str(it)
        generated = {**generated, "itineraries": str(it).strip()}
    tour      = state.get("tour", {})
    issues: list[str] = []
    fired:  list[str] = []
    score = 10.0

    # Required fields
    for field in ["name", "subtitle", "summary", "highlights", "itineraries",
                  "seo_title", "seo_meta"]:
        if not generated.get(field):
            issues.append(f"Missing field: {field}")
            fired.append("MISSING_FIELD")
            score -= 1.5

    # highlights must be list with 3+ items
    highlights = generated.get("highlights", [])
    if not isinstance(highlights, list):
        issues.append("highlights must be a list")
        fired.append("HIGHLIGHTS_NOT_LIST")
        score -= 1.0
    elif len(highlights) < 3:
        issues.append(f"highlights has only {len(highlights)} items, need 3+")
        fired.append("HIGHLIGHTS_TOO_FEW")
        score -= 0.5

    # Subtitle must not be generic
    subtitle = generated.get("subtitle", "").lower()
    generic_subtitle_flags = [
        "kingdom of happiness", "land of thunder dragon",
        "last shangri-la", "pristine wilderness",
    ]
    for flag in generic_subtitle_flags:
        if flag in subtitle:
            issues.append(f"Generic subtitle phrase: '{flag}'")
            fired.append("SUBTITLE_GENERIC")
            score -= 1.0

    # Forbidden words — AA core list + tenant custom list
    forbidden = list(_VALIDATE_FORBIDDEN)  # AA-240: shared const
    # P3-S3: Merge tenant forbidden_words (lowercase, deduplicated)
    tenant_forbidden = [w.lower().strip() for w in (state.get("brand_forbidden_words") or []) if w]
    all_forbidden = list(dict.fromkeys(forbidden + tenant_forbidden))  # preserve order, dedupe

    content_text = json.dumps(generated).lower()
    for word in all_forbidden:
        if word in content_text:
            issues.append(f"Forbidden word: '{word}'")
            fired.append("FORBIDDEN_WORD")
            score -= 0.5

    # Highlights specificity — must not be pure generic
    generic_highlight_patterns = [
        "panoramic views", "beautiful landscapes", "stunning scenery",
        "breathtaking views", "pristine nature", "gross national happiness",
    ]
    highlights_text = " ".join(highlights).lower() if isinstance(highlights, list) else ""
    for pattern in generic_highlight_patterns:
        if pattern in highlights_text:
            issues.append(f"Generic highlight phrase: '{pattern}'")
            fired.append("HIGHLIGHTS_TOO_GENERIC")
            score -= 0.5

    # seo_meta must not contain budget/accommodation language (AA audience = $250k+)
    _seo_meta_forbidden = SEO_META_FORBIDDEN  # AA-238/D4: canonical deny-list
    seo_meta_lower = (generated.get("seo_meta") or "").lower().replace("-", " ")  # AA-238: catch hyphen variants
    for term in _seo_meta_forbidden:
        if term in seo_meta_lower:
            issues.append(f"Budget language in seo_meta: '{term}'")
            fired.append("BRAND_SEO_META_VIOLATION")
            score -= 1.5
            break  # one violation is enough

    # SEO field lengths
    if len(generated.get("seo_title", "")) > 60:
        issues.append("seo_title exceeds 60 chars")
        fired.append("SEO_TITLE_TOO_LONG")
        score -= 0.5
    if len(generated.get("seo_meta", "")) > SEO_META_MAX:
        issues.append("seo_meta exceeds 155 chars")
        fired.append("SEO_META_TOO_LONG")
        score -= 0.5
    # AA-201: enforce lower band — no under-length meta
    _meta_len = generated.get("seo_meta", "").strip()
    if _meta_len and len(_meta_len) < SEO_META_MIN:
        issues.append("seo_meta under 140 chars")
        fired.append("META_TOO_SHORT")
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
            fired.append("SUMMARY_OFF_BRAND")
            score -= 1.0
            break

    # META_INCOMPLETE_SENTENCE: seo_meta must read as a complete sentence (AA-201)
    meta = generated.get("seo_meta", "").strip()
    if meta and not meta_complete_sentence(meta):
        issues.append("seo_meta is not a complete sentence")
        fired.append("META_INCOMPLETE_SENTENCE")
        score -= 1.0

    # ITINERARY_STRUCTURE_WEAK: must have day markers and be substantive
    itinerary = generated.get("itineraries", "") or ""
    has_day_marker = bool(re.search(r'\bday\s*[1-9one two three]\b', itinerary.lower()))
    if not has_day_marker or len(itinerary) < 80:
        issues.append("Itinerary lacks day structure or is too short")
        fired.append("ITINERARY_STRUCTURE_WEAK")
        score -= 1.0

    # DFS_INTENT_UNDERUSED: if SEO keywords exist, at least one should appear in title+meta
    # B1: handle both flat {"top_keywords": [...]} and nested {"keywords": {"top_keywords": [...]}}
    _seo    = state.get("seo", {})
    seo_kws = _seo.get("top_keywords", []) or _seo.get("keywords", {}).get("top_keywords", [])
    if seo_kws:
        kw_texts = [
            (kw["keyword"] if isinstance(kw, dict) else str(kw)).lower()
            for kw in seo_kws if kw
        ]
        seo_field_text = (
            (generated.get("seo_title", "") or "") + " " +
            (generated.get("seo_meta", "") or "")
        ).lower()
        if kw_texts and not any(kw in seo_field_text for kw in kw_texts):
            issues.append("SEO keywords not reflected in seo_title or seo_meta")
            fired.append("DFS_INTENT_UNDERUSED")
            score -= 1.0

    # Sub-score computation — each dimension starts at 10, deducts its own codes
    score = max(0.0, score)
    sub_scores = {
        dim: max(0.0, 10.0 - sum(
            _FAILURE_MAP[code][1] for code in fired
            if code in _FAILURE_MAP and _FAILURE_MAP[code][0] == dim
        ))
        for dim in ("brand", "seo", "structure", "quality")
    }
    # AA-216: a MISSING_FIELD means the generation is structurally incomplete (often a JSON-parse
    # failure → empty generated). Cap below MIN_QUALITY so should_retry never returns "done" and
    # _is_publishable (AA-211) blocks it — empty content must route to retry/HITL, never gold.
    _structural_fail = ("MISSING_FIELD" in fired) or (not generated.get("name"))
    quality_score = sum(sub_scores.values()) / 4
    if _structural_fail:
        quality_score = min(quality_score, MISSING_FIELD_CAP)
    failure_codes = list(dict.fromkeys(fired))   # unique, first-seen order
    passed_count  = sum(1 for d in sub_scores.values() if d == 10.0)
    failed_count  = len(failure_codes)
    feedback      = "; ".join(issues) if issues else ""

    logger.info("validation_done", score=quality_score, issues=len(issues),
                retry=state.get("retry_count", 0),
                failure_codes=failure_codes, sub_scores=sub_scores)

    return {
        **state,
        "generated":     generated,
        "quality_score": quality_score,
        "feedback":      feedback,
        "failure_codes": failure_codes,
        "sub_scores":    sub_scores,
        "passed_count":  passed_count,
        "failed_count":  failed_count,
    }

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

def revalidate_node(state: ContentState) -> ContentState:
    """AA-215: verify the fix pass actually worked before publish.

    Only re-checks tours that flag_fix repaired (fix_pass_applied=True). For those, re-run the
    SAME validate + judge nodes on the repaired content and rewrite brand_audit_status to the
    POST-fix state (was stale/PRE-fix). Passthrough for everything else:
      - clean pass (no fix): already validated/judged, still publishable — untouched.
      - flagged/manual_check but NOT fixed: already blocked by _is_publishable (AA-211) — untouched.
    Re-validate (rule-based, free) catches structural/SEO regressions from the fix; re-judge
    (GPT-4.1) re-confirms brand-fit. On fail -> manual_check so the existing export gate blocks it
    and _enqueue_review routes it to HITL.
    """
    if not state.get("fix_pass_applied"):
        return {**state, "revalidate_ran": False}

    # Re-run in the same order as the main graph: validate sets quality_score that judge then
    # min()'s against. Calling judge alone would min against the stale pre-fix validate score.
    s = validate_node(state)
    s = judge_node(s)

    score = s.get("quality_score", 0.0)
    audit_status = s.get("brand_audit_status", "")
    # "clean" POST-fix = score gate passed AND the post-fix audit isn't itself manual_check.
    # (brand_audit_node ran pre-fix; we don't re-run it here — judge is the post-fix brand gate.)
    passed = score >= MIN_QUALITY and audit_status != "manual_check"

    new_status = "fixed" if passed else "manual_check"
    logger.info("revalidate_done", passed=passed, post_fix_score=score,
                new_brand_audit_status=new_status,
                fix_fields=state.get("fix_pass_fields", []))
    return {
        **s,
        "brand_audit_status": new_status,
        "revalidate_ran":     True,
        "revalidate_passed":  passed,
    }

def human_edit_gate_node(state: ContentState) -> ContentState:
    """AA-234: gate node for the re-validation graph (human-edited content).

    Unlike revalidate_node (which only verifies an automated flag_fix pass and no-ops when
    fix_pass_applied is False), this runs on content a reviewer edited by hand. flag_fix is
    deliberately NOT in this graph — the human edit is final, the system only re-scores and
    gates. Pass = validate+judge score clears MIN_QUALITY AND brand_audit isn't manual_check.
    On fail the reviewer must fix and re-validate again before approve is allowed.
    """
    score = state.get("quality_score", 0.0)
    audit_status = state.get("brand_audit_status", "")
    codes = state.get("failure_codes", []) or []
    hard_hits = sorted(set(codes) & _HARD_BLOCK_CODES)
    passed = (
        score >= MIN_QUALITY
        and audit_status != "manual_check"
        and not hard_hits
    )
    logger.info("human_edit_revalidate_done", passed=passed, score=score,
                brand_audit_status=audit_status, hard_block_hits=hard_hits,
                failure_codes=codes)
    return {
        **state,
        "revalidate_ran":    True,
        "revalidate_passed": passed,
    }


def build_revalidation_graph() -> StateGraph:
    """AA-234: re-score a human-edited generated_content version IN PLACE.

    validate -> judge -> brand_audit -> human_edit_gate -> END. NO generate (content is the
    reviewer's edit, not LLM-generated), NO retry loop, NO flag_fix (the human edit is final).
    Compiled over the SAME ContentState so no field is stripped from the final state.
    """
    graph = StateGraph(ContentState)
    graph.add_node("validate", validate_node)
    graph.add_node("llm_judge", judge_node)
    graph.add_node("brand_audit", brand_audit_node)
    graph.add_node("human_edit_gate", human_edit_gate_node)

    graph.set_entry_point("validate")
    graph.add_edge("validate", "llm_judge")
    graph.add_edge("llm_judge", "brand_audit")
    graph.add_edge("brand_audit", "human_edit_gate")
    graph.add_edge("human_edit_gate", END)

    return graph.compile()


def build_graph() -> StateGraph:
    graph = StateGraph(ContentState)

    graph.add_node("generate", generate_node)
    graph.add_node("validate", validate_node)
    graph.add_node("llm_judge", judge_node)
    graph.add_node("increment_retry", increment_retry)
    graph.add_node("brand_audit", brand_audit_node)
    graph.add_node("flag_fix", flag_fix_node)
    graph.add_node("revalidate", revalidate_node)

    graph.set_entry_point("generate")
    graph.add_edge("generate", "validate")
    # AA-206: GPT-4.1 judge sits between validate and the retry decision so should_retry routes on
    # the judge-adjusted quality_score (Bedrock fixes against judge feedback via the retry loop).
    graph.add_edge("validate", "llm_judge")
    graph.add_conditional_edges("llm_judge", should_retry, {
        "done":  "brand_audit",
        "retry": "increment_retry",
        "hitl":  END,
    })
    graph.add_edge("brand_audit", "flag_fix")
    graph.add_edge("flag_fix", "revalidate")
    graph.add_edge("revalidate", END)
    graph.add_edge("increment_retry", "generate")

    return graph.compile()
