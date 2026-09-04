"""
services/content_generation/s1_from_atom.py — AA-306 S1-from-atom.

Writes a tour page by ASSEMBLING from curated atoms (acp_contract.tour_atoms,
AA-299 decompose + AA-300 curation UI) instead of writing freely from the raw
itinerary the way old S1 (graph.py) does. Runs PARALLEL to old S1 — this module
never imports from or mutates graph.py, and nothing here touches
silver_aa_internal.generated_content or the old S1 tables.

Grounding contract (ADR-2026-024/029, D1/L1): every sentence carrying a concrete
claim must cite the atom(s) it came from as "[R:atom_xxx]", using the tour's own
atom_id values verbatim. Closed world — no atom, no claim, even if true in
general. Density gate (F2, services/acp_shared/atom_constants.ATOM_DENSITY_WORDS):
>=1 citation per 300 words of generated prose, checked deterministically, not by
asking the model to self-report.

Writer model (AA-392, 09/08/2026 — supersedes AA-306's original Palmyra X5
choice; AA-397 12/08/2026 — acc3 now primary, acc1 fallback): Bedrock satellite
acc3 Sonnet (shared/llm_client/bedrock_satellite.py, model="sonnet"), the exact
same writer N7 Produce uses (services/acp_produce/
generation.py, AA-370/AA-334). Palmyra X5 (acc2-native,
us.writer.palmyra-x5-v1:0) is permanently rejected for this module — AA-337
measured it hard-capped at 1 req/min (channel-program limit, not adjustable),
the same throughput wall that made N7 abandon it (AA-334, Cancelled
06/08/2026, direct Nghiep sign-off) before this module's own AA-391 live
verify run hit the identical throttle. Palmyra must never appear anywhere in
this module again. generate_draft() is a one-function seam
(_call_claude_satellite below) — a future writer swap is a one-line
model_tier change, not a rewrite.
"""
import hashlib
import json
import re

import structlog
from json_repair import repair_json

from services.acp_shared.atom_constants import ATOM_DENSITY_WORDS
from services.acp_shared.grounding import find_novel_numeric_claims

logger = structlog.get_logger()

AWS_REGION = "us-west-1"
DEFAULT_MODEL_TIER = "claude"
MAX_RETRIES = 2
# Captures whatever token follows "[R:" verbatim, not just a well-formed atom_id
# shape — a hallucinated/malformed reference must still surface as an "unknown
# citation" in check_grounding() below, not be silently un-matched and treated
# as if no citation attempt was made there at all.
CITE_RE = re.compile(r"\[R:([^\]]+)\]")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
# Sentence boundary for the per-sentence entailment check (AA-325/ADR-2026-033) --
# splits on .!? followed by a capital/quote, same heuristic used to build the
# real-data test fixture in tests/unit/fixtures/aa325_grounding_units.json.
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'‘’“”])")

# Fields that carry prose subject to the citation/density gate. seo_title/
# seo_meta are excluded — they're short derived summaries, not new claims;
# gating them would just force decorative cites with no grounding value.
_GATED_FIELDS = ("aa_subtitle", "aa_summary", "aa_highlights", "aa_itineraries")

_GROUNDING_SYSTEM_PROMPT = """You are an editor for Adventure Asia, a private-travel brand \
for senior professionals (40-60) from US/UK/AUS markets. You write tour pages by ASSEMBLING \
from a fixed set of pre-verified atoms — you do not invent, infer, or add outside knowledge.

CLOSED WORLD RULE (L1) — the single most important rule: if a fact is not in the ATOM PACK \
below, it does not go in the output, even if you are certain it is true in general. An atom \
pack with 6 atoms produces content that only ever claims those 6 things, in whatever voice — \
never more.

CITATION RULE: every sentence that makes a concrete claim (a place, an activity, a detail) \
must end with a citation tag referencing the atom(s) it was built from, in the exact form \
[R:atom_xxxxxxxxxx] using the atom_id values given in the ATOM PACK verbatim — never invent \
an atom_id, never cite an atom_id that is not in the ATOM PACK. Sentences with no concrete \
claim (transitions, brand framing) do not need a citation. A sentence with a citation tag \
whose content is not actually supported by that atom's text is a worse violation than no \
citation at all — the tag must be true of what you write, not decorative.

STRICT RULES:
1. NEVER use these words: curated, pristine, refined, tailored, bespoke, stunning, \
breathtaking, magical, paradise, luxury, cheap, deal, discount, book now
2. If the atom pack is thin, write LESS. A short, fully-grounded page beats a long one \
padded with generic travel-writing filler ("breathtaking views", "unforgettable journey") \
that carries no citation because it carries no atom.
3. Do not invent day numbers, meal names, or clock-times not present in the atoms.

Output ONLY valid JSON. No preamble, no markdown, no explanation."""


