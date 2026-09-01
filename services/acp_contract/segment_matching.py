"""services/acp_contract/segment_matching.py — AA-509 Segment.

Groups tour_atoms describing the same real-world moment across a tenant's tours (not merging
content — an atom told two different ways stays two atoms, sharing one Segment). Foundation for
T6 group-by-Segment curation, Route (T7 Blog), Atom Score, Slate (none of those are built here).

Ported near-verbatim from Ms. Thư's aa-social-media (`src/aa_social/segments.py`) per the build
prompt and STEP0 (docs/claude_audit/AA-509-step0-schema-matching-investigation.md). The pure
grouping functions below (`derive_segments`/`reconcile_ids`/everything they call) are an
unmodified port of that algorithm's SHAPE — same Jaccard-on-place + verb-match-on-action logic,
same deterministic-derive-then-reconcile id strategy (ADR 0002, same repo:
docs/adr/0002-vector-store-scoped-to-search-matching.md — grouping must stay deterministic, no
embeddings, so a re-run never silently regroups Atoms out from under a Calendar/Slot built on the
old ids). Two adaptations were required, both because this codebase is multi-tenant and the
reference repo is one SQLite file per brand:

1. `_mint()` — segment_id derivation — has `tenant_id` folded into its hash input. The reference
   formula is `sha256(place|verb)` alone; without tenant_id, two tenants both describing "walk
   the Nakasendo trail" would derive the IDENTICAL segment_id and collide on one
   `atom_segment` PK row — the exact collision class AA-508 already found and fixed for
   `tour_atoms.atom_id` (see that task's Decision 2). Confirmed real by construction, not
   theoretical: `atom_segment.segment_id` has no `tenant_id` in its key otherwise.
2. `run_segment_matching()` (the DB-facing wrapper below — everything above it is pure, no I/O,
   per the build prompt's "pure function, không I/O" instruction) scopes every read/write to one
   `tenant_id` at a time, since one Postgres schema here holds every tenant's atoms, not one file
   per tenant the way the reference repo's CLI does.

`atom_segment` rows are UPSERT-only, never deleted, by design (see migration 129's own comment
for the FK reasoning: `atom_segment_alias.segment_id_old` references `atom_segment(segment_id)`,
so an id that "gave way" to another has to keep existing as a row for that FK to hold — matching
ADR 0002's own framing that the old id "still resolves", not that it disappears).
`atom_segment_member` (pure derived membership) IS fully rebuilt per tenant on every run.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import NamedTuple

# ── reference table, ported from Ms. Thư's aa-social-media (reference/action-verbs.toml) ───
# Deliberately narrow (see that file's own comment) — only add a class when a real export shows
# two itineraries splitting one moment across two words. Not re-derived here; copied verbatim.
_ACTION_SYNONYM_CLASSES: dict[str, list[str]] = {
    "eat": ["eat", "have", "dine", "taste", "sample"],
    "walk": ["walk", "hike", "stroll", "cross", "ramble", "trek"],
    "view": ["view", "observe", "watch", "see"],
    "bathe": ["bathe", "soak"],
}
_REACHED_BY_OPENERS = frozenset({"descend", "ascend", "climb", "continue", "proceed"})
_REACHED_BY_CONNECTORS = ("to and", "and then", "and")

# Connectors carry no information about which place is meant. Dropping them lets
# "Magome to Tsumago" meet "the Nakasendo post road between Magome and Tsumago".
CONNECTORS = frozenset(
    """a an and at between by for from in into of on over the through to via with""".split()
)

# Two places match when half their distinctive words agree, or when one is written out of the
# other — the long name for a walk contains the short one.
SIMILARITY = 0.5


class Key(NamedTuple):
    """What an Atom says, reduced to what grouping compares.

    `verb` is the moment's verb in its own words, so "have" and "eat" arrive here as one. `said`
    is the verb as the itinerary actually wrote it, and `about` is what the action names apart
    from its verb — both kept because a synonym is only safe where the two actions are about the
    same thing.
    """

    place: tuple[str, ...]
    verb: str
    said: str = ""
    about: frozenset = frozenset()


@dataclass(frozen=True)
class SegmentAtom:
    """One tour_atoms row as segment_matching sees it — maps onto aa_social.models.Atom's shape:
    trip_code -> tour_id, day -> itinerary_day (may be None: pre-migration-129 rows, or a row
    the legacy whole-tour path wrote before AA-352/migration 093)."""

    atom_id: str
    tour_id: str
    day: int | None
    place: str
    action: str


@dataclass(frozen=True)
class Segment:
    """One real-world moment, and the Atoms that describe it."""

    id: str
    place: str
    action: str
    atom_ids: tuple[str, ...]


def derive_segments(tenant_id: str, atoms: list[SegmentAtom]) -> list[Segment]:
    """Sort Atoms into Segments. Same Atoms in, same Segments out (for a given tenant_id).

    Quadratic in the number of Atoms — fine at one tenant's volumes (STEP0 mục 7), worth
    revisiting if any tenant's inventory reaches thousands, same caveat the reference repo's own
    `derive_segments()` docstring carries.
    """
    keys = {atom.atom_id: _key(atom) for atom in atoms}
    memberships = _connected(sorted(keys.items()))

    segments = []
    for members in memberships:
        canonical = _canonical(keys[atom_id] for atom_id in members)
        # Total for the same reason the reference repo's own comment gives: two Atoms of one
        # trip on one day reaching the same canonical key would otherwise be separated by list
        # order (a `set` iterates in a `PYTHONHASHSEED`-dependent order in CPython).
        label = min(
            (atom for atom in atoms if atom.atom_id in members and keys[atom.atom_id] == canonical),
            key=lambda atom: (atom.tour_id, _sort_day(atom.day), atom.place, atom.action),
        )
        segments.append(
            Segment(
                id=_mint(tenant_id, canonical),
                place=label.place,
                action=label.action,
                atom_ids=tuple(sorted(members)),
            )
        )
    return sorted(segments, key=lambda segment: segment.id)


def _sort_day(day: int | None) -> int:
    """A day-less Atom (NULL itinerary_day) sorts before every real day, deterministically —
    just needs to be a total order, not any particular one."""
    return -1 if day is None else day


def _canonical(keys: Iterable[Key]) -> Key:
    """The member key a Segment is named and identified by.

    The most economical naming of the moment — fewest distinctive words, ties broken
    alphabetically, then by verb/said/about so the ordering is total (mirrors the reference
    repo's own fix for a real cross-run instability it found — see its `_canonical()` docstring).
    """
    return min(
        keys,
        key=lambda key: (
            len(key.place),
            key.place,
            key.verb,
            key.said,
            tuple(sorted(key.about)),
        ),
    )


def _mint(tenant_id: str, canonical: Key) -> str:
    """A new Segment's identity, derived from what its members are (and which tenant they belong
    to — see this module's own docstring, item 1, for why tenant_id has to be in this hash).

    Only ever used for a Segment the tenant's own segments have not seen before. Once minted, an
    id is held: see `reconcile_ids`.
    """
    return hashlib.sha256(
        f"{tenant_id}|{' '.join(canonical.place)}|{canonical.verb}".encode()
    ).hexdigest()[:16]


def reconcile_ids(
    derived: list[Segment], assigned: Mapping[str, str]
) -> tuple[list[Segment], dict[str, str]]:
    """Keep the id a Segment already had, rather than re-deriving it.

    Deriving the id from the current members alone cannot survive a re-atomize: a tour that
    names a moment more briefly than anything already grouped re-identifies it, and a tour that
    bridges two Segments makes one id vanish. ADR 0002 requires a stable `segment_id` across
    re-runs — a Slate/Route/Slot built on an old id has to still resolve.

    So an id is derived from member identity when a Segment is first seen — never from arrival
    order — and held from then on. `assigned` maps atom_id to the Segment id it already belongs
    to (for THIS tenant only — the caller scopes it). Where a new Atom bridges two Segments, one
    id has to give way; the surviving id is chosen by content, not by order, and the other is
    returned as an alias so old references still resolve.
    """
    by_id = {segment.id: segment for segment in derived}
    ids = {segment.id: segment.id for segment in derived}
    taken = set(ids.values())
    aliases: dict[str, str] = {}

    # Sorted so the answer never depends on the order Segments were derived in.
    for prior, claimant in sorted(_claims(derived, assigned).items()):
        current = ids[claimant]
        if current == prior:
            continue
        if prior in taken:
            # Another Segment already answers to this id — it derived it from its own members.
            # The claimant keeps what it has and the old id points at whoever holds it.
            aliases[prior] = prior
            continue
        taken.discard(current)
        taken.add(prior)
        ids[claimant] = prior
        aliases[prior] = prior

    kept = [replace(by_id[identifier], id=ids[identifier]) for identifier in by_id]
    for prior, claimant in sorted(_claims(derived, assigned).items()):
        settled = ids[claimant]
        if prior != settled:
            aliases[prior] = settled
    return kept, _flatten(
        {was: target for was, target in aliases.items() if was != target}
    )


def _claims(
    derived: list[Segment], assigned: Mapping[str, str]
) -> dict[str, str]:
    """Which derived Segment has the best claim on each id that already existed.

    Re-extraction can split one Segment into several — a day that arrived as one run-on place
    becomes several Atoms — and then every part inherits the same old id. Only one may have it.
    The part holding most of the old Segment's Atoms wins, and a Segment that already is that id
    keeps it outright.
    """
    contenders: dict[str, dict[str, int]] = {}
    for segment in derived:
        for atom_id in segment.atom_ids:
            prior = assigned.get(atom_id)
            if prior is not None:
                held = contenders.setdefault(prior, {})
                held[segment.id] = held.get(segment.id, 0) + 1

    claims = {}
    for prior, held in contenders.items():
        if prior in held:
            claims[prior] = prior
            continue
        claims[prior] = min(held, key=lambda identifier: (-held[identifier], identifier))
    return claims


def _flatten(aliases: dict[str, str]) -> dict[str, str]:
    """Point every alias at the id that is actually live."""
    resolved = {}
    for start, target in aliases.items():
        seen = {start}
        while target in aliases and target not in seen:
            seen.add(target)
            target = aliases[target]
        resolved[start] = target
    return resolved


def _key(atom: SegmentAtom) -> Key:
    words = re.findall(r"[a-z0-9]+", atom.action.lower())
    rest = _past_the_approach(words)
    return Key(
        place=_place_tokens(atom.place),
        verb=_leading_verb(atom.action),
        said=_stem(rest[0]) if rest else "",
        about=frozenset(_stem(word) for word in rest[1:] if word not in CONNECTORS),
    )


def _place_tokens(place: str) -> tuple[str, ...]:
    words = re.findall(r"[a-z0-9]+", place.lower())
    kept = [word for word in words if word not in CONNECTORS]
    return tuple(sorted(set(kept or words)))


def _leading_verb(action: str) -> str:
    """The verb this action is about, stemmed and put in its own words.

    The first word is the verb — unless it says how the moment was reached rather than what it
    is: "descend to and visit" is a visit. Two itineraries writing "have dinner" and "eat dinner"
    at the same place describe one evening, so the verb is read through the synonym classes above
    (narrow by design — merging two genuinely different moments deletes content).
    """
    words = re.findall(r"[a-z0-9]+", action.lower())
    if not words:
        return ""
    return _in_its_own_words(_stem(_past_the_approach(words)[0]))


def _past_the_approach(words: list[str]) -> list[str]:
    """What is left of an action once it stops saying how you got there."""
    if not words or words[0] not in _REACHED_BY_OPENERS:
        return words
    for connector in _REACHED_BY_CONNECTORS:
        joined = connector.split()
        at = len(joined) + 1
        if words[1: 1 + len(joined)] == joined and len(words) > at:
            return words[at:]
    return words


@lru_cache(maxsize=1)
def _synonyms() -> dict[str, str]:
    """The synonym table, with both sides stemmed the way a verb is."""
    return {
        _stem(verb): _stem(canonical)
        for canonical, verbs in _ACTION_SYNONYM_CLASSES.items()
        for verb in verbs
    }


def _in_its_own_words(verb: str) -> str:
    return _synonyms().get(verb, verb)


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _looks_like_one_moment(left: Key, right: Key) -> bool:
    """A verb match and enough shared place words. An approximation, by design."""
    if left.verb != right.verb or not left.verb:
        return False
    if not _about_the_same_thing(left, right):
        return False
    one, two = set(left.place), set(right.place)
    if not one or not two:
        return False
    if one <= two or two <= one:
        return True
    return len(one & two) / len(one | two) >= SIMILARITY


def _about_the_same_thing(left: Key, right: Key) -> bool:
    """Whether a synonym may stand in for the word the itinerary used.

    Two itineraries that wrote the same verb are taken at their word. Where the words differ and
    only the synonym table made them meet, the actions have to be about the same thing as well —
    the verb is not the moment, the object is.
    """
    if left.said == right.said:
        return True
    if not left.about and not right.about:
        return True
    return bool(left.about & right.about)


def _connected(keyed: list[tuple[str, Key]]) -> list[set[str]]:
    """Connected components over `_looks_like_one_moment`, independent of order."""
    parent = {atom_id: atom_id for atom_id, _ in keyed}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for index, (atom_id, key) in enumerate(keyed):
        for other_id, other_key in keyed[index + 1:]:
            if _looks_like_one_moment(key, other_key):
                left, right = find(atom_id), find(other_id)
                if left != right:
                    parent[max(left, right)] = min(left, right)

    memberships: dict[str, set[str]] = {}
    for atom_id, _ in keyed:
        memberships.setdefault(find(atom_id), set()).add(atom_id)
    return list(memberships.values())


# ── DB-facing wrapper (impure) — everything above this line is a pure function ─────────────

async def run_segment_matching(tenant_id: str, pool) -> dict:
    """Rebuild one tenant's Segments from its current atoms. Called right after T5 completes for
    ANY of the tenant's tour versions (Linear AA-509 — Segments span every tour of one tenant),
    so this recomputes over the tenant's WHOLE atom set, not just the tour that just atomized.

    Excludes: soft-deleted atoms, empty-day markers (`is_empty_marker`), and any atom whose
    place/action are still NULL (atomized before migration 129 and not yet re-atomized — STEP0
    mục 4/migration 129 comment: no backfill, same precedent as itinerary_day).
    """
    async with pool.acquire() as conn:
        atom_rows = await conn.fetch("""
            SELECT atom_id, tour_id, itinerary_day, place, action
            FROM acp_contract.tour_atoms
            WHERE owner_scope = $1 AND NOT deleted AND NOT is_empty_marker
              AND place IS NOT NULL AND action IS NOT NULL
        """, tenant_id)
        assigned_rows = await conn.fetch("""
            SELECT asm.atom_id, asm.segment_id
            FROM acp_contract.atom_segment_member asm
            JOIN acp_contract.atom_segment asg ON asg.segment_id = asm.segment_id
            WHERE asg.tenant_id = $1::uuid
        """, tenant_id)

    atoms = [
        SegmentAtom(r["atom_id"], str(r["tour_id"]), r["itinerary_day"], r["place"], r["action"])
        for r in atom_rows
    ]
    assigned = {r["atom_id"]: r["segment_id"] for r in assigned_rows}

    segments, aliases = reconcile_ids(derive_segments(tenant_id, atoms), assigned)
    live_ids = {segment.id for segment in segments}
    alias_rows = [(was, target) for was, target in aliases.items() if target in live_ids]

    async with pool.acquire() as conn:
        async with conn.transaction():
            # atom_segment: UPSERT-only, never DELETEd (module docstring + migration 129 comment
            # — required by atom_segment_alias's own FK, an id that "gave way" still has to
            # exist as a row).
            if segments:
                await conn.executemany("""
                    INSERT INTO acp_contract.atom_segment
                        (segment_id, tenant_id, canonical_place, canonical_action)
                    VALUES ($1, $2::uuid, $3, $4)
                    ON CONFLICT (segment_id) DO UPDATE SET
                        canonical_place = excluded.canonical_place,
                        canonical_action = excluded.canonical_action
                """, [(s.id, tenant_id, s.place, s.action) for s in segments])

            # atom_segment_member: membership is fully derived, so fully rebuilt for this
            # tenant's segments every run — safe because every segment_id being deleted-from
            # here is an existing row in atom_segment (never itself deleted), and every
            # segment_id being inserted-into was just UPSERTed above.
            await conn.execute("""
                DELETE FROM acp_contract.atom_segment_member
                WHERE segment_id IN (
                    SELECT segment_id FROM acp_contract.atom_segment WHERE tenant_id = $1::uuid
                )
            """, tenant_id)
            if segments:
                await conn.executemany("""
                    INSERT INTO acp_contract.atom_segment_member (segment_id, atom_id)
                    VALUES ($1, $2)
                """, [(s.id, atom_id) for s in segments for atom_id in s.atom_ids])

            if alias_rows:
                await conn.executemany("""
                    INSERT INTO acp_contract.atom_segment_alias
                        (segment_id_old, segment_id_canonical)
                    VALUES ($1, $2)
                    ON CONFLICT (segment_id_old) DO UPDATE SET
                        segment_id_canonical = excluded.segment_id_canonical
                """, alias_rows)
                # An alias whose target has itself since given way (this run, or a prior one)
                # follows it on — mirrors aa_social.stages.atoms._store_segments()'s own 2-pass
                # chain-resolve, scoped to this tenant's own segment_id space.
                await conn.execute("""
                    UPDATE acp_contract.atom_segment_alias outer_a
                    SET segment_id_canonical = inner_a.segment_id_canonical
                    FROM acp_contract.atom_segment_alias inner_a
                    JOIN acp_contract.atom_segment s ON s.segment_id = outer_a.segment_id_old
                    WHERE inner_a.segment_id_old = outer_a.segment_id_canonical
                      AND s.tenant_id = $1::uuid
                """, tenant_id)
                await conn.execute("""
                    DELETE FROM acp_contract.atom_segment_alias
                    WHERE segment_id_old = segment_id_canonical
                """)

    return {"segments": len(segments), "atoms": len(atoms), "aliases": len(alias_rows)}
