"""services.acp_shared.atom_extraction — shared atom-extraction prompt/parse pieces.

Extracted from api/routers/v1_atoms.py (AA-475 — that router, the old platform-scope N2 atomize
endpoint, was deleted). These 4 pieces were never specific to that endpoint: they are the pure
prompt-build/parse/hash logic AA-299 proved, and `services/acp_produce/tenant_pipeline.py::
run_t5_atomize` (T5, the current owner_scope=tenant_id atomize pipeline) already depended on them
directly — moved here so T5 doesn't reach into a deleted router module.
"""
import hashlib
import re

SYSTEM_PROMPT = """You extract content atoms from a tour's source material for a travel \
marketing platform. An atom is one concrete, verbatim-derived moment from the trip — not a \
summary, not a paraphrase, not an invented detail.

Extract concrete, verbatim-derived moments only. If input is thin or empty, return an empty \
list — never invent content not present in the source text. Text must be a direct quote or \
minimal trim of the source material — do not add facts, names, numbers, or descriptive \
details that are not explicitly present in the input text, even if you know them to be true \
from general knowledge.

Example of what NOT to do: if the input says "visit a hillside temple", the atom must say \
only that — NOT "visit a 12th-century hillside temple famous for its hand-carved wooden \
gates", even though such details might be true of similar temples in general. Any fact not \
in the input text does not go in the atom, no matter how plausible or well-known.

Respond with ONLY a JSON object matching this exact contract:
{
  "atoms": [
    {
      "text": "verbatim-derived moment, 1-2 sentences",
      "activity_type": "trek|bike|food|culture|stay|transit|other",
      "emotional_hook": "string or null",
      "visual_potential": 1,
      "persona_fit": ["string", "..."],
      "season_note": "string or null",
      "itinerary_day": 1
    }
  ]
}

visual_potential is an integer 1-3 (3 = strong photo/video potential). No prose outside the \
JSON object.

itinerary_day is the day number in the source itinerary this atom belongs to (e.g. "DAY 01" -> 1, \
"Day 12" -> 12). Return null if the source text has no clear day label for this moment, or the \
atom isn't tied to one specific day (e.g. general trip-wide information). Never guess a day number \
without clear support in the source text.

If the itinerary is thin, return FEW atoms. Never pad. Returning 3 honest atoms beats 10 \
invented ones."""


def build_user_prompt(row: dict) -> str:
    parts = [f"TOUR: {row['name']}"]
    if row.get("aa_summary"):
        parts.append(f"SUMMARY: {row['aa_summary']}")
    if row.get("aa_highlights"):
        highlights = row["aa_highlights"]
        if isinstance(highlights, str):
            import json
            highlights = json.loads(highlights)
        if highlights:
            parts.append("HIGHLIGHTS:\n- " + "\n- ".join(str(h) for h in highlights))
    if row.get("itinerary_source"):
        parts.append(f"ITINERARY:\n{row['itinerary_source']}")
    if row.get("inclusions"):
        parts.append(f"INCLUSIONS:\n{row['inclusions']}")
    if row.get("exclusions"):
        parts.append(f"EXCLUSIONS:\n{row['exclusions']}")
    return "\n\n".join(parts)


def source_hash(row: dict) -> str:
    """sha256 of build_user_prompt()'s own output (migration 084) — hashing the exact string
    sent to the model, rather than re-deriving the field concatenation, guarantees the hash can
    never drift out of sync with what was actually decomposed."""
    return hashlib.sha256(build_user_prompt(row).encode("utf-8")).hexdigest()


def strip_json_fence(text: str) -> str:
    """invoke_claude() responses sometimes wrap the JSON in a ```json ... ``` fence despite
    SYSTEM_PROMPT saying "No prose outside the JSON object" (observed live, AA-305 inline-path
    test) — strip it before json.loads()."""
    match = re.match(r"^```(?:json)?\s*\n(.*)\n```\s*$", text.strip(), re.DOTALL)
    return match.group(1) if match else text
