"""
services.acp_produce.adapt — N7 E3 (Adapt channel), AA-371.

STEP 0 (Linear AA-371 comment, 06/08/2026) confirmed the design executed
here:
- 1 Piece = 1 channel — already the real DB shape (`acp_deliver.pieces.
  channel`, migration 094, scalar TEXT NOT NULL, no list/JSONB). `Piece`
  itself gained the `channel` field in this same issue (models.py).
  `adapt_channels()` returns up to 2 NEW `Piece` objects (channel="facebook",
  channel="tiktok"), never mutates the blog `Piece` it reads from.
- Runs in the same E1-E5 generation pass as E2, BEFORE any F-gate — matches
  the original AA-298 order (`brief compile -> apply_output_rules() -> E1-E5
  generation -> F1-F9 gates`, pipeline.py's own docstring). Each returned
  channel Piece still goes through the same `run_piece_through_produce_gates
  ()` (F1/F8/F9) as the blog piece once a real slot-runner exists — nothing
  here special-cases channel for gating, that stays pipeline.py's job.
- Input is the blog Piece's OWN already-tagged body — atom ids come from
  what it actually cites (`atom_usage.py::atom_ids_cited()`, the same
  `[R:atom_id]`-only convention F1/N8 usage-logging already rely on), never
  re-derived from the atom pack. This is a hard requirement from the issue
  text ("tái sử dụng cùng atom_ids đã cite trong blog gốc, không re-derive
  từ atom pack lại từ đầu — tránh lệch nội dung giữa các kênh") and is also
  why E3 doesn't need to wait for E4: it deliberately never reads the blog's
  FAQ content (E4, faq.py, owns that section and appends it separately).
  **Caller ordering note** (no real slot-runner exists yet to enforce this,
  so it's a call-order contract, not a code guard): call `adapt_channels()`
  on the blog `Piece` BEFORE `faq.apply_faq()` mutates it. Calling after
  would let `atom_ids_cited()` also pick up atoms cited only inside the
  appended FAQ section — not unsafe (they'd still be real, already-grounded
  atoms) but it drifts from "adapt the blog content", the scope this issue
  actually asked for.
- Model is Bedrock satellite acc1 Sonnet, same `invoke_claude(...,
  model="sonnet")` call as E2 (generation.py) — CHỐT, not a proposal
  (AA-334 Cancelled, see generation.py's own docstring). Palmyra must never
  appear anywhere in this module.
- Two independent Sonnet calls (facebook, tiktok), not one combined call —
  so a failure on one channel never blocks the other. A failed channel is
  logged (`e3_adapt_channel_failed`) and simply omitted from the returned
  list; `adapt_channels()` itself never raises for a single-channel failure
  (only `_invoke_channel_with_retry()` raises, and that's caught internally).
"""
from __future__ import annotations

import time
from typing import Literal

import structlog

from services.acp_produce.atom_usage import atom_ids_cited
from services.acp_produce.models import Piece
from services.content_generation.brand_standards import AA_BRAND_IDENTITY_PROMPT
from shared.llm_client.bedrock_satellite import BedrockInvokeResult, BedrockUnavailable, invoke_claude

logger = structlog.get_logger()

_MAX_INVOKE_ATTEMPTS = 3  # 1 original + 2 retries, same policy as generation.py's E2
_RETRY_BACKOFF_SECONDS = 2.0
_MAX_TOKENS = 1024  # both channel outputs are short-form, well under E2's per-batch ceiling

ChannelName = Literal["facebook", "tiktok"]

_ADAPT_SYSTEM_PROMPT_BASE = (
    "You are adapting an ALREADY-WRITTEN blog piece into a shorter channel-specific format.\n\n"
    + AA_BRAND_IDENTITY_PROMPT.strip() +
    "\n\nHARD RULES FOR THIS ADAPT TASK:\n"
    "- You may ONLY cite [R:atom_id] ids from the ATOM LIST given below — never invent a new id,\n"
    "  never cite an id not in that list.\n"
    "- Do not add any factual claim that isn't already in the blog text given to you.\n"
    "- Do NOT use [F:...] tags anywhere.\n"
)

_FACEBOOK_INSTRUCTIONS = (
    "\nFACEBOOK CAPTION FORMAT — output ONLY this, nothing else:\n"
    "- One short paragraph, 50-120 words, brand voice, at least one [R:atom_id] citation carried\n"
    "  over from the blog text.\n"
    "- Then a final line starting with \"HASHTAGS:\" followed by 3-5 relevant hashtags.\n"
)

