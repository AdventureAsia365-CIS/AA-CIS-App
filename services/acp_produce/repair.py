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

import structlog

from services.content_generation.brand_standards import AA_BRAND_IDENTITY_PROMPT
from shared.llm_client.bedrock_satellite import BedrockUnavailable, invoke_claude

logger = structlog.get_logger()

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


class RepairFailed(Exception):
    """E5 could not produce a repaired body — Sonnet invoke kept failing
    after retries. Raised so the caller (`gates.py::run_gates()`) can hold
    the piece immediately rather than silently returning the unrepaired body
    or crashing the whole slot-production run (L6: hold visible, never
    silent — same spirit as DraftGenerationFailed/AdaptChannelFailed/
    FAQAnswerFailed)."""


def repair_piece(body_tagged: str, violations: list[str]) -> str:
    """E5. Matches the `Callable[[str, list[str]], str]` contract
    `run_gates()` (gates.py) requires for its `repair_fn` parameter: given
    the current `body_tagged` and the violations list from the first failing
    gate, returns the full repaired text. Raises `RepairFailed` after
    `_MAX_INVOKE_ATTEMPTS` failed Sonnet invokes — never returns a
    fabricated or partial repair."""
    prompt = _build_prompt(body_tagged, violations)
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


def _build_prompt(body_tagged: str, violations: list[str]) -> str:
    return (
        "CURRENT TEXT:\n" + body_tagged + "\n\n"
        "VIOLATIONS TO FIX (fix ONLY these, nothing else):\n- " + "\n- ".join(violations)
    )


__all__ = ["repair_piece", "RepairFailed"]
