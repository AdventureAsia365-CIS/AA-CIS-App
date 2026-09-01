"""services/acp_contract/ranking_reference.py — AA-515, ported reference data + pure exclusion
rules from Ms. Thư's aa-social-media.

Two questions, both deterministic (per that repo's own ADR 0019/0020 — "the rule decides and the
model annotates"), both needed before a Segment may be ranked or researched:

1. `is_transit(action)` — is this action getting somewhere (or the ceremony around the trip)
   rather than something to write about? Ported near-verbatim from `src/aa_social/transit.py` +
   `reference/transit-verbs.toml`.
2. `names_somewhere(place)` — does this place name somewhere in particular, or a kind of place
   ("a nearby hot spring", "the trailhead")? Ported near-verbatim from `src/aa_social/places.py`
   + `reference/place-kinds.toml`.

Both are inlined here as Python literals (openers/fillers/kinds lists), not loaded from a live
`.toml` file — same precedent AA-509's `segment_matching.py` already set for its own reference
table (`_ACTION_SYNONYM_CLASSES`, ported verbatim from `reference/action-verbs.toml` rather than
adding a toml-loading dependency this repo doesn't otherwise have).

Also carries `_claimable`/`_words`/`_named_words`/`place_kinds` (the word-sets `atom_ranking.py`'s
`_demand()` port needs to decide which bought keyword a Segment may claim) — kept in this same
module since they read the identical reference data (`place-kinds.toml`'s `kinds`+`qualifiers`
lists), not `ranking_reference` + a second near-empty file.
"""
from __future__ import annotations

import re

# ── reference/transit-verbs.toml, ported verbatim ──────────────────────────────────────────

_TRANSIT_OPENERS: tuple[str, ...] = (
    "arrive", "assemble", "board", "catch", "connect", "continue by", "cross by",
    "depart", "disembark", "drive", "fly", "meet", "return", "ride the", "take the",
    "transfer", "travel",
)

_FRAME_OPENERS: tuple[str, ...] = (
    "attend", "begin the tour", "conclude", "end the tour", "gather for", "orientation",
    "have breakfast", "have dinner", "free time", "have lunch", "leave luggage", "receive",
    "settle in", "spend free time", "spend leisure", "visit for orientation",
    "assist", "consult", "introduce", "undergo",
)

_LODGING_OPENERS: tuple[str, ...] = (
    "check in", "check out", "check into", "overnight", "sleep", "spend the night", "stay",
)

_LODGING_FILLER: frozenset[str] = frozenset({
    "a", "access", "accommodation", "airport", "an", "and", "another", "at",
    "close", "extra", "final", "first", "for", "further", "here", "hotel",
    "hotels", "in", "last", "lodging", "lodgings", "more", "night", "nights",
    "on", "one", "or", "overnight", "rest", "second", "stay", "style", "the",
    "third", "this", "three", "to", "transfer", "two", "up", "western", "with",
})

_LEISURE_OPENERS: tuple[str, ...] = (
    "explore", "spend the afternoon", "spend the day", "spend the evening",
    "spend the morning", "relax", "rest", "spend time", "wander",
)

_LEISURE_FILLER: frozenset[str] = frozenset({
    "a", "an", "and", "around", "at", "before", "briefly", "day", "departure",
    "evening", "for", "freely", "further", "here", "in", "independently",
    "dining", "exploration", "exploring", "leisure", "more", "morning", "on",
    "or", "own", "pace", "quietly", "shopping", "sightseeing", "the", "there",
    "time", "to", "until", "up", "wandering", "your",
})

_MEAL_OPENERS: tuple[str, ...] = ("dine", "eat", "have")

_MEAL_FILLER: frozenset[str] = frozenset({
    "a", "an", "and", "at", "before", "breakfast", "brunch", "dinner", "farewell",
    "final", "first", "for", "group", "guide", "here", "in", "last", "lunch",
    "meal", "of", "on", "own", "supper", "the", "to", "together", "tonight",
    "welcome", "with", "your",
})

_TIDY = re.compile(r"[^a-z0-9 ]+")


def transit_opener(action: str) -> str | None:
    """The listed opener that made this action transit, or None.

    Returned rather than discarded so an exclusion can say what excluded it (matches
    `atom_ranking.py`'s excluded_reason column) — the difference between an argument and an
    assertion, per the reference module's own docstring.
    """
    tidied = " ".join(_TIDY.sub(" ", (action or "").lower()).split())
    for opener in (*_TRANSIT_OPENERS, *_FRAME_OPENERS):
        if _opens_with(tidied, opener):
            return opener
    for opener in _LODGING_OPENERS:
        if _opens_with(tidied, opener) and not _names_a_bed(tidied, opener):
            return opener
    for opener in _LEISURE_OPENERS:
        if _opens_with(tidied, opener) and not _names_something(tidied, opener):
            return opener
    for opener in _MEAL_OPENERS:
        if _opens_with(tidied, opener) and not _names_food(tidied, opener):
            return opener
    return None