_TIKTOK_INSTRUCTIONS = (
    "\nTIKTOK KIT FORMAT — output ONLY these three labeled blocks, in order:\n"
    "\"HOOK:\" one line, <=15 words, no citation needed.\n"
    "\"SCRIPT:\" 100-150 words, spoken/conversational, at least one [R:atom_id] citation carried\n"
    "  over from the blog text.\n"
    "\"VISUAL:\" 1-2 lines of shot/visual direction notes (no video/image is generated — this is\n"
    "  text guidance only for whoever films it).\n"
)

_CHANNEL_INSTRUCTIONS: dict[ChannelName, str] = {
    "facebook": _FACEBOOK_INSTRUCTIONS,
    "tiktok": _TIKTOK_INSTRUCTIONS,
}

# Substrings that MUST be present for a response to be considered parseable —
# same "unparseable == invoke failure, never guess a partial result" stance
# generation.py's _parse_batch_response() already established for E2.
_CHANNEL_REQUIRED_MARKERS: dict[ChannelName, tuple[str, ...]] = {
    "facebook": ("HASHTAGS:",),
    "tiktok": ("HOOK:", "SCRIPT:", "VISUAL:"),
}


class AdaptChannelFailed(Exception):
    """One channel's Sonnet invoke kept failing after retries, or its
    response didn't contain the required format markers. Raised internally
    by `_invoke_channel_with_retry()` and always caught by
    `adapt_channels()` — never propagates out of this module."""


def adapt_channels(blog_piece: Piece, atom_text_by_id: dict[str, str]) -> list[Piece]:
    """E3. Returns 0, 1, or 2 new `Piece` objects (channel="facebook" /
    "tiktok") adapted from `blog_piece.body_tagged`. A channel that fails
    after retries is logged and omitted — never raises, never blocks the
    other channel."""
    cited_ids = atom_ids_cited(blog_piece)
    cited_atom_text = {aid: atom_text_by_id[aid] for aid in cited_ids if aid in atom_text_by_id}

    pieces: list[Piece] = []
    for channel in ("facebook", "tiktok"):
        try:
            body = _invoke_channel_with_retry(blog_piece.body_tagged, cited_atom_text, channel)
        except AdaptChannelFailed as e:
            logger.error("e3_adapt_channel_failed", channel=channel,
                         blog_piece_id=blog_piece.piece_id, error=str(e))
            continue
        pieces.append(Piece(piece_id=f"{blog_piece.piece_id}#{channel}", body_tagged=body, channel=channel))
    return pieces


def _build_prompt(blog_body: str, cited_atom_text: dict[str, str], channel: ChannelName) -> str:
    lines = [
        "BLOG TEXT (adapt from this, do not add facts beyond it):",
        blog_body,
        "",
        "ATOMS YOU MAY CITE (only these ids, exactly as given):",
    ]
    lines += [f"- {aid}: {text}" for aid, text in cited_atom_text.items()] or ["- (none cited in the blog text)"]
    return "\n".join(lines)


def _invoke_channel_with_retry(blog_body: str, cited_atom_text: dict[str, str], channel: ChannelName) -> str:
    system = _ADAPT_SYSTEM_PROMPT_BASE + _CHANNEL_INSTRUCTIONS[channel]
    prompt = _build_prompt(blog_body, cited_atom_text, channel)
    required_markers = _CHANNEL_REQUIRED_MARKERS[channel]

    last_err: Exception | None = None
    for attempt in range(1, _MAX_INVOKE_ATTEMPTS + 1):
        try:
            result: BedrockInvokeResult = invoke_claude(prompt, model="sonnet", max_tokens=_MAX_TOKENS, system=system)
        except BedrockUnavailable as e:
            last_err = e
            logger.warning("e3_adapt_sonnet_retry", channel=channel, attempt=attempt,
                            max_attempts=_MAX_INVOKE_ATTEMPTS, error=str(e))
            if attempt < _MAX_INVOKE_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
            continue

        if not all(marker in result.text for marker in required_markers):
            last_err = AdaptChannelFailed(
                f"response missing required marker(s) {required_markers} for channel={channel}"
            )
            logger.warning("e3_adapt_unparseable_retry", channel=channel, attempt=attempt,
                            max_attempts=_MAX_INVOKE_ATTEMPTS)
            if attempt < _MAX_INVOKE_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
            continue

        logger.info("e3_adapt_channel_success", channel=channel, model_used=result.model_used,
                     latency_ms=result.latency_ms, usage=result.usage)
        return result.text.strip()

    raise AdaptChannelFailed(
        f"channel={channel} failed after {_MAX_INVOKE_ATTEMPTS} attempts: {last_err}"
    ) from last_err


__all__ = ["adapt_channels", "AdaptChannelFailed"]
