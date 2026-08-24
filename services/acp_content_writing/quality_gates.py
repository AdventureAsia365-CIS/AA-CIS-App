"""
services.acp_content_writing.quality_gates — T10, inline in the same request as T9 (Nghiep's
confirmed architecture, docs/claude_audit/AA-450-01-t9-t10-retry-loop-investigation.md). Full
gate-by-gate mapping/reasoning: docs/claude_audit/AA-450-02-t10-gate-map.md.

5 gates, mirroring services/acp_produce/gates.py's own `GateResult`/one-function-per-gate/
`gate_fns` list shape (kept for the same reason N7 has it — "dễ đọc/debug/mở rộng sau này", per
the build task's own instruction) WITHOUT importing anything from that module — every gate here
is written fresh against T9's short single-channel content, referenced not reused (ADR §0.5).

Each gate is a plain SYNCHRONOUS function — same "wrap at the async/sync boundary" decision as
generate.py (see that module's docstring). `run_quality_gates()` (the one function service.py
calls) is also synchronous for the same reason; service.py wraps the WHOLE call in
`asyncio.to_thread()`, not each gate individually, since all 5 gates for one attempt always run
together on the same request.
"""
from __future__ import annotations

import json
import re
from typing import Optional, TypedDict

import structlog

from services.acp_content_writing.framework_rubrics import get_framework_rubric
from services.acp_produce.judge_client import invoke_judge, parse_judge_json
from services.acp_shared.grounding import find_novel_numeric_claims

logger = structlog.get_logger()

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'‘’“”])")

# AA-450-02 gate map, F2 row: union of N7's own BANNED_PATTERNS_SEED (gates.py) and
# SKILL_v2.md's own "Avoid" list — the two only partially overlap, T9 is answerable to its own
# source doc's list too, not only N7's. Kept as regexes (case-insensitive), same shape as N7's
# _BANNED_PATTERNS_COMPILED.
_BANNED_PATTERNS_SEED = [
    r"\bnestled\b", r"\btapestry\b", r"\bhidden gem(s)?\b", r"\bmust[- ]visit\b",
    r"\bmust[- ]see\b", r"\bunforgettable\b", r"\bbreathtaking\b", r"\bbucket[- ]list\b",
    r"\bwhether you'?re .{3,40} or .{3,40}\b", r"\bin conclusion\b", r"\bembark on\b",
    r"\bawait(s)? you\b", r"\bimmerse yourself\b", r"\blook no further\b", r"\bdelve\b",
    # SKILL_v2.md §Avoid — not in N7's own list
    r"\bin today'?s fast[- ]paced world\b", r"\bgame[- ]changing\b", r"\brevolutionary\b",
    r"\bunlock your potential\b", r"\btake your .{2,30} to the next level\b",
    r"\bwhether you'?re a beginner or (an? )?expert\b",
]
_BANNED_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in _BANNED_PATTERNS_SEED]

_JUDGE_SYSTEM_PROMPT = (
    "You are a structural editor. You score writing against a fixed rubric — you do not "
    "rewrite, you do not soften scores, and every score of 1 must be backed by an exact quote "
    "from the piece as evidence. You have not seen and do not know how this piece was generated "
    "or instructed to be written; judge only what is on the page in front of you."
)

# AA-450-02 gate map, F9 row: N7's own real facebook rubric reused verbatim as the baseline
# across ALL channels — not per-channel bespoke fields, per ADR-2026-009 ("extend from real
# failures, don't guess ahead of data") given T9 has zero real production pieces yet for any
# channel. Flagged, not oversold as final — the same caveat gates.py's own F9-social docstring
# carries for its 2-channel version of this same choice.
_BRAND_VOICE_FIELDS = ["brand_fit", "cta_clear", "human_read"]
_BRAND_VOICE_FAILURE_CODES = [
    "SUMMARY_OFF_BRAND", "CTA_NOT_REFLECTED", "GENERIC_AI_WORDING", "FACT_CHECK_MANUAL_CHECK",
]

