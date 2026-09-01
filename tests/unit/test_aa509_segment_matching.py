"""AA-509 — Segment: derive_segments()/reconcile_ids() pure-function port from Ms. Thư's
aa-social-media (src/aa_social/segments.py), adapted for AA-CIS's real tour_atoms schema
(place/action columns added this same task) and multi-tenant _mint().

STEP0: docs/claude_audit/AA-509-step0-schema-matching-investigation.md.
Implementation notes: docs/implementation-notes/AA-509.md.
"""
from services.acp_contract.segment_matching import (
    SegmentAtom, derive_segments, reconcile_ids,
)

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"


def _atom(atom_id, tour_id, day, place, action):
    return SegmentAtom(atom_id=atom_id, tour_id=tour_id, day=day, place=place, action=action)


def test_same_place_different_action_not_merged():
    """Two atoms at the same place but genuinely different activities stay 2 Segments — the
    exact false-merge ADR 0002/STEP0 flagged as the risk of grouping on place alone."""
    atoms = [
        _atom("a1", "tour1", 1, "the old temple", "visit"),
        _atom("a2", "tour1", 1, "the old temple", "eat lunch"),
    ]
    segments = derive_segments(TENANT_A, atoms)
    assert len(segments) == 2
    assert {s.atom_ids for s in segments} == {("a1",), ("a2",)}


def test_same_place_synonym_action_merged():
    """"eat" and "have" are one synonym class (action-verbs.toml, ported) — two itineraries
    describing the same meal at the same place merge into one Segment."""
    atoms = [
        _atom("a1", "tour1", 1, "the ryokan", "eat dinner"),
        _atom("a2", "tour2", 1, "the ryokan", "have dinner"),
    ]
    segments = derive_segments(TENANT_A, atoms)
    assert len(segments) == 1
    assert segments[0].atom_ids == ("a1", "a2")


def test_different_place_same_action_not_merged():
    """Same verb, two different places (below the 0.5 Jaccard threshold) — not one moment."""
    atoms = [
        _atom("a1", "tour1", 1, "Magome", "walk the Nakasendo trail"),
        _atom("a2", "tour1", 2, "Narai", "walk the village street"),
    ]
    segments = derive_segments(TENANT_A, atoms)
    assert len(segments) == 2


def test_cross_tenant_same_content_does_not_collide_segment_id():
    """AA-509's own required adaptation (module docstring item 1, same class of bug AA-508 fixed
    for tour_atoms.atom_id): two tenants describing the identical place+action must NOT derive
    the same segment_id, or one tenant's UPSERT would silently claim the other's row."""
    atoms = [_atom("a1", "tour1", 1, "Magome", "walk to Tsumago")]
    seg_a = derive_segments(TENANT_A, atoms)[0]
    seg_b = derive_segments(TENANT_B, atoms)[0]
    assert seg_a.id != seg_b.id


def test_reconcile_ids_stable_across_runs_with_no_new_atoms():
    """Running derive+reconcile twice with the same atoms and the same `assigned` (as if
    segment_matching.py ran twice back-to-back with nothing changed) yields identical ids —
    ADR 0002's core guarantee."""
    atoms = [
        _atom("a1", "tour1", 1, "Magome", "walk to Tsumago"),
        _atom("a2", "tour1", 2, "Halong Bay", "kayak the caves"),
    ]
    first, _ = reconcile_ids(derive_segments(TENANT_A, atoms), {})
    assigned = {atom_id: seg.id for seg in first for atom_id in seg.atom_ids}

    second, aliases = reconcile_ids(derive_segments(TENANT_A, atoms), assigned)

    assert {s.id for s in first} == {s.id for s in second}
    assert aliases == {}


def test_reconcile_ids_keeps_id_when_a_bridging_atom_merges_two_segments():
    """A 3rd atom later bridges two previously-separate Segments into one — the id derived from
    the newly-merged group's own content is not what's kept (ADR 0002: an id is only ever minted
    once, on first sight); instead one of the two PRIOR ids is kept (deterministically, by sorted
    order over the two equally-sized claims) and the other comes back as an alias."""
    atoms_run1 = [
        _atom("a1", "tour1", 1, "the grand old temple", "visit"),
        _atom("a2", "tour2", 1, "the sacred temple ruins", "visit"),
    ]
    first, _ = reconcile_ids(derive_segments(TENANT_A, atoms_run1), {})
    assert len(first) == 2  # place Jaccard 1/5 = 0.2, below the 0.5 threshold — not merged yet
    assigned = {atom_id: seg.id for seg in first for atom_id in seg.atom_ids}
    id_1, id_2 = sorted(s.id for s in first)

    # A 3rd atom naming just "temple" is a place-subset of BOTH prior Segments' places, and
    # shares their verb — bridges the two into one connected component.
    atoms_run2 = atoms_run1 + [_atom("a3", "tour3", 1, "temple", "visit")]
    second, aliases = reconcile_ids(derive_segments(TENANT_A, atoms_run2), assigned)

    assert len(second) == 1
    assert set(second[0].atom_ids) == {"a1", "a2", "a3"}
    # One of the two prior ids survives; the other resolves via the aliases dict. The freshly
    # re-derived id (from "temple"/"visit" alone) is NOT what's kept — ADR 0002's own guarantee.
    assert second[0].id in (id_1, id_2)
    surviving = second[0].id
    given_way = id_2 if surviving == id_1 else id_1
    assert aliases.get(given_way) == surviving


def test_atoms_with_empty_action_never_merge():
    """Two atoms at the same place, both with an unreadable/empty action (`_leading_verb`
    returns "" for no words) — never accidentally merge with each other or anything else:
    `_looks_like_one_moment()` requires a real, shared, non-empty verb (`not left.verb` is
    checked explicitly), not just verb equality."""
    atoms = [
        _atom("a1", "tour1", 1, "the market", ""),
        _atom("a2", "tour1", 1, "the market", ""),
        _atom("a3", "tour1", 1, "the market", "browse the stalls"),
    ]
    segments = derive_segments(TENANT_A, atoms)
    assert len(segments) == 3
