"""
services.acp_produce.generation — N7 E1 (Outline) + E2 (Draft), AA-370.

STEP 0 (Linear AA-370 comment, 06/08/2026) confirmed the design executed here:
- E1 (`build_outline`) is fully deterministic — no LLM. `Brief.required_h2s`
  + `Brief.atoms_by_section` (both already built by AA-369's
  `research.py::compile_brief()`) are sufficient; the per-section "goal" is a
  template string, never generated text.
- E2 (`generate_draft`) is the one real LLM writer call in N7 Produce. Model
  is Bedrock satellite acc1 Sonnet (`shared/llm_client/bedrock_satellite.py`,
  `model="sonnet"`) — CHỐT, not a proposal: AA-334 (bake-off issue) was
  Cancelled 06/08/2026 with an explicit sign-off ("Nghiep xác nhận trực
  tiếp: Palmyra X5 không dùng được ... chuyển thẳng sang Bedrock satellite
  acc1 Sonnet, không qua bake-off"). Palmyra must never appear anywhere in
  this module.
- Sections are drafted in batches of 2-3 (never one call for the whole
  piece) — the same lesson AA-353/AA-357 already applied to S1's itinerary
  generation ("tránh lặp lại lỗi kiến trúc compression"). H2 headings are
  inserted by CODE from the outline, never written by the model — mirrors
  AA-353's "day-title formatting no longer trusted to the model".
- Every factual claim gets a `[R:atom_id]` tag. `[F:fact_id]` is
  deliberately NOT offered to the model — `Brief.facts_ids` is always empty
  (no Facts pack exists anywhere in this repo, AA-369 scope note) so the tag
  would have nothing real to reference.

This module intentionally reuses `services.content_generation.brand_standards
.AA_BRAND_IDENTITY_PROMPT` (S1's real brand rubric) instead of inventing a
second brand-voice text that could drift from it.

`generation.py` is the name every existing forward-reference in this package
already anticipates (`judge_client.py`, `pipeline.py`, `reliability.py`,
`sweeper_lambda.py`, `packets.py`, `rule_adapter.py` docstrings all say
"E1-E5 generation" / name this file directly) — not a new naming choice.

Wiring into the rest of N7 Produce (AA-364): `generate_draft()` returns a
plain `str` — the caller assigns it straight to `Piece(piece_id=...,
body_tagged=that_str)` and passes the `Piece` to
`pipeline.py::run_piece_through_produce_gates()` exactly like every existing
test already hand-constructs. No change needed anywhere else in the package.
`atom_text_by_id` (the same `dict[str, str]` this module takes as input) is
also exactly the shape `run_piece_through_produce_gates(text_by_id=...)`
wants, and `set(atom_text_by_id)` is its `valid_ids` — confirmed compatible
with `gates.py::gate_grounding()`'s `TAG_RE` in AA-370 STEP 0, no format gap.
"""
from __future__ import annotations

import re
import time
from typing import Optional

import structlog

from services.acp_produce.models import Brief, OutlineSection
from services.content_generation.brand_standards import AA_BRAND_IDENTITY_PROMPT
from shared.llm_client.bedrock_satellite import BedrockInvokeResult, BedrockUnavailable, invoke_claude

logger = structlog.get_logger()

_TARGET_BATCH_SIZE = 3  # sections/call — "batch 2-3 section/call", never 1-call-whole-piece
_MAX_INVOKE_ATTEMPTS = 3  # 1 original + 2 retries, per AA-370 IMPLEMENT scope
_RETRY_BACKOFF_SECONDS = 2.0
_MIN_MAX_TOKENS = 512
_MAX_MAX_TOKENS = 4096  # same ceiling as the JSON-truncation fix elsewhere in this repo

_SECTION_MARKER_RE = re.compile(r"===SECTION:.*?===\s*\n", re.MULTILINE)