# Same concrete good/bad calibration anchor as gates.py::GENERIC_AI_WORDING_ANCHOR (referenced,
# not imported — this module has no dependency on services.acp_produce) — the mechanism (a
# judge given only an abstract label drifts; a concrete good/bad pair anchors it) is real and
# worth keeping, the exact anchor text is T9's own (facebook/tiktok-shaped copy, not blog).
_GENERIC_AI_WORDING_ANCHOR = (
    "\n\nWHAT COUNTS AS GENERIC_AI_WORDING (concrete anchor, not a vague vibe check):\n"
    "- BAD (generic — flag this): \"Experience the best of this incredible destination on an "
    "unforgettable journey.\" — templated superlatives, no concrete detail, swappable onto any "
    "destination unchanged.\n"
    "- GOOD (specific, on-brand — do NOT flag this): a sentence built from a real, concrete, "
    "verifiable detail from the content seed (a place name, a real fact, a specific number or "
    "geography) — calm and precise, no adjective padding, no superlatives.\n"
    "Do not flag calm, precise, unhurried writing as \"too plain\" just because it lacks "
    "superlatives. Reserve GENERIC_AI_WORDING for templated filler that could be copy-pasted "
    "onto any other brand's any other piece unchanged.\n"
)


class GateResultLite(TypedDict):
    gate: str
    passed: bool
    violations: list[str]
    repairable: bool


def _result(gate: str, violations: list[str], repairable: bool = True) -> GateResultLite:
    return {"gate": gate, "passed": not violations, "violations": violations, "repairable": repairable}


# ---------------------------------------------------------------- CTA gate (F6-DET-half)

def gate_cta_present(cta: Optional[str]) -> GateResultLite:
    """AA-450-02 gate map, F6 row — direct precedent from N7's own `_is_f6_content_fixable()`
    filter: a missing CTA is external/caller-state, not something a rewrite can fix, so this
    fails NON-repairable (immediate hold, no repair round spent) exactly like N7's "no
    cta_target" case. This gate runs FIRST for the same reason N7's `output_rules` runs before
    the rest of the stack — no reason to pay for the 2 LLM-judge gates below on a piece that was
    always going to hold regardless."""
    if not cta or not cta.strip():
        return _result("F6_cta_present", ["no CTA available for this request"], repairable=False)
    return _result("F6_cta_present", [])


# ---------------------------------------------------------------- F1-adjusted (grounding)

def gate_grounding(content_text: str, atom_text: str) -> GateResultLite:
    """AA-450-02 gate map, F1 row — no [R:atom_id] tags (T9's output is tenant-facing copy, a
    visible citation tag would look broken, same reasoning acp_s4_social/writer.py's
    tag-free output already implied). Reuses services.acp_shared.grounding.
    find_novel_numeric_claims() directly — the SAME shared utility N7's own gate_grounding()
    and S1's check_grounding() already share (ADR-2026-033, "one implementation, not two that
    can drift") — sentence-by-sentence against the ONE chosen atom's text (no tag parsing
    needed, there is exactly one source)."""
    violations: list[str] = []
    for sent in _SENT_SPLIT_RE.split(content_text or ""):
        novel = find_novel_numeric_claims(sent, [atom_text])
        if novel:
            violations.append(
                f"sentence states {novel} not present in the content seed: '{sent.strip()[:100]}'"
            )
    return _result("F1_grounding", violations)


# ---------------------------------------------------------------- F2-adjusted (banned patterns)

def gate_banned_patterns(content_text: str, atom_text: str) -> GateResultLite:
    """AA-450-02 gate map, F2 row — deterministic, cheap. A match is exempt only when it's
    genuinely present (case-insensitive) in the atom's own source text — same B12 carve-out N7's
    own gate_banned_patterns() applies, adapted to T9's single-atom shape."""
    violations: list[str] = []
    atom_lower = (atom_text or "").lower()
    for pattern in _BANNED_PATTERNS_COMPILED:
        for m in pattern.finditer(content_text or ""):
            phrase = m.group(0).lower()
            if phrase in atom_lower:
                continue
            violations.append(f"banned pattern /{pattern.pattern}/ -> '{m.group(0)}'")
    return _result("F2_banned_patterns", violations)