class GroundingError(Exception):
    """Claude output failed the closed-world or density gate after all retries.

    AA-289: carries prompt_version/gate/retries when available (i.e. whenever a system
    prompt was actually built and at least one draft was attempted) so the caller can log a
    'gate_failed' row without recomputing the hash — None on the earlier "no curated atoms"
    raise, where no LLM call was ever attempted and there's nothing meaningful to log against
    a prompt_version yet.
    """

    def __init__(self, message: str, prompt_version: str = None, gate: dict = None, retries: int = None):
        # B042 (flake8-bugbear): pass every constructor arg to super().__init__() so
        # pickle/copy.copy() can reconstruct this exception from .args alone, not just attrs.
        super().__init__(message, prompt_version, gate, retries)
        self.prompt_version = prompt_version
        self.gate = gate
        self.retries = retries


def _row_to_atom(r) -> dict:
    return {
        "atom_id": r["atom_id"],
        "text": r["text"],
        "activity_type": r.get("activity_type"),
        "emotional_hook": r.get("emotional_hook"),
        "season_note": r.get("season_note"),
        "itinerary_day": r.get("itinerary_day"),
    }


async def fetch_curated_atoms(tour_id: str, pool) -> list[dict]:
    """The curated set for a tour is NOT deleted AND NOT is_empty_marker (migration
    085) — the same filter admin_atoms.py's list/summary endpoints use. There is no
    separate "curated=true" column; `starred` is a weighting signal for the N6
    allocator (services/acp_planning/allocator.py), not a membership filter here.

    AA-355: itinerary_day (migration 093, AA-352) is now selected and used to
    order/group the atom pack by day — NULLS LAST puts atoms decomposed before
    migration 093 (or ones the model couldn't place) after every dated atom,
    so they still land in the pack (never dropped) but outside any DAY group."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT atom_id, text, activity_type, emotional_hook, season_note, itinerary_day
            FROM acp_contract.tour_atoms
            WHERE tour_id = $1::uuid AND NOT deleted AND NOT is_empty_marker
            ORDER BY itinerary_day NULLS LAST, created_at
            """,
            tour_id,
        )
    return [_row_to_atom(r) for r in rows]


def _build_atom_pack(atoms: list[dict]) -> str:
    """AA-355: atoms with a non-null itinerary_day are grouped under "DAY N"
    headers (ascending) — this is the model's ONLY day-boundary signal, so the
    number of DAY groups shown must equal the number of day-blocks the model
    writes in aa_itineraries (see build_user_prompt). Atoms with itinerary_day
    None (pre-migration-093 atoms, or ones the extractor couldn't place) are
    listed under a separate UNDATED section — still available to cite for
    aa_summary/aa_highlights, but explicitly not to be assigned an invented
    day. A tour with zero dated atoms produces only the UNDATED section,
    reproducing the pre-AA-355 flat/narrative behavior exactly."""
    dated: dict[int, list[dict]] = {}
    undated: list[dict] = []
    for a in atoms:
        day = a.get("itinerary_day")
        if day is None:
            undated.append(a)
        else:
            dated.setdefault(day, []).append(a)

    def _atom_line(a: dict) -> str:
        detail = f"[{a['atom_id']}] {a['text']}"
        extras = []
        if a.get("activity_type"):
            extras.append(f"type={a['activity_type']}")
        if a.get("emotional_hook"):
            extras.append(f"hook={a['emotional_hook']}")
        if a.get("season_note"):
            extras.append(f"season={a['season_note']}")
        if extras:
            detail += f" ({', '.join(extras)})"
        return detail

    sections = []
    for day in sorted(dated):
        lines = "\n".join(_atom_line(a) for a in dated[day])
        sections.append(f"DAY {day}:\n{lines}")
    if undated:
        lines = "\n".join(_atom_line(a) for a in undated)
        sections.append(
            "UNDATED (no source day identified for these — do not assign them to a day; "
            f"use only for aa_summary/aa_highlights, never invent a day for them):\n{lines}"
        )
    return "\n\n".join(sections)