def is_transit(action: str) -> bool:
    """Whether this action is getting somewhere rather than being somewhere."""
    return transit_opener(action) is not None


def _opens_with(tidied: str, opener: str) -> bool:
    return tidied == opener or tidied.startswith(opener + " ")


def _names_something(tidied: str, opener: str) -> bool:
    rest = tidied[len(opener):].split()
    return not rest or any(word not in _LEISURE_FILLER for word in rest)


def _names_food(tidied: str, opener: str) -> bool:
    rest = tidied[len(opener):].split()
    return not rest or any(word not in _MEAL_FILLER for word in rest)


def _names_a_bed(tidied: str, opener: str) -> bool:
    rest = tidied[len(opener):].split()
    return any(word not in _LODGING_FILLER for word in rest)


# ── reference/place-kinds.toml, ported verbatim ────────────────────────────────────────────

_PLACE_KIND_NOUNS: frozenset[str] = frozenset({
    "airport", "area", "bar", "beach", "bridge", "cafe", "castle", "center",
    "centre", "city", "coast", "district", "falls", "ferry", "forest", "garden",
    "gardens", "gorge", "guesthouse", "hall", "harbour", "hostel", "hotel",
    "hotels", "house", "inn", "island", "japan", "japanese", "lake", "lodge",
    "lodging", "market", "minshuku", "mount", "mountain", "mountains", "museum",
    "onsen", "park", "pass", "path", "peninsula", "port", "quarter", "region",
    "restaurant",
    "river", "ryokan", "san", "shrine", "shrines", "shukubo", "station", "street",
    "temple", "temples", "town", "trail", "valley", "village", "waterfall",
    "cho", "dera", "gawa", "gu", "ji", "jinja", "jingu", "kawa", "ko", "koen",
    "ku", "machi", "misaki", "saki", "taisha", "yama", "zan",
})

_PLACE_QUALIFIERS: frozenset[str] = frozenset({
    "afternoon", "ancient", "central", "eastern", "evening", "grand", "great",
    "historic", "local", "lower", "morning", "national", "new", "night",
    "northern", "old", "people", "southern", "traditional", "upper", "western",
})

_PLACE_WHEN: frozenset[str] = frozenset({
    "annual", "daily", "friday", "monday", "monthly", "saturday", "sunday",
    "thursday", "tuesday", "wednesday", "weekend", "weekly", "yearly",
})

# What `names_somewhere()` reads: kinds + when (qualifiers deliberately absent — see
# `places.py`'s own docstring, "Northern" says nothing about whether a place is named).
PLACE_KIND_NOUNS: frozenset[str] = _PLACE_KIND_NOUNS | _PLACE_WHEN

# What claiming demand reads (`_words()`/`_claimable()` below): kinds + qualifiers + when,
# together — "score reads both lists as one" per place-kinds.toml's own comment.
PLACE_KINDS: frozenset[str] = _PLACE_KIND_NOUNS | _PLACE_QUALIFIERS | _PLACE_WHEN


def names_somewhere(place: str) -> bool:
    """Whether this place is somewhere in particular rather than a kind of place.

    One capitalised word that is not merely a kind of place, generous on purpose (ADR 0020) —
    "Mount Koya" still names a mountain because "Koya" is not a kind word.
    """
    return any(
        word[:1].isupper() and word.strip(",.'’").lower() not in PLACE_KIND_NOUNS
        for word in (place or "").split()
    )


# ── score.py's own word-set helpers, needed by atom_ranking.py's _demand() port ────────────

_ANYWHERE = frozenset({"to", "the", "a", "and", "of", "in", "at", "or", "near", "on", "from"})


def _words(text: str) -> set[str]:
    return set(_TIDY.sub(" ", (text or "").lower()).split()) - _ANYWHERE


def _named_words(text: str) -> set[str]:
    """The words of an action that name something, rather than describe it — a proper name
    (capitalised token) inside the action text, e.g. "walk the Nakasendo"."""
    return {
        word
        for token in (text or "").split()
        if token[:1].isupper()
        for word in _words(token)
        if len(word) > 1
    }


def claimable_words(place: str, action: str) -> set[str]:
    """The words a Segment may claim a bought keyword through — union of the place's own words
    and any proper name inside the action."""
    return _words(place) | _named_words(action)


def keyword_words(text: str) -> set[str]:
    """Public alias of `_words()` — the same tokenizer `claimable_words()` uses internally,
    exposed for `atom_ranking.py`'s `compute_demand()`/`compute_questions()` to tokenize a
    bought KEYWORD the identical way (both sides of a word-overlap test must tokenize
    identically or the overlap is meaningless)."""
    return _words(text)


__all__ = [
    "is_transit", "transit_opener", "names_somewhere",
    "PLACE_KIND_NOUNS", "PLACE_KINDS", "claimable_words", "keyword_words",
]