# ---------------------------------------------------------------- F4-adjusted (extreme length only)

# STEP0/build task's own explicit instruction: no hardcoded exact per-channel word limit (no
# source document has one). "Extreme" is deliberately generous — this catches an empty/near-empty
# response or a multi-thousand-word runaway generation, nothing narrower.
_MIN_CHARS = 20
_MAX_CHARS = 6000


def gate_extreme_length(content_text: str) -> GateResultLite:
    """AA-450-02 gate map, F4 row (replaced, not ported — N7's version needs a Brief.word_range
    T9 has no equivalent of)."""
    length = len(content_text or "")
    if length < _MIN_CHARS:
        return _result("F4_extreme_length", [f"content is only {length} chars — effectively empty"])
    if length > _MAX_CHARS:
        return _result("F4_extreme_length", [f"content is {length} chars — far beyond any real channel example"])
    return _result("F4_extreme_length", [])


# ---------------------------------------------------------------- F8-adjusted (framework judge)

def gate_framework(content_text: str, goal_key: str) -> GateResultLite:
    """AA-450-02 gate map, F8 row — same Nova Pro judge, same binary 1/0 + mandatory-evidence-
    quote contract, same writer-prompt isolation as N7's gate_framework() (reuses
    services.acp_produce.judge_client.invoke_judge/parse_judge_json directly — those two
    functions are pure LLM-call plumbing, not N7 business logic, importing them is not a
    departure from ADR §0.5's "don't reuse acp_s4_social/acp_produce business logic"). Rubric
    items come from framework_rubrics.py (derived from goals.py's own `logic` field), not N7's
    FRAMEWORK_RUBRICS (T8's 8 goals include SLAP/FAB/BAB/5W1H, which N7's table doesn't cover)."""
    rubric_items = get_framework_rubric(goal_key)
    contract = json.dumps({
        "items": [{"criterion": "str", "score": "1|0",
                    "evidence": "exact quote from the piece, or empty string if score is 0"}],
    }, indent=1)
    user_prompt = (
        f"PIECE:\n{content_text}\n\n"
        f"RUBRIC — score each item 1 (met) or 0 (not met), quoting exact evidence from the "
        f"piece for every 1:\n- " + "\n- ".join(rubric_items) +
        f"\n\nOutput ONLY JSON matching this contract:\n{contract}"
    )
    try:
        raw = invoke_judge(_JUDGE_SYSTEM_PROMPT, user_prompt)
        data = parse_judge_json(raw["text"])
    except Exception as e:
        logger.warning("t10_f8_judge_unavailable", error=str(e))
        return _result("F8_framework", [f"judge unavailable: {e} — treated as fail"])

    violations: list[str] = []
    items = data.get("items") or []
    for item in items:
        criterion = item.get("criterion", "(unnamed criterion)")
        score = str(item.get("score"))
        evidence = (item.get("evidence") or "").strip()
        if score != "1":
            violations.append(f"framework criterion failed: {criterion}")
        elif not evidence:
            violations.append(f"framework criterion '{criterion}' scored 1 with no evidence quote — treated as fail")
    if not items:
        violations.append("judge returned no rubric items — treated as fail, not a silent pass")
    return _result("F8_framework", violations)


# ---------------------------------------------------------------- F9-adjusted (brand/CTA/voice judge)