def build_user_prompt(tour: dict, atoms: list[dict], feedback: str = "") -> str:
    atom_pack = _build_atom_pack(atoms)
    feedback_block = f"\n\nPREVIOUS ATTEMPT FEEDBACK — fix these before continuing:\n{feedback}" if feedback else ""

    # AA-355: day-count instruction is derived straight from the DAY groups actually
    # present in the atom pack (not a source-side day count the model has no way to
    # verify) — the model's only obligation is internal consistency with what it was
    # shown. Zero dated atoms (tour has no day-tagged atoms at all, e.g. pre-migration-093
    # curation) falls back to the original undated instruction rather than claiming a
    # day count of zero.
    day_numbers = sorted({a["itinerary_day"] for a in atoms if a.get("itinerary_day") is not None})
    if day_numbers:
        day_instruction = (
            f"The ATOM PACK below is grouped into {len(day_numbers)} DAY group(s) "
            f"(DAY {min(day_numbers)} to DAY {max(day_numbers)}). aa_itineraries MUST contain exactly "
            f"{len(day_numbers)} day-block(s), one per DAY group shown, in the same order — do not merge, "
            "split, skip, or add day-blocks beyond what the DAY groups show. Atoms in the UNDATED section "
            "(if present) are supplementary context only — never turn them into an extra day-block."
        )
    else:
        day_instruction = (
            "No atom in this pack carries a known source day — write aa_itineraries as day-by-day prose "
            "inferred from atom order and content, without fabricating specific day numbers the atoms "
            "don't support."
        )

    return f"""Assemble a tour page for this trip using ONLY the atoms below.

TOUR: {tour.get('name', '')}
COUNTRY: {tour.get('country', '')}

ATOM PACK ({len(atoms)} atoms — the ONLY facts you may use):
{atom_pack}
{feedback_block}

DAY STRUCTURE: {day_instruction}

OUTPUT JSON FORMAT:
{{
  "aa_name": "Evocative, specific tour name (brand voice) — no outside facts, may paraphrase the TOUR name above",
  "aa_subtitle": "Concrete subtitle built from atom content, with citation tag(s)",
  "aa_summary": "Editorial prose assembled from atoms, each concrete-claim sentence cited [R:atom_xxx]",
  "aa_highlights": ["Specific highlight built from one or more atoms, cited [R:atom_xxx]", "..."],
  "aa_itineraries": [
    {{"day": "day number matching a DAY group above, or null if this pack has no DAY groups",
     "title": "Short day title built from atom content",
     "prose": "Prose describing that day's activities, cited [R:atom_xxx] per claim"}}
  ]
}}"""


# ── Writer seam ──────────────────────────────────────────────────────────────

def generate_draft(system_prompt: str, user_prompt: str, model_tier: str = DEFAULT_MODEL_TIER,
                    max_tokens: int = 4096) -> dict:
    """Single seam every caller in this module goes through. Swapping the writer
    model is changing the model_tier argument at the call site — no other code
    in this file needs to change. Returns
    {text, model_used, provider, input_tokens, output_tokens}."""
    if model_tier == "palmyra":
        raise ValueError(
            "model_tier='palmyra' is permanently rejected (AA-392, 09/08/2026) — Palmyra X5's "
            "1 req/min channel-program throttle (AA-337) makes it unusable here, the same reason "
            "N7 dropped it (AA-334). Use model_tier='claude'."
        )
    if model_tier == "claude":
        return _call_claude_satellite(system_prompt, user_prompt, max_tokens)
    raise ValueError(f"Unknown model_tier: {model_tier!r} (expected 'claude')")


