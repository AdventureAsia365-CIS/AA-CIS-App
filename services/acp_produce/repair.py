"""
services.acp_produce.repair — N7 E5 (Repair), AA-376.

Ported from the aa-marketing-v2 research build's aamc/generation.py::repair()
(docs/implementation-notes/AA-376.md STEP 0 confirmed this is real prior art,
not a fresh design) with the same behavior contract: fix ONLY the listed
violations, preserve structure/voice/length, return the full corrected
`body_tagged` — never a diff/patch, never a partial section. One function
handles every gate's violations (F1-F9 alike) — the prototype's own
`run_gates()` never split repair by gate either, it always called the same
`repair()` regardless of which gate failed.

Wiring (AA-376): this is the `repair_fn: Callable[[str, list[str]], str]`
`run_gates()` (gates.py) has accepted in its signature since AA-298/P0-3 but
never had a real implementation for — `pipeline.py` previously passed
`_repair_not_available()` with `max_repairs=0`, so this path was never
reachable (see pipeline.py's pre-AA-376 docstring in git history). Model is
Bedrock satellite acc3 Sonnet (AA-397, acc1 fallback under it), same
`invoke_claude(..., model="sonnet")` call as E2/E3 (generation.py/adapt.py) —
CHỐT per AA-334 (Palmyra Cancelled, see
generation.py's own docstring). Palmyra must never appear anywhere in this
module.

Not repaired here (caller's job — see gates.py::run_gates()'s `is_repairable`
filter, AA-376): a violation that isn't fixable by editing `body_tagged` at
all (F6's "no cta_target"/"url_alive not True" — external DB/caller-supplied
state, not content) must never reach this function — `run_gates()` filters
those out and holds immediately instead of wasting a repair round + a Sonnet
call on a violation this module cannot possibly fix by rewriting text.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog

from services.acp_produce.atom_usage import ATOM_CITE_RE
from services.content_generation.brand_standards import AA_BRAND_IDENTITY_PROMPT
from shared.llm_client.bedrock_satellite import BedrockUnavailable, invoke_claude

logger = structlog.get_logger()

# Brand-mandated CTA phrase (also gates.py::_CTA_PHRASE_RE, adapt.py's
# _FACEBOOK_INSTRUCTIONS, AA_BRAND_IDENTITY_PROMPT's own "CTA:" line — this
# repo has no single shared constant for it yet; each module that needs the
# literal string already carries its own copy, this is one more, not a new
# duplication pattern).
_CTA_PHRASE = "Design This Journey"

_MAX_INVOKE_ATTEMPTS = 3  # same retry policy as E2/E3 (generation.py/adapt.py)
_RETRY_BACKOFF_SECONDS = 2.0
# Repair returns the FULL piece body (not a batch/section) — same ceiling as
# the project-wide "max_tokens = 4096, NOT 2000" rule (JSON-truncation fix).
_MAX_TOKENS = 4096

_REPAIR_SYSTEM_PROMPT = (
    "You are repairing an ALREADY-WRITTEN piece that failed a QA check.\n\n"
    + AA_BRAND_IDENTITY_PROMPT.strip() +
    "\n\nHARD RULES FOR THIS REPAIR TASK:\n"
    "- Fix ONLY the violations listed below. Do not rewrite anything else.\n"
    "- Preserve the existing structure, voice, and length as closely as possible.\n"
    "- Preserve every [R:atom_id]/[F:fact_id] provenance tag exactly as given, unless a\n"
    "  violation specifically requires removing or changing one.\n"
    "- Any NEW prose you write to fix a violation must still avoid every word in the\n"
    "  FORBIDDEN language list above — fixing one gate's violation must never reintroduce a\n"
    "  banned word into content that was already clean before this repair round (AA-404: this\n"
    "  is the exact mechanism behind the real F4-repair -> F2-regression cases).\n"
    "- Output ONLY the full repaired text, same format as the input — no commentary, no\n"
    "  explanation, no markdown fence.\n"
)


# AA-396 (piece-7 class): a real Sonnet repair call, confused by the
# BRAND_SEO_FAILURE_CODES naming collision with the S1 pipeline's real DB
# fields (see gates.py's own AA-396 comment), returned its own chain-of-
# thought about why it couldn't act ("Looking at the violations, I need to
# identify... The current text is a summary/editorial piece — it does not
# contain discrete AA_HIGHLIGHTS... which means they cannot be repaired
# within this document as written.") instead of a repaired body, and that
# text got PERSISTED as the piece's real content. Narrow, evidence-based
# guard: only checked against the first paragraph (real leaks precede the
# actual repaired content, this one did) and only for phrases that are
# self-referential about the repair task itself — not any use of words like
# "violations" or "structure" a legitimate travel article might contain
# deeper in the body.
_LEAK_SIGNAL_RE = re.compile(
    r"\b(the violations?(\s+to\s+fix)?|cannot be repaired|i need to identify|"
    r"the current text is (a|an)\b|does not contain discrete|re-reading carefully)\b",
    re.IGNORECASE,
)


def _looks_like_leaked_reasoning(text: str) -> bool:
    """AA-396: does `text` open with repair's own meta-commentary about the
    repair task, rather than actual repaired content? Checked only against
    the first paragraph/prefix on purpose — narrows the guard to the exact
    corruption shape observed in real data (leak precedes the real content)
    instead of scanning the whole body, which would risk false-flagging
    legitimate prose that later discusses e.g. itinerary structure."""
    prefix = text.split("\n\n", 1)[0][:500]
    return bool(_LEAK_SIGNAL_RE.search(prefix))


@dataclass
class PieceInvariants:
    """AA-404 (STEP 0 "mở rộng" repair.py blind spot survey,
    docs/implementation-notes/AA-404.md §"repair.py::_build_prompt()"):
    piece-wide constraints that generation (E1-E3: generation.py/adapt.py)
    already decided for THIS piece and that must survive every repair round
    below, regardless of which gate's violations triggered that round.
    `repair_piece()` previously received only `(body_tagged, violations)` —
    the first failing gate's own narrow view — with zero visibility into any
    OTHER gate's structural requirements, which is exactly why a repair
    aimed at gate X could silently regress gate Y (confirmed real: 14
    regression events / 13 pieces across 4 causal pairs, see the doc above).

    All fields are optional/default-off so a piece with no applicable
    invariant (most non-blog, non-hook_story_cta pieces) produces an empty
    structural-context block — `_build_prompt()` never fabricates a
    constraint that generation didn't actually set.

    Every field here is either a direct `Brief` pass-through or re-derived
    from a pure function generation.py/adapt.py already export
    (`build_outline`/`_select_variance_owners`) — no new state storage, no
    new `Piece`/DB field, per the doc's own recommendation. The single
    exception, `single_atom_required`, is a flag only: the actual atom id(s)
    to preserve are re-derived fresh from the CURRENT `body_tagged` at
    prompt-build time (see `_currently_cited_atom_ids()`), so it stays
    correct even after an earlier repair round in the same loop already
    touched the body — a stored id could go stale, a re-derived one can't."""

    channel: str = "blog"
    # F3_structural_variance (blog only, AA-404 Part 1): the two section
    # titles generation.py::_select_variance_owners() assigned as the ONE
    # long section / ONE short-single-sentence-paragraph owner. Real
    # regression: F4-repair (adding/restructuring an H2) broke this 3x by
    # rewriting section content with no awareness of which section was
    # supposed to stay short vs. run long.
    long_section_title: Optional[str] = None
    short_para_section_title: Optional[str] = None
    # F4_brief_compliance (blog only): Brief.required_h2s, direct pass-
    # through, minus the synthetic "FAQ" entry (E4's job, never E2's). Real
    # regression: F9-repair (blog brand/SEO rewrite) broke this 3x by
    # silently dropping/renaming a required heading.
    required_h2s: list[str] = field(default_factory=list)
    # F8_framework hook_story_cta (facebook, AA-404 Part 2): True forces
    # repair to keep the piece citing only the atom id(s) already present in
    # the CURRENT body — the single-atom ceiling adapt.py's
    # _select_atoms_for_channel() enforces at generation time has no
    # equivalent enforcement once repair starts rewriting.
    single_atom_required: bool = False
    # F8_framework hook_story_cta (facebook): True when this piece's
    # framework requires the literal brand CTA phrase as its closing
    # sentence (gates.py::_ends_with_cta(), a deterministic check). Real
    # regression: F9-social-repair broke this 6x — the single dominant
    # pattern in the whole dataset (9/14 events came from an F9 variant).
    cta_required: bool = False
    cta_phrase: str = _CTA_PHRASE
    # F8_framework AIDA (blog, AA-404 Part 3): same class of gap as F3's —
    # which OutlineSection is first/last in the outline, for the opening-
    # hook/closing-single-CTA notes generation.py's E2 prompt gives them.
    # Not yet observed regressing in real data (only 1 real AIDA failure so
    # far, not preceded by an unrelated repair round) but structurally
    # identical exposure to F3's confirmed 3x — included so it doesn't need
    # its own follow-up patch once real data eventually exercises it.
    aida_opening_section_title: Optional[str] = None
    aida_closing_section_title: Optional[str] = None