_DRAFT_SYSTEM_PROMPT = (
    "You are the Adventure Asia content writer for N7 (blog/social) pieces.\n\n"
    + AA_BRAND_IDENTITY_PROMPT.strip() +
    "\n\nADDITIONAL RULES FOR THIS DRAFT TASK:\n"
    "- You will be given one or more sections to write. For EACH section, output a line\n"
    "  \"===SECTION:<title>===\" followed by that section's body prose — nothing else on\n"
    "  that line, and output the sections in the exact order given.\n"
    "- Do NOT write the section heading/H2 as prose — the marker line above is enough,\n"
    "  the reader-facing heading is inserted separately by code from the outline.\n"
    "- Every factual claim MUST carry a [R:atom_id] tag citing the exact atom id supplied\n"
    "  for that section. Never invent an atom id. Never state a fact with no cited atom.\n"
    "- Do NOT use [F:...] tags anywhere — no Facts pack exists for this brief.\n"
    "- If a section lists no atoms, write no factual claims in it — keep it brief and\n"
    "  transitional (e.g. a bridge into the next section), not padded with invented detail."
)


class DraftGenerationFailed(Exception):
    """E2 could not produce a real draft for one batch — Sonnet invoke kept
    failing after retries, or its response didn't parse into one body per
    requested section. Raised with a concrete reason (never a silently empty
    or fabricated section) — caller (the not-yet-built slot runner) is
    expected to log this to unknown_ledger and skip the slot, same "hold
    visible, never silent" spirit as gates.py's F1-F9 (L6)."""


# ---------------------------------------------------------------- E1 outline (deterministic, no LLM)

def build_outline(brief: Brief) -> list[OutlineSection]:
    """E1. One OutlineSection per `brief.required_h2s` entry, atom_ids read
    straight off `brief.atoms_by_section`. Calls no LLM — verified by this
    function not importing/calling `invoke_claude` at all.

    Skips the literal "FAQ" title (research.py::compile_brief() appends it
    when `fw_cfg.get("faq")`) — AA-371 (E4, faq.py) owns that section
    entirely now, answering `Brief.faq_candidates` with real grounded
    answers instead of E2 drafting a generic throwaway paragraph off
    whatever atoms `atoms_by_section["FAQ"]` happened to collect (AA-370's
    original behavior, before E4 existed to do this properly). `required_h2s`
    always appends "FAQ" last (research.py line ~282), so E4 appending its
    rendered FAQ block to the end of `body_tagged` reproduces the same
    position this section would have occupied."""
    sections: list[OutlineSection] = []
    for title in brief.required_h2s:
        if title == "FAQ":
            continue
        atom_ids = brief.atoms_by_section.get(title, [])
        sections.append(OutlineSection(title=title, atom_ids=atom_ids, goal=_section_goal(title, atom_ids)))
    return sections


def _section_goal(title: str, atom_ids: list[str]) -> str:
    n = len(atom_ids)
    if n == 0:
        return f"No atoms assigned to '{title}' — keep brief/transitional, no factual claims."
    return f"Cover {n} supporting fact{'s' if n != 1 else ''} for '{title}'."


# ---------------------------------------------------------------- E2 draft (Sonnet, batched)

