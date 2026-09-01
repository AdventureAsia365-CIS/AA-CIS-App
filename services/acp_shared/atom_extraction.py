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


def _preamble_parts(row: dict) -> list[str]:
    """TOUR/SUMMARY/HIGHLIGHTS lines shared by build_user_prompt() (whole-tour) and
    build_day_user_prompt() (AA-508, per-day) — factored out so the two never drift
    apart on what tour-level context the model sees."""
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
    return parts


def build_user_prompt(row: dict) -> str:
    parts = _preamble_parts(row)
    if row.get("itinerary_source"):
        parts.append(f"ITINERARY:\n{row['itinerary_source']}")
    if row.get("inclusions"):
        parts.append(f"INCLUSIONS:\n{row['inclusions']}")
    if row.get("exclusions"):
        parts.append(f"EXCLUSIONS:\n{row['exclusions']}")
    return "\n\n".join(parts)


def build_day_user_prompt(row: dict, day_number: int, day_title: str, day_body: str) -> str:
    """AA-508 — per-day variant of build_user_prompt(). Same TOUR/SUMMARY/HIGHLIGHTS preamble for
    context, but ITINERARY is scoped to this one day instead of the whole trip, so run_t5_atomize()
    can call the model (and fingerprint/cache the result) per day instead of once for the whole
    tour. SYSTEM_PROMPT (what counts as an atom, how decompose works) is untouched by this — only
    what the model is shown changes, never what it's asked to do with it."""
    parts = _preamble_parts(row)
    parts.append(f"ITINERARY:\nDay {day_number} — {day_title}\n{day_body}")
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


def normalise(text: str) -> str:
    """AA-508 — same normalisation aa-social-media's own `_normalise()` uses (models.py) before
    hashing: lowercase, every run of non-alphanumeric characters collapsed to one space, stripped.
    Exported (not `_normalise`) — content_hash_atom_id() and any test/consumer that needs to
    reproduce a hash input by hand both need it."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def content_hash_atom_id(tour_id: str, owner_scope: str, day_number: int, text: str) -> str:
    """An Atom's identity, derived from what it is rather than when it arrived — AA-508, mirrors
    aa-social-media's own atom_id() (src/aa_social/models.py), adapted to this schema's real
    shape (STEP0/STEP0b, docs/claude_audit/AA-508-step0*.md):

    - The reference formula hashes (trip_code, day, place, action). This codebase's decompose
      schema (SYSTEM_PROMPT above) has no separate place/action fields — one atom is one combined
      `text` (the verbatim moment) plus a coarse `activity_type` enum. `text` is what gets hashed
      here; it IS the place+action pair, just not split into two fields the way the reference
      repo's extractor returns them.
    - `owner_scope` (the rewriting tenant's id, or 'platform') is added to the hash input. The
      reference repo has no multi-tenant concept (one SQLite file per brand), so its formula never
      needed it. `tour_atoms.atom_id` here is a single GLOBAL primary key shared by every tenant
      that has ever rewritten a given `tour_id` — without owner_scope in the hash, two tenants'
      differently-worded rewrites of the same tour_id/day that happened to normalise to the same
      `text` would collide on that one PK and silently overwrite each other's row.

    `tour_id` is used verbatim (not normalised), same as the reference formula treats `trip_code`;
    `day_number` and `text` are normalised the same way normalise() does.
    """
    parts = (str(tour_id), owner_scope, str(day_number), normalise(text))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def day_fingerprint(day_title: str, day_body: str, model: str) -> str:
    """What one day's atomize reading depends on (AA-508) — mirrors aa-social-media's own
    _fingerprint() (src/aa_social/stages/atoms.py): the day's own text, the decompose instruction
    (SYSTEM_PROMPT), and the model. Change any of the three and the fingerprint changes — a
    matching fingerprint means run_t5_atomize() would get the exact same reading calling the model
    again, so it doesn't."""
    joined = "\n\0".join((day_title or "", day_body or "", SYSTEM_PROMPT, model))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def strip_json_fence(text: str) -> str:
    """invoke_claude() responses sometimes wrap the JSON in a ```json ... ``` fence despite
    SYSTEM_PROMPT saying "No prose outside the JSON object" (observed live, AA-305 inline-path
    test) — strip it before json.loads()."""
    match = re.match(r"^```(?:json)?\s*\n(.*)\n```\s*$", text.strip(), re.DOTALL)
    return match.group(1) if match else text