def _currently_cited_atom_ids(body_tagged: str) -> list[str]:
    """Unique `[R:atom_id]` ids in `body_tagged`, first-seen order — same
    regex (`atom_usage.ATOM_CITE_RE`) and same first-seen-order convention as
    `atom_usage.py::atom_ids_cited()`, reimplemented against a bare string
    here rather than a `Piece` (that function requires one; repair only ever
    has the current body string mid-round, not a `Piece` to construct)."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for atom_id in ATOM_CITE_RE.findall(body_tagged or ""):
        if atom_id not in seen_set:
            seen_set.add(atom_id)
            seen.append(atom_id)
    return seen


def _build_structural_context(body_tagged: str, invariants: Optional[PieceInvariants]) -> str:
    """AA-404: the "STRUCTURAL CONTEXT TO PRESERVE" block — every invariant
    line here is conditional on `invariants` actually carrying that field,
    so a piece with no applicable constraint (e.g. a tiktok piece, which has
    no single-atom ceiling and no CTA-phrase requirement) gets no
    fabricated guidance. Returns "" when nothing applies, so
    `_build_prompt()` can splice this in unconditionally."""
    if invariants is None:
        return ""
    lines: list[str] = []

    if invariants.long_section_title:
        lines.append(
            f'- The "## {invariants.long_section_title}" section was deliberately written to run '
            "notably longer than the others (structural-variance rule). If you are not fixing that "
            "section, leave its length alone — do not shrink it, and do not grow any OTHER section "
            "to rival it."
        )
    if invariants.short_para_section_title:
        lines.append(
            f'- The "## {invariants.short_para_section_title}" section carries the piece\'s one '
            "required short, single-sentence standalone paragraph (structural-variance rule). If "
            "you are not fixing that section, leave that short paragraph exactly as it is."
        )
    if invariants.required_h2s:
        headings = ", ".join(f'"{h}"' for h in invariants.required_h2s)
        lines.append(
            f"- This piece's required section headings are: {headings}. Never remove, rename, or "
            "merge any of these while fixing a violation from a different gate."
        )
    if invariants.single_atom_required:
        cited = _currently_cited_atom_ids(body_tagged)
        if cited:
            ids = ", ".join(f"[R:{aid}]" for aid in cited)
            lines.append(
                f"- This is a single-atom piece: it must cite ONLY {ids} (already in the text "
                "above) — never add a citation to any other atom id, even while fixing a violation "
                "that has nothing to do with citations."
            )
    if invariants.cta_required:
        lines.append(
            f'- This piece\'s format REQUIRES ending on the exact brand CTA phrase "'
            f'{invariants.cta_phrase}" as its final sentence. Even when fixing a violation that '
            "isn't about the CTA, do not let that fix remove, move, or bump the CTA out of the "
            "final position."
        )
    if invariants.aida_opening_section_title:
        lines.append(
            f'- The "## {invariants.aida_opening_section_title}" section is this piece\'s OPENING '
            "(AIDA framework) — it must open on a genuine attention hook. Don't let a fix for an "
            "unrelated violation replace that opening with generic scene-setting."
        )
    if invariants.aida_closing_section_title:
        lines.append(
            f'- The "## {invariants.aida_closing_section_title}" section is this piece\'s CLOSING '
            "(AIDA framework) — it must end on exactly ONE clear call to action. Don't introduce a "
            "second CTA or remove the existing one while fixing an unrelated violation."
        )

    if not lines:
        return ""
    return (
        "STRUCTURAL CONTEXT TO PRESERVE (regardless of which violation above you're fixing — these "
        "were decided when the piece was first written and must survive every repair round):\n"
        + "\n".join(lines)
    )


# AA-404 STEP 0 §"repair.py::_build_prompt()": the brand block already
# mentions the CTA phrase once (AA_BRAND_IDENTITY_PROMPT's "CTA:" line,
# already in every repair call's system prompt) yet real facebook pieces
# still failed to add it across 4 repair rounds — the terse violation string
# ("framework criterion failed: ends with CTA") never connects to that
# one-line brand fact elsewhere in context. This lookup is unconditional
# (not gated on `invariants`) because the violation text itself only ever
# appears for hook_story_cta pieces (gates.py::_ends_with_cta(), the only
# gate check that emits it) — a defense-in-depth match on top of the
# `cta_required` structural-context line above, not a replacement for it.
_VIOLATION_HINTS: tuple[tuple[str, str], ...] = (
    (
        "ends with cta",
        'HINT for the "ends with CTA" violation: the exact required phrase is "{cta_phrase}" — it '
        "must be the piece's final sentence, written as natural prose (never \"Book Now\", never a "
        "bare link or markdown), not merely present somewhere earlier in the text.",
    ),
)


def _violation_hints(violations: list[str], cta_phrase: str) -> list[str]:
    hints = []
    for v in violations:
        v_lower = v.lower()
        for needle, hint_template in _VIOLATION_HINTS:
            if needle in v_lower:
                hints.append(hint_template.format(cta_phrase=cta_phrase))
    return hints


class RepairFailed(Exception):
    """E5 could not produce a repaired body — Sonnet invoke kept failing
    after retries. Raised so the caller (`gates.py::run_gates()`) can hold
    the piece immediately rather than silently returning the unrepaired body
    or crashing the whole slot-production run (L6: hold visible, never
    silent — same spirit as DraftGenerationFailed/AdaptChannelFailed/
    FAQAnswerFailed)."""


def repair_piece(body_tagged: str, violations: list[str], *, invariants: Optional[PieceInvariants] = None) -> str:
    """E5. Matches the `Callable[[str, list[str]], str]` contract
    `run_gates()` (gates.py) requires for its `repair_fn` parameter: given
    the current `body_tagged` and the violations list from the first failing
    gate, returns the full repaired text. Raises `RepairFailed` after
    `_MAX_INVOKE_ATTEMPTS` failed Sonnet invokes — never returns a
    fabricated or partial repair.

    `invariants` (AA-404, keyword-only, defaults to `None`): optional
    piece-wide constraints from generation time (see `PieceInvariants`) that
    get folded into the prompt regardless of which gate's violations this
    round is fixing. `None` (every caller/test before this change, and
    `run_gates()`'s own bare `Callable[[str, list[str]], str]` contract)
    reproduces the exact pre-AA-404 prompt shape — this parameter is
    strictly additive."""
    prompt = _build_prompt(body_tagged, violations, invariants)
    last_err: BedrockUnavailable | None = None
    for attempt in range(1, _MAX_INVOKE_ATTEMPTS + 1):
        try:
            result = invoke_claude(
                prompt, model="sonnet", max_tokens=_MAX_TOKENS, system=_REPAIR_SYSTEM_PROMPT, account="acc3"
            )
        except BedrockUnavailable as e:
            last_err = e
            logger.warning("e5_repair_sonnet_retry", attempt=attempt,
                            max_attempts=_MAX_INVOKE_ATTEMPTS, error=str(e))
            if attempt < _MAX_INVOKE_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
            continue

        repaired = result.text.strip()
        if _looks_like_leaked_reasoning(repaired):
            logger.warning("e5_repair_leaked_reasoning_rejected", violations=violations,
                            prefix=repaired[:200])
            raise RepairFailed(
                "repair output failed sanity check -- looks like leaked reasoning about the "
                "repair task itself (AA-396 piece-7 class), not repaired content"
            )

        logger.info("e5_repair_success", model_used=result.model_used,
                     latency_ms=result.latency_ms, usage=result.usage, violations=violations)
        return repaired

    raise RepairFailed(
        f"Sonnet invoke failed after {_MAX_INVOKE_ATTEMPTS} attempts: {last_err}"
    ) from last_err


def _build_prompt(body_tagged: str, violations: list[str], invariants: Optional[PieceInvariants] = None) -> str:
    cta_phrase = invariants.cta_phrase if invariants is not None else _CTA_PHRASE
    parts = [
        "CURRENT TEXT:\n" + body_tagged + "\n\n"
        "VIOLATIONS TO FIX (fix ONLY these, nothing else):\n- " + "\n- ".join(violations)
    ]

    hints = _violation_hints(violations, cta_phrase)
    if hints:
        parts.append("\n\n" + "\n".join(hints))

    structural_context = _build_structural_context(body_tagged, invariants)
    if structural_context:
        parts.append("\n\n" + structural_context)

    return "".join(parts)


__all__ = ["repair_piece", "RepairFailed", "PieceInvariants"]