def _call_claude_satellite(system_prompt: str, user_prompt: str, max_tokens: int) -> dict:
    """AA-392 default writer — Claude Sonnet via the AA-296/397 Bedrock satellite, the same
    `invoke_claude()` call N7's own writer uses (services/acp_produce/generation.py). Real
    billed money post Activate-credits-rejection (ADR-2026-032) — accepted cost, same as N7's
    own AA-334 sign-off (06/08/2026) to move off Palmyra.

    AA-518 (02/09/2026) — model/account now come from the "s1_atom_writer" stage config (seeded
    to sonnet/acc3, matching the prior hardcoded literals exactly). Also fixes a stale docstring
    this same STEP0 flagged: this function previously described itself as having an "acc1
    fallback" — it never did (one call, one account, no except-and-retry-on-acc1 anywhere in
    this function); that fallback only exists in Mechanism A (LLMClient.generate()), not here."""
    from shared.llm_client.bedrock_satellite import invoke_claude, BedrockUnavailable
    from shared.llm_client.role_config import get_stage_config_sync
    from shared.llm_client.call_log import record_call_sync
    from shared.llm_client.pricing import calc_cost

    cfg = get_stage_config_sync("s1_atom_writer")
    try:
        result = invoke_claude(
            user_prompt, model=cfg.model_id, max_tokens=max_tokens, system=system_prompt,
            account=cfg.account_route or "acc3",
        )
    except BedrockUnavailable as e:
        raise RuntimeError(f"Claude satellite failed: {e}") from e
    in_tok = result.usage.get("input_tokens", 0)
    out_tok = result.usage.get("output_tokens", 0)
    record_call_sync(
        stage="s1_atom_writer", role="writer", model=f"satellite-{result.model_used}",
        tokens_in=in_tok, tokens_out=out_tok, cost_usd=calc_cost(cfg.model_id, in_tok, out_tok),
        tenant_id=None,  # AA-518 — same ContentState-has-no-tenant_id gap as s1_generate, flagged there
        quality_signal={"output_len_chars": len(result.text)},
        stop_reason=result.stop_reason,
    )
    return {
        "text": result.text,
        "model_used": f"satellite-{result.model_used}",
        "provider": "bedrock-satellite",
        "input_tokens": in_tok,
        "output_tokens": out_tok,
    }


# ── Persona/role layer (AA-243) ──────────────────────────────────────────────
# Deliberately a separate, additive function — only ever appended to the
# grounding system prompt AFTER grounding+gating is verified working (see
# AA-306 task ordering: persona before grounding produces content that is
# "different voice, same fabrication", the S104 finding this task must not
# repeat). Passing persona=None reproduces the pre-persona grounding prompt
# exactly, so the gate/density behavior above is unaffected either way.

def _persona_block(persona: str) -> str:
    return f"\n\nEDITORIAL PERSONA: {persona}"


DEFAULT_PERSONA = (
    "Write as a well-travelled Adventure Asia editor who has personally scouted this route — "
    "calm authority, specific over superlative, the tone of a trusted trip advisor briefing a "
    "client one-on-one, not a marketing brochure."
)


# ── Grounding / density gate ─────────────────────────────────────────────────

def _itinerary_prose_texts(val) -> list[str]:
    """AA-356: aa_itineraries is a list of {day, title, prose} dicts (AA-355's
    day-block format) or, as a fallback if the model doesn't comply, a flat
    string (the pre-AA-355 shape). Either way, returns only the prose-bearing
    text — `day` is structural metadata (which DAY group a block belongs to),
    never a factual claim, and must never reach the citation/density/
    entailment gates as if it were prose. This is the fix for AA-356: the day
    number itself was being flattened into gated text and then flagged by
    find_novel_numeric_claims() as an ungrounded number — grounding.py itself
    (ADR-2026-033) is untouched, this only fixes what gets fed into it."""
    if isinstance(val, list):
        texts = []
        for block in val:
            if isinstance(block, dict):
                if block.get("title"):
                    texts.append(str(block["title"]))
                if block.get("prose"):
                    texts.append(str(block["prose"]))
            elif block:
                texts.append(str(block))
        return texts
    return [str(val)] if val else []


def _flatten_gated_text(content: dict) -> str:
    parts = []
    for field in _GATED_FIELDS:
        val = content.get(field)
        if field == "aa_itineraries":
            parts.extend(_itinerary_prose_texts(val))
        elif isinstance(val, list):
            parts.extend(str(v) for v in val)
        elif val:
            parts.append(str(val))
    return "\n".join(parts)


