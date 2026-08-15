"""
tests/unit/test_aa404_repair_invariants.py — services/acp_produce/pipeline.py
::_build_repair_invariants() (AA-404: the piece-invariants object that
survives every repair round regardless of which gate triggered it).

Scope: this file tests ONLY the pure invariants-building function, not the
full async orchestrator (test_aa364_pipeline.py already covers wiring
end-to-end — see its test_facebook_piece_fails_only_f9_then_repair_round_
passes for the closure-level confirmation that `_repair` actually threads
`invariants` through to `repair_piece()`). `_build_repair_invariants()` is
pure/synchronous (no DB, no LLM), so these tests need no mocks at all.
"""
from services.acp_produce.models import Brief, KeywordRecord
from services.acp_produce.pipeline import _build_repair_invariants


def _brief(**overrides) -> Brief:
    defaults = dict(
        brief_id="brief-1", slot_id="slot-1", keyword="sapa trekking tours",
        demand=KeywordRecord(keyword="sapa trekking tours", location="US", volume=500, confidence="dfs"),
        required_h2s=["Intro", "Middle", "Wrap-up", "FAQ"],
        atoms_by_section={
            "Intro": ["atom_a"],
            "Middle": ["atom_b", "atom_c", "atom_d"],
            "Wrap-up": [],
            "FAQ": ["atom_e"],
        },
        framework="hub", cta_target="https://aa.example.com/tours/sapa",
    )
    defaults.update(overrides)
    return Brief(**defaults)


def test_facebook_hook_story_cta_sets_single_atom_and_cta_required_no_blog_fields():
    """AA-404 Part 2 real regression source (F9-social -> F8, 6x): a
    facebook piece must get single_atom_required=True + cta_required=True,
    resolved from `effective_framework` (already routed to "hook_story_cta"
    by `_resolve_framework()` upstream), never the caller's raw blog
    `framework` string. No section-ownership/required_h2s -- F3/F4 are
    blog-only gates, nothing to protect on a facebook piece."""
    inv = _build_repair_invariants("facebook", "hook_story_cta", _brief())

    assert inv.channel == "facebook"
    assert inv.single_atom_required is True
    assert inv.cta_required is True
    assert inv.long_section_title is None
    assert inv.short_para_section_title is None
    assert inv.required_h2s == []
    assert inv.aida_opening_section_title is None


def test_tiktok_channel_sets_no_facebook_only_invariants():
    """hook_beats_payoff (tiktok's framework) has no single-atom ceiling and
    no literal-CTA-phrase requirement -- both flags must stay False, unlike
    facebook's hook_story_cta."""
    inv = _build_repair_invariants("tiktok", "hook_beats_payoff", _brief())

    assert inv.single_atom_required is False
    assert inv.cta_required is False


def test_blog_hub_framework_sets_section_ownership_and_required_h2s():
    """AA-404 Part 1 real regression source (F4 -> F3, 3x) and the F9-blog
    -> F4 pattern (3x): a blog piece must get the SAME deterministic
    long/short section titles generate_draft()'s own
    _select_variance_owners() would have picked (most atoms = long, fewest
    = short), plus required_h2s minus the synthetic "FAQ" entry. hub isn't
    AIDA, so no opening/closing notes."""
    inv = _build_repair_invariants("blog", "hub", _brief())

    assert inv.channel == "blog"
    assert inv.long_section_title == "Middle"  # most atoms (3)
    assert inv.short_para_section_title == "Wrap-up"  # fewest atoms (0)
    assert inv.required_h2s == ["Intro", "Middle", "Wrap-up"]  # FAQ excluded
    assert inv.single_atom_required is False
    assert inv.cta_required is False
    assert inv.aida_opening_section_title is None
    assert inv.aida_closing_section_title is None


def test_blog_aida_framework_also_sets_opening_closing_section_titles():
    """AA-404 Part 3: an AIDA blog piece additionally gets
    aida_opening_section_title/aida_closing_section_title from the outline's
    first/last section (matching the same positional notes generate_draft()
    gives the opening/closing batch at generation time)."""
    inv = _build_repair_invariants("blog", "AIDA", _brief(framework="AIDA"))

    assert inv.aida_opening_section_title == "Intro"  # outline[0]
    assert inv.aida_closing_section_title == "Wrap-up"  # outline[-1]
    # AIDA is a blog framework, never hook_story_cta's facebook-only flags
    assert inv.single_atom_required is False
    assert inv.cta_required is False


def test_brief_none_for_blog_channel_produces_empty_invariants():
    """`brief=None` is documented as legitimate (pipeline.py's own
    docstring, e.g. a caller that never resolved a Brief) -- must degrade
    to an all-empty PieceInvariants, never raise."""
    inv = _build_repair_invariants("blog", "hub", None)

    assert inv.long_section_title is None
    assert inv.short_para_section_title is None
    assert inv.required_h2s == []


def test_facebook_with_shared_parent_brief_still_skips_blog_only_fields():
    """A facebook/tiktok Piece may carry its parent blog Piece's `Brief`
    (pipeline.py's own docstring: "shares its parent blog piece's Brief for
    cta_target only") -- section-ownership/required_h2s must NOT leak onto
    a facebook piece just because a Brief object happens to be present;
    those are blog-only concerns gated on `channel`, not on `brief is not
    None` alone."""
    inv = _build_repair_invariants("facebook", "hook_story_cta", _brief())

    assert inv.required_h2s == []
    assert inv.long_section_title is None


def test_empty_required_h2s_produces_no_section_ownership_crash():
    """A Brief with no required_h2s at all (build_outline() returns [])
    must not crash _select_variance_owners() (which raises ValueError on an
    empty outline) -- _build_repair_invariants() must guard this, same as
    generate_draft()'s own non-empty-outline check."""
    inv = _build_repair_invariants("blog", "hub", _brief(required_h2s=[], atoms_by_section={}))

    assert inv.long_section_title is None
    assert inv.short_para_section_title is None
    assert inv.required_h2s == []