def gate_brand_voice(content_text: str, cta: str, brand_rubric_text: str) -> GateResultLite:
    """AA-450-02 gate map, F9 row — see module docstring for the rubric-field/failure-code
    choices. `cta_clear` also absorbs N7's dropped F6 literal-CTA-substring check (semantic
    judgment, since T9's CTA is a free-text tenant value, not N7's one fixed brand phrase — no
    hardcoded-phrase false-positive carve-out ports as-is for this reason)."""
    contract = json.dumps({
        "status": "pass|flagged|manual_check",
        **{f: "1|0" for f in _BRAND_VOICE_FIELDS},
        "failure_codes": [f"subset of {_BRAND_VOICE_FAILURE_CODES}"],
        "flagged_phrases": ["exact quoted phrase for each SUMMARY_OFF_BRAND/GENERIC_AI_WORDING "
                             "code above — [] if neither code is used"],
        "notes": "str",
    }, indent=1)
    user_prompt = (
        f"PIECE:\n{content_text}\n\n"
        f"REQUIRED CALL TO ACTION FOR THIS PIECE: {cta}\n\n"
        f"BRAND RUBRIC:\n{brand_rubric_text}\n"
        f"{_GENERIC_AI_WORDING_ANCHOR}\n"
        "Score every field 1 or 0. cta_clear=1 only if the required CTA above is present and "
        "reads as a single, unambiguous action — not a vague sign-off. Use ONLY the listed "
        f"failure codes: {_BRAND_VOICE_FAILURE_CODES}. If you use SUMMARY_OFF_BRAND or "
        "GENERIC_AI_WORDING, you MUST quote the exact offending phrase in flagged_phrases. The "
        "required CTA text itself is never grounds for SUMMARY_OFF_BRAND or GENERIC_AI_WORDING "
        "on its own — do not flag it. When uncertain about a factual claim: "
        "status=manual_check + FACT_CHECK_MANUAL_CHECK.\n\n"
        f"Output ONLY JSON matching this contract:\n{contract}"
    )
    try:
        raw = invoke_judge(_JUDGE_SYSTEM_PROMPT, user_prompt)
        data = parse_judge_json(raw["text"])
    except Exception as e:
        logger.warning("t10_f9_judge_unavailable", error=str(e))
        return _result("F9_brand_voice", [f"judge unavailable: {e} — treated as fail"])

    status = data.get("status", "manual_check")
    failure_codes = [c for c in (data.get("failure_codes") or []) if c in _BRAND_VOICE_FAILURE_CODES]
    notes = data.get("notes") or ""
    passed = status == "pass"
    violations: list[str] = []
    if not passed:
        reason = ", ".join(failure_codes) or notes or "(no reason given)"
        phrases = [p for p in (data.get("flagged_phrases") or []) if isinstance(p, str) and p.strip()]
        if phrases:
            reason += " — exact flagged phrase(s): " + "; ".join(f'"{p}"' for p in phrases)
        violations = [f"audit {status}: {reason}"]
    return _result("F9_brand_voice", violations)


# ---------------------------------------------------------------- orchestration

class QualityCheckOutcome(TypedDict):
    passed: bool
    gate_ledger: list[GateResultLite]
    first_failure: Optional[GateResultLite]


def run_quality_gates(
    *, content_text: str, atom_text: str, cta: Optional[str], goal_key: str, brand_rubric_text: str,
) -> QualityCheckOutcome:
    """Runs the T10 gate stack for ONE attempt. CTA-presence runs first and short-circuits the
    2 LLM-judge gates on failure (same "don't pay for a judge call on content that was always
    going to be rejected" reasoning N7's own output_rules pre-check uses) — every other gate
    always runs regardless of an earlier gate's outcome, same as N7's run_gates() (a repair
    fixing one gate must never ship while silently regressing another the caller never re-
    checked). `first_failure` is the first FAILED gate in this fixed order, used by service.py
    to pick which violations to feed the attempt-2 rewrite."""
    cta_result = gate_cta_present(cta)
    ledger = [cta_result]
    if not cta_result["passed"]:
        return {"passed": False, "gate_ledger": ledger, "first_failure": cta_result}

    gate_ledger = [
        cta_result,
        gate_grounding(content_text, atom_text),
        gate_banned_patterns(content_text, atom_text),
        gate_extreme_length(content_text),
        gate_framework(content_text, goal_key),
        gate_brand_voice(content_text, cta or "", brand_rubric_text),
    ]
    first_failure = next((g for g in gate_ledger if not g["passed"]), None)
    return {
        "passed": first_failure is None,
        "gate_ledger": gate_ledger,
        "first_failure": first_failure,
    }


__all__ = [
    "GateResultLite", "QualityCheckOutcome", "gate_cta_present", "gate_grounding",
    "gate_banned_patterns", "gate_extreme_length", "gate_framework", "gate_brand_voice",
    "run_quality_gates",
]