def generate_draft(brief: Brief, outline: list[OutlineSection], atom_text_by_id: dict[str, str]) -> str:
    """E2. Drafts `outline` in batches of 2-3 sections/Sonnet call, inserts
    H2 headings from the outline (code, never the model), and joins the
    result into one `body_tagged` string in outline order. Raises
    `DraftGenerationFailed` rather than ever emitting an empty/fabricated
    section."""
    if not outline:
        raise ValueError("generate_draft() requires a non-empty outline — run build_outline() first")

    words_mid = sum(brief.word_range) // 2
    words_per_section = max(words_mid // len(outline), 100)

    section_bodies: dict[str, str] = {}
    for batch in _batch_sections(outline):
        prompt = _build_batch_prompt(brief, batch, atom_text_by_id)
        max_tokens = min(max(int(words_per_section * len(batch) * 1.6) + 150, _MIN_MAX_TOKENS), _MAX_MAX_TOKENS)

        result = _invoke_sonnet_with_retry(prompt, max_tokens)
        logger.info(
            "e2_draft_batch_success", model_used=result.model_used,
            sections=[s.title for s in batch], latency_ms=result.latency_ms, usage=result.usage,
        )

        parsed = _parse_batch_response(result.text, batch)
        if len(parsed) != len(batch):
            raise DraftGenerationFailed(
                f"Sonnet response for batch {[s.title for s in batch]} did not contain "
                f"{len(batch)} parseable ===SECTION:...=== block(s) (got {len(parsed)})"
            )
        section_bodies.update(parsed)

    return "\n\n".join(f"## {s.title}\n\n{section_bodies[s.title]}" for s in outline)


def _batch_sections(sections: list[OutlineSection], target: int = _TARGET_BATCH_SIZE) -> list[list[OutlineSection]]:
    """Balanced chunking so every batch lands in [2,3] whenever the total
    allows it (e.g. 5 sections -> [3,2], not [3,3,-1] or a trailing [1])."""
    n = len(sections)
    if n == 0:
        return []
    num_batches = -(-n // target)  # ceil
    base, extra = divmod(n, num_batches)
    batches, i = [], 0
    for b in range(num_batches):
        size = base + (1 if b < extra else 0)
        batches.append(sections[i:i + size])
        i += size
    return batches


def _build_batch_prompt(brief: Brief, batch: list[OutlineSection], atom_text_by_id: dict[str, str]) -> str:
    lines = [
        f"KEYWORD: {brief.keyword}",
        f"FRAMEWORK: {brief.framework}",
        f"CTA TARGET: {brief.cta_target}",
        "VARIANCE DIRECTIVES (apply across the whole piece): " + "; ".join(brief.variance_directives),
        "",
        "Write the body prose for these sections, in order:",
    ]
    for s in batch:
        lines.append(f"\nSECTION: {s.title}")
        lines.append(f"GOAL: {s.goal}")
        if s.atom_ids:
            lines.append("ATOMS (cite each factual claim with [R:atom_id]):")
            lines += [f"- {aid}: {atom_text_by_id.get(aid, '')}" for aid in s.atom_ids]
        else:
            lines.append("ATOMS: (none assigned — no factual claims in this section)")
    return "\n".join(lines)


def _invoke_sonnet_with_retry(prompt: str, max_tokens: int) -> BedrockInvokeResult:
    last_err: Optional[BedrockUnavailable] = None
    for attempt in range(1, _MAX_INVOKE_ATTEMPTS + 1):
        try:
            return invoke_claude(prompt, model="sonnet", max_tokens=max_tokens, system=_DRAFT_SYSTEM_PROMPT)
        except BedrockUnavailable as e:
            last_err = e
            logger.warning("e2_draft_sonnet_retry", attempt=attempt, max_attempts=_MAX_INVOKE_ATTEMPTS, error=str(e))
            if attempt < _MAX_INVOKE_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
    raise DraftGenerationFailed(
        f"Sonnet invoke failed after {_MAX_INVOKE_ATTEMPTS} attempts: {last_err}"
    ) from last_err


def _parse_batch_response(raw_text: str, batch: list[OutlineSection]) -> dict[str, str]:
    """Splits on `===SECTION:...===` markers and maps chunk i -> batch[i].title
    POSITIONALLY (not by matching the marker's own title text) — same
    defensive-fallback shape as AA-353's day-number mismatch handling
    ("positional fallback ... simple and good enough"). Returns {} (a
    parse failure, handled by the caller) if the marker count doesn't match
    the requested section count — never guesses a partial mapping."""
    markers = list(_SECTION_MARKER_RE.finditer(raw_text))
    if len(markers) != len(batch):
        return {}
    bodies = {}
    for i, m in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(raw_text)
        bodies[batch[i].title] = raw_text[m.end():end].strip()
    return bodies


__all__ = ["build_outline", "generate_draft", "DraftGenerationFailed"]
