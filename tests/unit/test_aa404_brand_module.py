"""
tests/unit/test_aa404_brand_module.py — services/acp_produce/brand.py
(AA-404 writer-side wire: fetch_brand_rubric_text() moved out of
slot_runner.py into a shared leaf module so E2/E3/E4/E5 can import it too,
without inverting slot_runner.py's own import direction — see brand.py's
module docstring).

Behavioral coverage of fetch_brand_rubric_text() itself already lives in
test_aa404_brand_rubric_wire.py (imported via slot_runner.py's re-export, its
own pre-existing test path) — this file only confirms the MOVE didn't
introduce a second, drifting copy or break the import graph: brand.py is
importable directly (no cycle through generation.py/adapt.py/faq.py/
slot_runner.py), and slot_runner.py's re-exported name is the exact same
function object, not a duplicate implementation.
"""
from services.acp_produce import brand
from services.acp_produce.slot_runner import fetch_brand_rubric_text as slot_runner_fetch


def test_brand_module_importable_standalone():
    assert callable(brand.fetch_brand_rubric_text)
    assert brand.__all__ == ["fetch_brand_rubric_text"]


def test_slot_runner_reexports_the_same_function_object_not_a_copy():
    """slot_runner.py's `fetch_brand_rubric_text` name (kept for backward
    compatibility with existing `@patch("services.acp_produce.slot_runner.
    fetch_brand_rubric_text", ...)` test call sites) must be an import of
    brand.py's real implementation, never a second, independently-written
    copy that could silently drift from it."""
    assert slot_runner_fetch is brand.fetch_brand_rubric_text


def test_writer_modules_import_brand_module_without_cycle():
    """E2/E3/E4/E5 don't call fetch_brand_rubric_text() themselves (it's
    fetched once per slot by slot_runner.py and threaded down as a plain
    `str` parameter — see each module's own docstring) — but this confirms
    brand.py sits below every one of them in the import graph, so any of
    them COULD import it directly in the future without creating a cycle
    back through slot_runner.py."""
    import services.acp_produce.adapt  # noqa: F401
    import services.acp_produce.faq  # noqa: F401
    import services.acp_produce.generation  # noqa: F401
    import services.acp_produce.repair  # noqa: F401
