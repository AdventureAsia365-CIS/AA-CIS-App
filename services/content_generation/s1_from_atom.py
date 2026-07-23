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

Writer model (ADR-2026-031/032, AA-308 Phần A bake-off evidence): Palmyra X5,
acc2-native (us.writer.palmyra-x5-v1:0), NOT the acc1 Claude satellite S1 old's
generate_node can fall back to — acc1 Claude calls are real billed money post
Activate-credits-rejection, and T1 acc2-native is the tier policy's preferred
writer once it clears a quality bar (Palmyra did, 14/20 vs Claude's 6/20 on a
blind Nova-judged sample). generate_draft() is a one-function seam so a future
switch to Claude is a one-line model_tier change, not a rewrite — see
_call_claude_satellite below, wired but not the default.
"""
import json
import re

import boto3
import structlog
from json_repair import repair_json

from services.acp_shared.atom_constants import ATOM_DENSITY_WORDS

logger = structlog.get_logger()

AWS_REGION = "us-west-1"
PALMYRA_MODEL_ID = "us.writer.palmyra-x5-v1:0"
DEFAULT_MODEL_TIER = "palmyra"
MAX_RETRIES = 2
# Captures whatever token follows "[R:" verbatim, not just a well-formed atom_id
# shape — a hallucinated/malformed reference must still surface as an "unknown
# citation" in check_grounding() below, not be silently un-matched and treated
# as if no citation attempt was made there at all.
CITE_RE = re.compile(r"\[R:([^\]]+)\]")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")

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
    """Palmyra/Claude output failed the closed-world or density gate after all retries."""


def _row_to_atom(r) -> dict:
    return {
        "atom_id": r["atom_id"],
        "text": r["text"],
        "activity_type": r.get("activity_type"),
        "emotional_hook": r.get("emotional_hook"),
        "season_note": r.get("season_note"),
    }


async def fetch_curated_atoms(tour_id: str, pool) -> list[dict]:
    """The curated set for a tour is NOT deleted AND NOT is_empty_marker (migration
    085) — the same filter admin_atoms.py's list/summary endpoints use. There is no
    separate "curated=true" column; `starred` is a weighting signal for the N6
    allocator (services/acp_planning/allocator.py), not a membership filter here."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT atom_id, text, activity_type, emotional_hook, season_note
            FROM acp_contract.tour_atoms
            WHERE tour_id = $1::uuid AND NOT deleted AND NOT is_empty_marker
            ORDER BY created_at
            """,
            tour_id,
        )
    return [_row_to_atom(r) for r in rows]


def _build_atom_pack(atoms: list[dict]) -> str:
    lines = []
    for a in atoms:
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
        lines.append(detail)
    return "\n".join(lines)


def build_user_prompt(tour: dict, atoms: list[dict], feedback: str = "") -> str:
    atom_pack = _build_atom_pack(atoms)
    feedback_block = f"\n\nPREVIOUS ATTEMPT FEEDBACK — fix these before continuing:\n{feedback}" if feedback else ""
    return f"""Assemble a tour page for this trip using ONLY the atoms below.

TOUR: {tour.get('name', '')}
COUNTRY: {tour.get('country', '')}

ATOM PACK ({len(atoms)} atoms — the ONLY facts you may use):
{atom_pack}
{feedback_block}