def _entailment_violations(content: dict, atom_text_by_id: dict[str, str]) -> list[dict]:
    """AA-325/ADR-2026-033: per-sentence check that a cited sentence doesn't assert
    a number/measurement absent from the atom(s) it cites (see
    services/acp_shared/grounding.py for why this replaces a whole-sentence
    token-overlap ratio -- that approach was tested against real production
    output and could not separate real violations from real good content).
    Unknown atom_ids are skipped here, not penalized twice -- closed_world_pass
    already catches those."""
    violations = []
    for field in _GATED_FIELDS:
        val = content.get(field)
        if field == "aa_itineraries":
            texts = _itinerary_prose_texts(val)
        else:
            texts = val if isinstance(val, list) else [val] if val else []
        for t in texts:
            for sent in _SENT_SPLIT_RE.split(str(t)):
                tags = CITE_RE.findall(sent)
                if not tags:
                    continue
                cited_texts = [atom_text_by_id[a] for a in tags if a in atom_text_by_id]
                novel = find_novel_numeric_claims(sent, cited_texts)
                if novel:
                    violations.append({"field": field, "sentence": sent.strip(), "novel_numbers": novel})
    return violations


def check_grounding(content: dict, valid_atom_ids: set[str], atom_text_by_id: dict[str, str]) -> dict:
    """Deterministic gate — never trusts the model's own citation claims.
    Returns {citations: [...], unknown_citations: [...], word_count, citation_count,
    words_per_citation, density_pass, closed_world_pass, entailment_pass,
    entailment_violations}."""
    text = _flatten_gated_text(content)
    citations = CITE_RE.findall(text)
    unknown = sorted({c for c in citations if c not in valid_atom_ids})
    # Strip citation tags before counting words — "[R:atom_xxx]" is markup, not
    # prose, and left in place it inflates word_count (and so understates real
    # density) by 2-3 words per citation.
    prose_only = CITE_RE.sub("", text)
    word_count = len(_WORD_RE.findall(prose_only))
    citation_count = len(citations)

    # words_per_citation, not citations/word — reads directly as "1 cite per N
    # words", the same units ATOM_DENSITY_WORDS is expressed in.
    words_per_citation = (word_count / citation_count) if citation_count else float("inf")
    density_pass = citation_count > 0 and words_per_citation <= ATOM_DENSITY_WORDS
    closed_world_pass = len(unknown) == 0

    entailment_violations = _entailment_violations(content, atom_text_by_id)
    entailment_pass = len(entailment_violations) == 0

    return {
        "citations": citations,
        "unknown_citations": unknown,
        "word_count": word_count,
        "citation_count": citation_count,
        "words_per_citation": round(words_per_citation, 1) if citation_count else None,
        "density_pass": density_pass,
        "closed_world_pass": closed_world_pass,
        "entailment_pass": entailment_pass,
        "entailment_violations": entailment_violations,
    }


def _parse_draft_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        salvaged = repair_json(raw, return_objects=True)
        if isinstance(salvaged, dict):
            return salvaged
        raise


def _grounding_feedback(gate: dict) -> str:
    issues = []
    if not gate["closed_world_pass"]:
        issues.append(
            f"These citation tags reference atom_ids NOT in the ATOM PACK: "
            f"{', '.join(gate['unknown_citations'])}. Every [R:atom_xxx] must use an atom_id "
            f"printed in the ATOM PACK above, verbatim."
        )
    if not gate["density_pass"]:
        if gate["citation_count"] == 0:
            issues.append("No citation tags found at all. Every concrete-claim sentence needs a [R:atom_xxx] tag.")
        else:
            issues.append(
                f"Citation density too low: {gate['words_per_citation']} words per citation "
                f"(need <= {ATOM_DENSITY_WORDS}). Either add more citation tags to claims that "
                f"already have one nearby, or cut ungrounded prose that has no atom behind it."
            )
    if not gate["entailment_pass"]:
        examples = "; ".join(
            f"\"{v['sentence'][:100]}\" states {v['novel_numbers']} which its cited atom(s) never mention"
            for v in gate["entailment_violations"][:3]
        )
        issues.append(
            f"Some sentences state a specific number/measurement not present in the atom(s) they cite: "
            f"{examples}. A citation tag is only valid if the atom actually supports every figure in that "
            f"sentence — remove the invented number or cite an atom that states it."
        )
    return " ".join(issues)


