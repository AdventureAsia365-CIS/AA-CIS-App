"""
services.acp_produce.gates — MODULE F: N7 QA gate stack.

F1 grounding (AA-298 Phần A) · F2 banned patterns, F3 structural variance,
F4 brief compliance, F6 route-to-sellable, F7 FAQ dedup (AA-372) · F8
framework judge, F9 brand/SEO audit (blog) + F9 social (facebook/tiktok,
AA-372) — cross-weight LLM judges.

Numbering note: F2/F3/F4/F6/F7 follow AA-372's OWN renumbering (confirmed
against its Linear text, not the aamc/ prototype's F2=atom density/
F3=banned/F4=structural/F5=brief-compliance/F6=route/F7=faq scheme). Atom
density (the aamc prototype's original F2) is not part of this repo's gate
set — AA-372 does not ask for it, and it is not built here.

F1 ported from the aa-marketing-v2 research build's aamc/gates.py::
gate_grounding() with the P0-1 bug fixed during the port (ADR-2026-029)
rather than carrying it forward and patching it later — see
docs/implementation-notes/AA-298.md.

F2 (AA-372) folds in the fix for B12 (aamc/'s banned-pattern scan flagged
verbatim-cited atom/fact text as a false positive). AA-327 traced B12/B10 to
what THAT issue calls "F3" — AA-327 was written before AA-372's renumbering
and used the aamc scheme, where banned-patterns WAS F3; under AA-372's real
numbering both bugs belong to F2, not F3 (docs/implementation-notes/AA-372.md
§4 works through the citation trail). B10 (BrandRubric.compile_brand()
reading the wrong reject-list field) does not apply to F2 here — no
BrandRubric/compile_brand() subsystem exists in this repo (AA-327, Backlog)
for F2 to inherit the bug from; it just scans a hardcoded global lexicon.

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
from services.acp_produce.models import REPAIR_TOTAL_MAX, Brief, GateResult, Piece
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


# ---------------------------------------------------------------- F2 banned patterns (DET)

# Global AI-voice lexicon seed — ported verbatim from the aa-marketing-v2
# research build's aamc/config.py::BANNED_PATTERNS_SEED (that build's
# CONTEXT.md §1.6.2: "banned-pattern lexicon... seeded globally, extended by
# audit failures"). No tenant-extension mechanism here — that needs the
# brand-rubric-compiler subsystem (BrandRubric.compile_brand()), AA-327
# (Backlog), out of scope for this chunk.
BANNED_PATTERNS_SEED: list[str] = [
    r"\bnestled\b",
    r"\btapestry\b",
    r"\bhidden gem(s)?\b",
    r"\bmust[- ]visit\b",
    r"\bmust[- ]see\b",
    r"\bunforgettable\b",
    r"\bbreathtaking\b",
    r"\bbucket[- ]list\b",
    r"\bwhether you'?re .{3,40} or .{3,40}\b",
    r"\bin conclusion\b",
    r"\bembark on\b",
    r"\bawait(s)? you\b",
    r"\bimmerse yourself\b",
    r"\blook no further\b",
    r"\bdelve\b",
]

_BANNED_PATTERNS_COMPILED = [re.compile(p, re.IGNORECASE) for p in BANNED_PATTERNS_SEED]


def gate_banned_patterns(body_tagged: str, text_by_id: dict[str, str]) -> GateResult:
    """F2 banned patterns (DET). Scans `body_tagged` for the global AI-voice
    lexicon above. B12 fix folded into the port (see module docstring, not
    patched later): a match is EXEMPT only when the sentence it falls in
    carries a `[R:id]`/`[F:id]` citation AND the matched substring is itself
    present (case-insensitive) in that id's own source text — i.e. the
    phrase is genuinely quoted from the registry/atom, not AI-generated
    prose that happens to sit near a citation. `text_by_id` reuses
    gate_grounding()'s (F1) exact parameter shape — no new data plumbing.
    Same sentence-boundary heuristic as F1 (`_SENT_SPLIT_RE`)."""
    body = body_tagged or ""
    violations: list[str] = []

    for sent in _SENT_SPLIT_RE.split(body):
        cited_ids = TAG_RE.findall(sent)
        cited_texts = [text_by_id[c].lower() for c in cited_ids if c in text_by_id]
        for pattern in _BANNED_PATTERNS_COMPILED:
            for m in pattern.finditer(sent):
                phrase = m.group(0).lower()
                if cited_texts and any(phrase in t for t in cited_texts):
                    continue  # B12: genuinely verbatim-cited registry text, exempt
                violations.append(f"banned pattern /{pattern.pattern}/ -> '{m.group(0)}'")

    return GateResult(gate="F2_banned_patterns", passed=not violations, violations=violations)


# ---------------------------------------------------------------- F3 structural variance (DET)

def gate_structural_variance(body_tagged: str, channel: str) -> GateResult:
    """F3 structural variance (DET) — blog only (facebook/tiktok have their
    own short, template-driven shape from adapt.py's format instructions;
    the "no rhythm variance" AI-tell this gate targets is a long-form-article
    problem). Direct port of aamc/gates.py::gate_structural_variance() — no
    B10/B12 baggage here (see module docstring: both bugs trace to F2/
    banned-patterns despite AA-372's own text filing them under a stale "F3"
    label).

    Checks (each independent, all must pass): (1) at least one genuinely
    one-sentence paragraph exists (uniform paragraph length is an AI tell);
    (2) with >=3 H2 sections, the longest is notably longer (>=1.4x) than
    the second-longest (uniform section length is another AI-uniformity
    tell); (3) at most 1 bulleted list in the whole piece."""
    if channel != "blog":
        return GateResult(gate="F3_structural_variance", passed=True)

    body = body_tagged or ""
    violations: list[str] = []
    paras = [p for p in body.split("\n\n") if p.strip() and not p.startswith("#")]

    if not any(
        len(re.split(r"(?<=[.!?])\s+", p.strip())) == 1 and len(p.split()) >= 2
        for p in paras
    ):
        violations.append("no one-sentence paragraph found (variance rule)")

    sections = re.split(r"^## ", body, flags=re.MULTILINE)[1:]
    if len(sections) >= 3:
        lens = sorted(len(s.split()) for s in sections)
        if lens and lens[-1] < lens[-2] * 1.4:
            violations.append("no section is notably longer than the others")

    blocks = len([b for b in body.split("\n\n") if re.match(r"^\s*[-*] ", b)])
    if blocks > 1:
        violations.append(f"{blocks} bulleted lists — max 1 per article")

    return GateResult(gate="F3_structural_variance", passed=not violations, violations=violations)


# ---------------------------------------------------------------- F4 brief compliance (DET)

def gate_brief_compliance(body_tagged: str, channel: str, brief: Optional[Brief]) -> GateResult:
    """F4 brief compliance (DET) — blog only, ported from aamc/gates.py::
    gate_brief_compliance() against the real AA-369 `Brief` fields (keyword,
    required_h2s, word_range, internal_links — all exist as-is, no invented
    fields). `brief=None` FAILS CLOSED (L6: can't verify compliance against
    nothing, so don't silently pass) — unlike the channel branch, a real
    blog piece missing its Brief is a caller-contract bug worth surfacing,
    not a legitimate "nothing to check" state."""
    if channel != "blog":
        return GateResult(gate="F4_brief_compliance", passed=True)
    if brief is None:
        return GateResult(gate="F4_brief_compliance", passed=False,
                           violations=["no Brief available to check compliance against"])

    body = body_tagged or ""
    violations: list[str] = []

    if brief.keyword.lower() not in body.lower():
        violations.append(f"keyword '{brief.keyword}' absent from body")

    got_h2s = {h.strip().lower() for h in re.findall(r"^## (.+)$", body, re.MULTILINE)}
    for h in brief.required_h2s:
        if h.strip().lower() not in got_h2s:
            violations.append(f"required H2 missing: '{h}'")

    wc = len(TAG_RE.sub("", body).split())
    lo, hi = brief.word_range
    if not (lo * 0.7 <= wc <= hi * 1.3):
        violations.append(f"word count {wc} outside range {lo}-{hi} (+/-30%)")

    for link in brief.internal_links:
        if link and link not in body and link != brief.cta_target:
            violations.append(f"internal link not placed: {link}")

    return GateResult(gate="F4_brief_compliance", passed=not violations, violations=violations)


# ---------------------------------------------------------------- F6 route-to-sellable (DET)

def gate_route_to_sellable(
    body_tagged: str, channel: str, cta_target: Optional[str], url_alive: Optional[bool],
) -> GateResult:
    """F6 route-to-sellable (DET). Fail-closed by design (Nghiep, 06/08/2026):
    no `acp_deliver.tenant_tour_pages` row for this tour is treated the same
    as a confirmed-dead route — `url_alive` must be exactly `True`, not just
    not-`False`. No `manual_check`/soft status here — a route-to-sellable
    failure blocks `publish_mode` past `propose_only` (`packets.py::
    set_publish_mode()`'s `ALLOWED_PUBLISH_MODES_UNTIL_F6` guard), it does
    not create a review queue outside the defined HITL gates.

    `cta_target`/`url_alive` are pre-fetched by the caller (same convention
    as F9's `brand_rubric_text` and F1's `text_by_id` — this gate does no DB
    I/O itself). The literal-CTA-in-body sub-check is blog-only: FB/TikTok
    captions reference the trip conversationally, never embedding a literal
    URL (confirmed against adapt.py's real output format)."""
    violations: list[str] = []

    if not cta_target:
        violations.append("no CTA target -- a beautiful dead-end is a failure")
    if url_alive is not True:
        violations.append(
            "route-to-sellable not confirmed alive (no acp_deliver.tenant_tour_pages row, "
            "or url_alive is not True) -- fail-closed, never a silent/manual_check pass"
        )
    if channel == "blog" and cta_target and cta_target not in (body_tagged or ""):
        violations.append(f"CTA {cta_target} not present in body")

    return GateResult(gate="F6_route_to_sellable", passed=not violations, violations=violations)


# ---------------------------------------------------------------- F7 FAQ dedup (DET, intra-piece)

_FAQ_ANSWER_RE = re.compile(r"\*\*Q: .*?\*\*\s*\nA: (.*?)(?=\n\*\*Q: |\Z)", re.DOTALL)
_FAQ_TOKEN_RE = re.compile(r"[a-z]{5,}")
_FAQ_DEDUP_THRESHOLD = 0.85  # ported from aamc/gates.py::gate_faq_dedup()


def gate_faq_dedup(body_tagged: str) -> GateResult:
    """F7 FAQ dedup (DET) — INTRA-piece only for this chunk
    (docs/implementation-notes/AA-372.md §8): does a FAQ answer just restate
    a body paragraph within the SAME piece? Cross-time dedup against
    previously-published FAQs for the same tour/slot needs a new table that
    does not exist yet (`faq.py` confirms `Piece.faq_items`/`faq_jsonld` are
    Pydantic-only) — flagged as a follow-up, not built here.

    Matches the REAL AA-371 FAQ section format (`faq.py::render_faq_section()`
    — `"## FAQ"` then `"**Q: ...**"` / `"A: ..."` pairs), not the aamc
    prototype's different markdown shape. No-op (passed=True) when the piece
    has no FAQ section at all."""
    body = body_tagged or ""
    if "## FAQ" not in body:
        return GateResult(gate="F7_faq_dedup", passed=True)

    pre, _, faq = body.partition("## FAQ")
    pre_tokens = set(_FAQ_TOKEN_RE.findall(pre.lower()))

    violations: list[str] = []
    for i, m in enumerate(_FAQ_ANSWER_RE.finditer(faq)):
        answer = m.group(1).strip()
        answer_tokens = set(_FAQ_TOKEN_RE.findall(answer.lower()))
        if answer_tokens and len(answer_tokens & pre_tokens) / len(answer_tokens) > _FAQ_DEDUP_THRESHOLD:
            violations.append(
                f"FAQ answer {i + 1} restates a body paragraph -- cut or add a detail the body lacks"
            )

    return GateResult(gate="F7_faq_dedup", passed=not violations, violations=violations)


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


# ---------------------------------------------------------------- F9 social (LLM rubric, AA-372)

# Separate, minimal fixed vocabulary from BRAND_SEO_FAILURE_CODES (blog) —
# kept append-only-per-domain rather than merged, so a future N8 flywheel
# dashboard querying blog failure codes doesn't have to filter out
# social-only codes that never apply to blog pieces, and vice versa.
SOCIAL_SEO_FAILURE_CODES = [
    "SUMMARY_OFF_BRAND", "CTA_MISSING_OR_WEAK", "HOOK_WEAK",
    "GENERIC_AI_WORDING", "FACT_CHECK_MANUAL_CHECK",
]

_SOCIAL_RUBRIC_FIELDS: dict[str, list[str]] = {
    "facebook": ["brand_fit", "cta_clear", "human_read"],
    "tiktok": ["hook_strength", "cta_clear"],
}


def gate_brand_seo_audit_social(
    piece_body: str, channel: str, brand_rubric_text: str,
) -> tuple[GateResult, Optional[dict]]:
    """F9 social (LLM, cross-weight, AA-372) — minimal per-channel rubric,
    NOT a parameterization of gate_brand_seo_audit() (blog). Decided
    06/08/2026 (option b of AA-372's open question, resolved outside Linear):
    2-3 criteria per channel, because no real FB/TikTok piece has run
    through F8/F9 yet to know what it actually needs (Mistake-to-Rule,
    ADR-2026-009 — extend from real failures, don't guess the full
    blog-shaped rubric ahead of data). Banned-pattern policing is
    deliberately excluded here — that's F2's job (deterministic, cheaper,
    more consistent than asking an LLM to also police brand-voice red
    lines).

    Facebook (3 fields): brand_fit, cta_clear (single unambiguous action,
    not a vague sign-off), human_read (reads like a person, not templated AI
    copy). TikTok (2 fields): hook_strength (the HOOK line would stop a
    scroll in the first second), cta_clear (SCRIPT ends with an actual call
    to action, not just a fact). Same isolation guarantee, `status`/
    manual_check convention, and judge call as gate_brand_seo_audit()."""
    fields = _SOCIAL_RUBRIC_FIELDS.get(channel)
    if fields is None:
        raise ValueError(f"gate_brand_seo_audit_social() has no rubric for channel={channel!r}")

    contract = json.dumps({
        "status": "pass|flagged|manual_check",
        **{f: "1|0" for f in fields},
        "failure_codes": [f"subset of {SOCIAL_SEO_FAILURE_CODES}"],
        "notes": "str",
    }, indent=1)
    user_prompt = (
        f"PIECE ({channel}):\n{piece_body}\n\n"
        f"BRAND RUBRIC:\n{brand_rubric_text}\n\n"
        "Score every field 1 or 0. Use ONLY the listed failure codes: "
        f"{SOCIAL_SEO_FAILURE_CODES}. When uncertain about a factual claim: "
        "status=manual_check + FACT_CHECK_MANUAL_CHECK.\n\n"
        f"Output ONLY JSON matching this contract:\n{contract}"
    )
    try:
        raw = invoke_judge(_JUDGE_SYSTEM_PROMPT, user_prompt)
        data = parse_judge_json(raw["text"])
    except Exception as e:
        return GateResult(gate="F9_brand_seo_audit_social", passed=False,
                           violations=[f"judge unavailable: {e} -- manual check"]), None

    status = data.get("status", "manual_check")
    failure_codes = [c for c in (data.get("failure_codes") or []) if c in SOCIAL_SEO_FAILURE_CODES]
    audit = {
        "status": status, "channel": channel,
        **{f: data.get(f) for f in fields},
        "failure_codes": failure_codes, "notes": data.get("notes"),
    }
    passed = status == "pass"
    violations = []
    if not passed:
        reason = ", ".join(failure_codes) or audit.get("notes") or "(no reason given)"
        violations = [f"audit {status}: {reason}"]
    return GateResult(gate="F9_brand_seo_audit_social", passed=passed, violations=violations), audit


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
