"""
services.acp_produce.gates — MODULE F: N7 QA gate stack (AA-298 Phần A).

Only F1 grounding is implemented so far. Ported from the aa-marketing-v2
research build's aamc/gates.py::gate_grounding() with the P0-1 bug fixed
during the port (ADR-2026-029) rather than carrying it forward and patching
it later — see docs/implementation-notes/AA-298.md. F2-F9 land in the rest
of AA-298 Phần A.

Shares its entailment mechanism with S1-from-atom
(services/content_generation/s1_from_atom.py::check_grounding(), AA-325) via
services/acp_shared/grounding.py — one implementation, not two that can drift
(ADR-2026-033). ADR-2026-033 also documents why this is a narrow
numeric/measurement check rather than the whole-sentence token-overlap ratio
ADR-2026-029 originally specified: tested against 107 real (sentence, atom)
pairs from a live production audit, the token-overlap approach could not
separate real violations from real good content at any threshold.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from services.acp_produce.judge_client import invoke_judge, parse_judge_json
from services.acp_produce.models import REPAIR_TOTAL_MAX, GateResult, Piece
from services.acp_shared.grounding import find_novel_numeric_claims

TAG_RE = re.compile(r"\[(?:R|F):([^\]]+)\]")
# Same sentence-boundary heuristic used to build the real-data test fixture
# (tests/unit/fixtures/aa325_grounding_units.json) and s1_from_atom.py's gate.
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'‘’“”])")


def gate_grounding(body_tagged: str, valid_ids: set[str], text_by_id: dict[str, str]) -> GateResult:
    """F1 grounding (DET). Two checks, both required to pass:

    1. Closed-world — every [R:id]/[F:id] tag references an id that actually
       exists in `valid_ids` (the atom/fact set assigned to this brief).
    2. Entailment — no cited sentence asserts a number/measurement absent
       from the text of the id(s) it cites (see services/acp_shared/
       grounding.py for why this is narrower than plain tag-presence: a
       valid tag on a fabricated sentence used to pass this gate — that was
       P0-1)."""
    violations: list[str] = []
    body = body_tagged or ""

    tags = TAG_RE.findall(body)
    unknown = sorted({t for t in tags if t not in valid_ids})
    for uid in unknown:
        violations.append(f"unknown provenance id [{uid}] — not in the atom/fact set for this brief")

    for sent in _SENT_SPLIT_RE.split(body):
        cited = TAG_RE.findall(sent)
        if not cited:
            continue
        cited_texts = [text_by_id[c] for c in cited if c in text_by_id]
        novel = find_novel_numeric_claims(sent, cited_texts)
        if novel:
            violations.append(
                f"sentence states {novel} not present in its cited id(s): '{sent.strip()[:100]}'"
            )

    return GateResult(gate="F1_grounding", passed=not violations, violations=violations)


# ---------------------------------------------------------------- F8 framework judge (LLM, cross-weight)

# Deterministic rubric table — not LLM-invented, matches the framework the N6
# allocator (services/acp_planning/constants.FRAMEWORK_TABLE) already assigned
# per (funnel_stage, channel). The judge scores against THIS fixed list, never
# against its own idea of what a "good hub article" looks like.
FRAMEWORK_RUBRICS: dict[str, list[str]] = {
    "hub": ["covers the topic comprehensively via subsections",
            "each section answers a distinct sub-question"],
    "PAS": ["opens with the reader's problem", "agitates concretely",
            "resolves with the trip as solve"],
    "AIDA": ["attention hook first", "interest via specifics",
             "desire built on concrete moments", "single clear action (CTA)"],
    "hook_story_cta": ["first line is the hook", "one atom, one emotion", "ends with CTA"],
    "hook_beats_payoff": ["hook stated", "timed beats present", "payoff lands"],
    "reader_as_hero": ["reader is the subject, not the brand", "single CTA"],
}
_DEFAULT_FRAMEWORK_RUBRIC = ["structure matches the stated framework"]

_JUDGE_SYSTEM_PROMPT = (
    "You are a structural editor. You score writing against a fixed rubric — you do not "
    "rewrite, you do not soften scores, and every score of 1 must be backed by an exact "
    "quote from the piece as evidence. You have not seen and do not know how this piece "
    "was generated or instructed to be written; judge only what is on the page in front "
    "of you."
)


def gate_framework(piece_body: str, framework: str) -> GateResult:
    """F8 framework judge — LLM, Nova Pro, cross-weight from the writer per
    ADR-2026-014/ADR-2026-027/L3. The judge receives ONLY the piece body and
    a hard-anchored rubric (see FRAMEWORK_RUBRICS above) — never the writer's
    generation system/user prompt (services/acp_produce/judge_client.py
    documents why that isolation is structural, not just promised). Binary
    1/0 per criterion with a MANDATORY evidence quote for every 1 — never a
    1-10 scale, which invites drift with no accountable evidence trail."""
    rubric_items = FRAMEWORK_RUBRICS.get(framework, _DEFAULT_FRAMEWORK_RUBRIC)
    contract = json.dumps({
        "items": [{"criterion": "str", "score": "1|0",
                   "evidence": "exact quote from the piece, or empty string if score is 0"}],
    }, indent=1)
    user_prompt = (
        f"PIECE:\n{piece_body}\n\n"
        f"RUBRIC (framework: {framework}) — score each item 1 (met) or 0 (not met), quoting "
        f"exact evidence from the piece for every 1:\n- " + "\n- ".join(rubric_items) +
        f"\n\nOutput ONLY JSON matching this contract:\n{contract}"
    )
    try:
        raw = invoke_judge(_JUDGE_SYSTEM_PROMPT, user_prompt)
        data = parse_judge_json(raw["text"])
    except Exception as e:
        return GateResult(gate="F8_framework", passed=False,
                           violations=[f"judge unavailable: {e} — manual check"])

    items = data.get("items") or []
    violations = []
    for item in items:
        criterion = item.get("criterion", "(unnamed criterion)")
        score = str(item.get("score"))
        evidence = item.get("evidence") or ""
        if score != "1":
            violations.append(f"framework criterion failed: {criterion}")
        elif not evidence.strip():
            violations.append(f"framework criterion '{criterion}' scored 1 with no evidence quote — treated as fail")
    if not items:
        violations.append("judge returned no rubric items — treated as fail, not a silent pass")
    return GateResult(gate="F8_framework", passed=not violations, violations=violations)


# ---------------------------------------------------------------- F9 brand_seo_audit (LLM, cross-weight)

# Fixed failure-code vocabulary — the judge must classify into ONE of these,
# never invent its own label (a free-text failure reason can't be tracked,
# trended, or turned into an acp_output_rules entry later, N8 flywheel).
BRAND_SEO_FAILURE_CODES = [
    "PRODUCT_TRUTH_RISK", "SUMMARY_OFF_BRAND", "HIGHLIGHTS_TOO_GENERIC",
    "ITINERARY_STRUCTURE_WEAK", "SEO_TITLE_WEAK", "META_INCOMPLETE_SENTENCE",
    "DFS_INTENT_UNDERUSED", "KEYWORD_STUFFING_RISK", "GENERIC_AI_WORDING",
    "FACT_CHECK_MANUAL_CHECK",
]


def gate_brand_seo_audit(piece_body: str, brand_rubric_text: str) -> tuple[GateResult, dict | None]:
    """F9 brand/SEO audit — LLM, Nova Pro, cross-weight (same isolation
    guarantee as F8, see gate_framework() and judge_client.py). Caller
    supplies `brand_rubric_text` already fetched (this function does no DB
    I/O itself, same convention as gate_grounding() taking pre-fetched
    valid_ids/text_by_id) — real source is shared.tenant_brand_rules.
    Binary 1/0 fields, fixed failure-code vocabulary — never a free-text
    verdict that can't be tracked or trended. Returns (GateResult, audit_dict
    | None) — audit_dict is None only when the judge call itself failed."""
    contract = json.dumps({
        "status": "pass|flagged|manual_check",
        "brand_fit": "1|0", "human_read": "1|0", "seo_fit": "1|0",
        "trip_type_accuracy": "1|0", "publish_readiness": "1|0",
        "failure_codes": [f"subset of {BRAND_SEO_FAILURE_CODES}"],
        "notes": "str",
    }, indent=1)
    user_prompt = (
        f"PIECE:\n{piece_body}\n\n"
        f"BRAND RUBRIC:\n{brand_rubric_text}\n\n"
        "Audit in this order: product truth -> brand fit -> trip type -> highlights -> "
        "readability -> SEO -> publish readiness. Score every field 1 or 0. Use ONLY the "
        f"listed failure codes: {BRAND_SEO_FAILURE_CODES}. When uncertain about a factual "
        "claim: status=manual_check + FACT_CHECK_MANUAL_CHECK.\n\n"
        f"Output ONLY JSON matching this contract:\n{contract}"
    )
    try:
        raw = invoke_judge(_JUDGE_SYSTEM_PROMPT, user_prompt)
        data = parse_judge_json(raw["text"])
    except Exception as e:
        return GateResult(gate="F9_brand_seo_audit", passed=False,
                           violations=[f"judge unavailable: {e} — manual check"]), None

    status = data.get("status", "manual_check")
    failure_codes = [c for c in (data.get("failure_codes") or []) if c in BRAND_SEO_FAILURE_CODES]
    audit = {
        "status": status,
        "brand_fit": data.get("brand_fit"), "human_read": data.get("human_read"),
        "seo_fit": data.get("seo_fit"), "trip_type_accuracy": data.get("trip_type_accuracy"),
        "publish_readiness": data.get("publish_readiness"),
        "failure_codes": failure_codes, "notes": data.get("notes"),
    }
    passed = status == "pass"
    violations = []
    if not passed:
        reason = ", ".join(failure_codes) or audit.get("notes") or "(no reason given)"
        violations = [f"audit {status}: {reason}"]
    return GateResult(gate="F9_brand_seo_audit", passed=passed, violations=violations), audit


# ---------------------------------------------------------------- orchestration + repair budget (P0-3)

def run_gates(
    piece: Piece,
    gate_fns: list[Callable[[str], GateResult]],
    repair_fn: Callable[[str, list[str]], str],
    max_repairs: int = REPAIR_TOTAL_MAX,
) -> Piece:
    """P0-3 fix: after EVERY repair, re-run the ENTIRE gate stack, not just the
    gate that just failed. The aamc/gates.py bug this replaces re-checked only
    the single gate that had failed — a repair aimed at fixing gate 3 could
    silently re-break gate 1, and the old code would ship it because it never
    looked at gate 1 again. Each call to `repair_fn` still targets one gate's
    violations (the first failing gate found, in `gate_fns` order) — the fix
    is in what gets VALIDATED afterward, not in trying to fix everything at
    once. `piece.gate_ledger` after return is always the ledger from the
    round that decided the outcome (all-pass or held), not a stale one from a
    superseded gate."""
    while True:
        piece.gate_ledger = []
        first_failure: GateResult | None = None
        for gate_fn in gate_fns:
            result = gate_fn(piece.body_tagged)
            piece.gate_ledger.append(result)
            if not result.passed and first_failure is None:
                first_failure = result

        if first_failure is None:
            piece.status = "passed"
            return piece

        if piece.repair_count >= max_repairs:
            return _hold(piece, first_failure)

        piece.body_tagged = repair_fn(piece.body_tagged, first_failure.violations)
        piece.repair_count += 1


def _hold(piece: Piece, result: GateResult) -> Piece:
    """L6: hold VISIBLY with a concrete reason — never a silent gap."""
    piece.status = "held"
    piece.held_reason = f"{result.gate}: {'; '.join(result.violations[:3])}"
    return piece