async def generate_s1_from_atom(
    tour_id: str,
    tour: dict,
    pool,
    model_tier: str = DEFAULT_MODEL_TIER,
    persona: str | None = DEFAULT_PERSONA,
    max_tokens: int = 4096,
) -> dict:
    """Entry point. tour = {"name": ..., "country": ...} (caller-supplied, kept
    minimal — this module only needs enough to label the output, all factual
    content comes from atoms). Raises GroundingError if the gate never passes
    within MAX_RETRIES. Returns {content, atoms_used, gate, retries, model_used,
    input_tokens, output_tokens, atoms_available, prompt_version}."""
    atoms = await fetch_curated_atoms(tour_id, pool)
    if not atoms:
        raise GroundingError(f"No curated atoms for tour {tour_id} — nothing to assemble from")
    valid_atom_ids = {a["atom_id"] for a in atoms}
    atom_text_by_id = {a["atom_id"]: a["text"] for a in atoms}

    system_prompt = _GROUNDING_SYSTEM_PROMPT
    if persona:
        system_prompt += _persona_block(persona)

    # AA-289: hash the stable prefix (grounding rules + persona), same sha256[:8] convention as
    # S1-old (graph.py generate_node) — NOT including build_user_prompt's atom pack, which is
    # per-tour variable content, not the "prompt template" AA-289 means to version.
    prompt_version = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:8]

    feedback = ""
    last_content: dict = {}
    last_gate: dict = {}
    last_draft: dict = {}
    for attempt in range(MAX_RETRIES + 1):
        user_prompt = build_user_prompt(tour, atoms, feedback=feedback)
        draft = generate_draft(system_prompt, user_prompt, model_tier=model_tier, max_tokens=max_tokens)
        last_draft = draft
        try:
            content = _parse_draft_json(draft["text"])
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("s1_from_atom_parse_failed", tour_id=tour_id, attempt=attempt, error=str(e))
            feedback = f"Your last response was not valid JSON matching the required schema: {e}"
            continue

        gate = check_grounding(content, valid_atom_ids, atom_text_by_id)
        last_content, last_gate = content, gate

        if gate["density_pass"] and gate["closed_world_pass"] and gate["entailment_pass"]:
            logger.info("s1_from_atom_gate_passed", tour_id=tour_id, attempt=attempt,
                        citation_count=gate["citation_count"], words_per_citation=gate["words_per_citation"])
            return {
                "content": content,
                "atoms_used": sorted(set(gate["citations"])),
                "atoms_available": len(atoms),
                "gate": gate,
                "retries": attempt,
                "model_used": draft["model_used"],
                "input_tokens": draft["input_tokens"],
                "output_tokens": draft["output_tokens"],
                "prompt_version": prompt_version,
            }

        # AA-306 L6-spirit: reject is logged loudly, never silent.
        logger.warning("s1_from_atom_gate_rejected", tour_id=tour_id, attempt=attempt,
                        closed_world_pass=gate["closed_world_pass"], density_pass=gate["density_pass"],
                        entailment_pass=gate["entailment_pass"],
                        citation_count=gate["citation_count"], words_per_citation=gate["words_per_citation"],
                        unknown_citations=gate["unknown_citations"],
                        entailment_violations=gate["entailment_violations"])
        feedback = _grounding_feedback(gate)

    raise GroundingError(
        f"tour {tour_id}: grounding gate failed after {MAX_RETRIES + 1} attempts "
        f"(closed_world_pass={last_gate.get('closed_world_pass')}, "
        f"density_pass={last_gate.get('density_pass')}, "
        f"entailment_pass={last_gate.get('entailment_pass')}, "
        f"words_per_citation={last_gate.get('words_per_citation')}). "
        f"Last model_used={last_draft.get('model_used')}.",
        prompt_version=prompt_version, gate=last_gate, retries=MAX_RETRIES,
    )
