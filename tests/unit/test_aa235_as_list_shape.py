"""AA-235 — shape guard for _as_list.

Root cause: seo_context.keyword_ideas was stored as a JSON object {seed: null}
(empty DataForSEO) instead of an array. _as_list must collapse every non-list
shape (dict, dict-string, bad JSON, None) to [] so the FE [...spread] and the
BE keyword_ideas[:25] slice can never crash.
"""
from api.routers.admin_pipeline import _as_list


def test_list_passthrough():
    assert _as_list([{"kw": "x"}]) == [{"kw": "x"}]


def test_dict_string_to_empty():
    # BUG GỐC — a JSON object serialized as a string
    assert _as_list('{"seed": null}') == []


def test_object_doubled_key():
    # real DB case: empty DFS seed appended " tours" → {"<seed> tours": null}
    assert _as_list('{"South Korea tours tours": null}') == []


def test_valid_json_array_string():
    assert _as_list('[{"kw":"x"}]') == [{"kw": "x"}]


def test_invalid_json():
    assert _as_list("not json") == []


def test_none():
    assert _as_list(None) == []


def test_dict_object_direct():
    # dict object (not via string) → []
    assert _as_list({}) == []


def test_dict_object_nonempty():
    # non-empty dict still → [] (this is what 500'd export-docx via [:25] slice)
    assert _as_list({"a": 1}) == []


def test_empty_string():
    assert _as_list("") == []


def test_empty_list():
    assert _as_list([]) == []