OUTPUT JSON FORMAT:
{{
  "aa_name": "Evocative, specific tour name (brand voice) — no outside facts, may paraphrase the TOUR name above",
  "aa_subtitle": "Concrete subtitle built from atom content, with citation tag(s)",
  "aa_summary": "Editorial prose assembled from atoms, each concrete-claim sentence cited [R:atom_xxx]",
  "aa_highlights": ["Specific highlight built from one or more atoms, cited [R:atom_xxx]", "..."],
  "aa_itineraries": "Day-by-day prose from atoms describing that day's activities, cited [R:atom_xxx] per claim"
}}"""


# ── Writer seam ──────────────────────────────────────────────────────────────

def generate_draft(system_prompt: str, user_prompt: str, model_tier: str = DEFAULT_MODEL_TIER,
                    max_tokens: int = 4096) -> dict:
    """Single seam every caller in this module goes through. Swapping the writer
    model (e.g. Palmyra -> Claude satellite if a future verify run shows Palmyra
    output is not good enough) is changing the model_tier argument at the call
    site — no other code in this file needs to change. Returns
    {text, model_used, provider, input_tokens, output_tokens}."""
    if model_tier == "palmyra":
        return _call_palmyra(system_prompt, user_prompt, max_tokens)
    if model_tier == "claude":
        return _call_claude_satellite(system_prompt, user_prompt, max_tokens)
    raise ValueError(f"Unknown model_tier: {model_tier!r} (expected 'palmyra' or 'claude')")


def _call_palmyra(system_prompt: str, user_prompt: str, max_tokens: int) -> dict:
    """acc2-native, OpenAI-compatible response shape (choices[0].message.content) —
    verified live via ECS exec smoke test (AA-306 STEP 0), NOT Anthropic's
    content[0].text shape _call_claude_satellite below uses. No cross-account
    AssumeRole — aa-cis-dev-ecs-task-role's existing bedrock:InvokeModel
    (Resource "*") already covers acc2 models."""
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    body = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
    }
    resp = client.invoke_model(
        modelId=PALMYRA_MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(resp["body"].read())
    choice = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage", {})
    logger.info("s1_from_atom_llm_success", provider="bedrock-acc2", model=PALMYRA_MODEL_ID,
                in_tokens=usage.get("prompt_tokens", 0), out_tokens=usage.get("completion_tokens", 0))
    return {
        "text": choice,
        "model_used": PALMYRA_MODEL_ID,
        "provider": "bedrock-acc2",
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }


def _call_claude_satellite(system_prompt: str, user_prompt: str, max_tokens: int) -> dict:
    """T2 — acc1 Claude satellite (AA-296). Wired so the seam is real, but NOT the
    default model_tier: ADR-2026-031/032 gate this behind a quality bar Palmyra
    already cleared (AA-308 Phần A), and acc1 calls are real billed money post
    Activate-credits-rejection (ADR-2026-032) — switching this in as the default
    needs separate sign-off, not a silent fallback from this module."""
    from shared.llm_client.bedrock_satellite import invoke_claude, BedrockUnavailable
    try:
        result = invoke_claude(user_prompt, model="sonnet", max_tokens=max_tokens, system=system_prompt)
    except BedrockUnavailable as e:
        raise RuntimeError(f"Claude satellite failed: {e}") from e
    return {
        "text": result.text,
        "model_used": f"satellite-{result.model_used}",
        "provider": "bedrock-satellite",
        "input_tokens": result.usage.get("input_tokens", 0),
        "output_tokens": result.usage.get("output_tokens", 0),
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

def _flatten_gated_text(content: dict) -> str:
    parts = []
    for field in _GATED_FIELDS:
        val = content.get(field)
        if isinstance(val, list):
            parts.extend(str(v) for v in val)
        elif val:
            parts.append(str(val))
    return "\n".join(parts)


def check_grounding(content: dict, valid_atom_ids: set[str]) -> dict:
    """Deterministic gate — never trusts the model's own citation claims.
    Returns {citations: [...], unknown_citations: [...], word_count, citation_count,
    words_per_citation, density_pass, closed_world_pass}."""
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

    return {
        "citations": citations,
        "unknown_citations": unknown,
        "word_count": word_count,
        "citation_count": citation_count,
        "words_per_citation": round(words_per_citation, 1) if citation_count else None,
        "density_pass": density_pass,
        "closed_world_pass": closed_world_pass,
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
    input_tokens, output_tokens, atoms_available}."""
    atoms = await fetch_curated_atoms(tour_id, pool)
    if not atoms:
        raise GroundingError(f"No curated atoms for tour {tour_id} — nothing to assemble from")
    valid_atom_ids = {a["atom_id"] for a in atoms}

    system_prompt = _GROUNDING_SYSTEM_PROMPT
    if persona:
        system_prompt += _persona_block(persona)

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

        gate = check_grounding(content, valid_atom_ids)
        last_content, last_gate = content, gate

        if gate["density_pass"] and gate["closed_world_pass"]:
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
            }

        # AA-306 L6-spirit: reject is logged loudly, never silent.
        logger.warning("s1_from_atom_gate_rejected", tour_id=tour_id, attempt=attempt,
                        closed_world_pass=gate["closed_world_pass"], density_pass=gate["density_pass"],
                        citation_count=gate["citation_count"], words_per_citation=gate["words_per_citation"],
                        unknown_citations=gate["unknown_citations"])
        feedback = _grounding_feedback(gate)

    raise GroundingError(
        f"tour {tour_id}: grounding gate failed after {MAX_RETRIES + 1} attempts "
        f"(closed_world_pass={last_gate.get('closed_world_pass')}, "
        f"density_pass={last_gate.get('density_pass')}, "
        f"words_per_citation={last_gate.get('words_per_citation')}). "
        f"Last model_used={last_draft.get('model_used')}."
    )
