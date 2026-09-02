"""
services.acp_angle_gate.ranking — AA-512: measurable angle ranking (ADR 0004, Ms. Thư repo:
docs/adr/0004-reasoning-patterns-placed-by-shape.md — "Angles are ranked by measurable criteria
... not by LLM opinion").

Port of `src/aa_social/angles.py::rank()`'s real algorithm (read, not guessed, per STEP0 —
docs/claude_audit/AA-512-step0-investigation.md §2), with 2 deliberate, disclosed adaptations:

1. Scope narrowed to the channel's OWN avoid-list only (AA-512's own text: "số vi phạm avoid-list
   của Channel"), not also the brand's — Ms. Thư's `Rules.load()` folds both in; this ticket
   doesn't own brand-wide banned-phrase config, so it isn't touched here.
2. `walks` is not scored — AA-512's own text lists exactly 3 axes (Segment/Route Score, PAA
   answered, avoid-list violations) and T8's angle-generation prompt still only ever sees ONE
   representative atom's text (Route-aware multi-segment context is AA-513's job, not built
   yet) — nothing to check "walks the whole journey" against.

Segment/Route Score (`subject.score`) is NOT part of the per-angle sort key below — it is
constant across all 3 angles of the same Subject (it already decided which Subject got proposed/
picked, AA-511's own job), so it cannot differentiate between 3 angles of the SAME subject. It is
surfaced to the tenant in the fixed header instead (service.py::fetch_request()), not folded into
a 3-way tie-break here. This is a disclosed synthesis, not a silent scope-drop — see STEP0 §2.

Ranking only runs when `channel` is already known at generation time (a Subject-driven request —
channel fixed from the Subject at creation) — avoid-list violations are channel-scoped and can't
be computed before a channel is known, which is genuinely never true for the legacy atom-picker
path (channel picked only at step 8, after angles already exist). See service.py's call site.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


def _plain(text: str) -> str:
    """Same normalization as the reference `angles.py::_plain()` — lowercase, strip everything
    but alnum+space, collapse whitespace. Used on both sides of a PAA-answer match so a requoted
    question with different punctuation/case still lands."""
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def split_avoid_phrases(avoid_text: str) -> tuple[str, ...]:
    """AA-CIS's own `channel_style.py::CHANNEL_STYLES[...]['avoid']` is one free-text,
    comma-joined string (unlike Ms. Thư's `ChannelSpec.avoid: list[str]`, already split) — this
    adapts the DATA SHAPE only, not the matching algorithm below. Empty/whitespace-only segments
    are dropped."""
    return tuple(p.strip() for p in avoid_text.split(",") if p.strip())


def _compile_banned(phrases: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    """Same `\\b<escaped>\\b` word-boundary, case-insensitive pattern per phrase as the
    reference `Rules.load()`."""
    return tuple(re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE) for p in phrases)


def _violations(text: str, banned: tuple[re.Pattern[str], ...]) -> list[str]:
    return [
        f"banned phrase '{match.group(0)}'"
        for pattern in banned
        for match in pattern.finditer(text)
    ]


@dataclass
class RankedAngle:
    """One angle_gate_option row's ranking evidence — attached back onto the dict service.py
    already builds, not a replacement for it."""
    idx: int
    answers: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def score(self) -> tuple[int, int]:
        """Sort key, best/lowest first: fewest avoid-list violations, then most real PAA
        questions answered. Matches the reference `Angle.score`'s first 2 elements exactly
        (its 3rd, `walks`, is out of scope here — see module docstring)."""
        return (len(self.violations), -len(self.answers))


def rank_angles(
    angles: list[dict], *, claimed_answers: list[list[str]],
    asked_questions: list[str], avoid_text: str,
) -> tuple[list[RankedAngle], int]:
    """Rank `angles` (each with 'name'/'why_it_works' text to check for avoid-list violations)
    against the real PAA pool and the channel's own avoid-list. `claimed_answers[i]` is the LLM's
    own claimed list of PAA questions for `angles[i]` — re-verified here, never trusted directly
    (ADR 0004's whole point).

    Returns (ranked_evidence_in_original_idx_order, recommended_idx) — evidence stays in the
    SAME order as `angles` (idx-aligned, for a simple zip at the call site); `recommended_idx` is
    the idx of the best-scoring angle (ties broken by earlier idx — stable, deterministic, no
    hidden tie-break the tenant can't see)."""
    asked = {_plain(q): q for q in asked_questions}
    banned = _compile_banned(split_avoid_phrases(avoid_text))

    evidence: list[RankedAngle] = []
    for i, a in enumerate(angles):
        claims = claimed_answers[i] if i < len(claimed_answers) else []
        real_answers = [asked[_plain(c)] for c in claims if _plain(c) in asked]
        text = f"{a.get('name', '')} {a.get('why_it_works', '')}"
        evidence.append(RankedAngle(idx=i, answers=real_answers, violations=_violations(text, banned)))

    best_idx = min(range(len(evidence)), key=lambda i: (evidence[i].score, i))
    return evidence, best_idx


__all__ = ["RankedAngle", "rank_angles", "split_avoid_phrases"]
