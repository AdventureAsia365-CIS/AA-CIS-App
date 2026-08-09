"""AA-306 — S1-from-atom: grounding/density gate, writer seam, retry loop.

No live DB / no live Bedrock: asyncpg mocked via the same pool.acquire()
context-manager shape used in test_aa299_atom_insert.py; generate_draft
patched at module level (services.content_generation.s1_from_atom.generate_draft)
so the retry loop is exercised without a real network call.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.content_generation.s1_from_atom import (
    DEFAULT_PERSONA, GroundingError, _GROUNDING_SYSTEM_PROMPT, _build_atom_pack, _entailment_violations,
    _flatten_gated_text, _itinerary_prose_texts, _persona_block, _row_to_atom, build_user_prompt,
    check_grounding, fetch_curated_atoms, generate_draft, generate_s1_from_atom,
)

TOUR_ID = "11111111-1111-1111-1111-111111111111"

ATOMS = [
    {"atom_id": "atom_aaaaaaaaaa", "text": "Ride a rickshaw through Chandni Chowk.",
     "activity_type": "culture", "emotional_hook": "chaos and colour", "season_note": None},
    {"atom_id": "atom_bbbbbbbbbb", "text": "Watch the Taj Mahal sunrise.",
     "activity_type": "culture", "emotional_hook": "golden hour", "season_note": None},
]
ATOM_TEXT = {a["atom_id"]: a["text"] for a in ATOMS}


def _make_pool(atom_rows):
    conn = AsyncMock()
    conn.fetch.return_value = atom_rows
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


def _row(atom_id, text, activity_type="culture", hook=None, season=None, itinerary_day=None):
    return {"atom_id": atom_id, "text": text, "activity_type": activity_type,
            "emotional_hook": hook, "season_note": season, "itinerary_day": itinerary_day}


# ── check_grounding: density + closed-world gate ────────────────────────────

def test_check_grounding_passes_dense_grounded_content():
    valid_ids = {"atom_aaaaaaaaaa", "atom_bbbbbbbbbb"}
    content = {
        "aa_subtitle": "Old Delhi and the Taj Mahal in one loop [R:atom_aaaaaaaaaa]",
        "aa_summary": "A rickshaw ride through Chandni Chowk [R:atom_aaaaaaaaaa] opens the trip, "
                       "closing with sunrise at the Taj Mahal [R:atom_bbbbbbbbbb].",
        "aa_highlights": ["Rickshaw through Chandni Chowk [R:atom_aaaaaaaaaa]",
                           "Taj Mahal at sunrise [R:atom_bbbbbbbbbb]"],
        "aa_itineraries": "",
    }
    gate = check_grounding(content, valid_ids, ATOM_TEXT)
    assert gate["closed_world_pass"] is True
    assert gate["density_pass"] is True
    assert gate["citation_count"] == 5  # 1 (subtitle) + 2 (summary) + 2 (highlights)
    assert gate["unknown_citations"] == []


def test_check_grounding_fails_on_unknown_atom_id():
    valid_ids = {"atom_aaaaaaaaaa"}
    content = {"aa_summary": "A rickshaw ride [R:atom_aaaaaaaaaa] and a made-up elephant trek [R:atom_zzzzzzzzzz]."}
    gate = check_grounding(content, valid_ids, ATOM_TEXT)
    assert gate["closed_world_pass"] is False
    assert gate["unknown_citations"] == ["atom_zzzzzzzzzz"]


def test_check_grounding_fails_on_zero_citations():
    valid_ids = {"atom_aaaaaaaaaa"}
    content = {"aa_summary": "A lovely trip with breathtaking views and unforgettable moments throughout."}
    gate = check_grounding(content, valid_ids, ATOM_TEXT)
    assert gate["citation_count"] == 0
    assert gate["density_pass"] is False


def test_check_grounding_fails_below_density_threshold():
    valid_ids = {"atom_aaaaaaaaaa"}
    # One citation, then >300 filler words with no further citation -> words_per_citation > 300.
    filler = " ".join(["word"] * 320)
    content = {"aa_summary": f"Opening claim [R:atom_aaaaaaaaaa]. {filler}"}
    gate = check_grounding(content, valid_ids, ATOM_TEXT)
    assert gate["citation_count"] == 1
    assert gate["words_per_citation"] > 300
    assert gate["density_pass"] is False


def test_check_grounding_ignores_seo_fields_not_in_gated_set():
    valid_ids = {"atom_aaaaaaaaaa"}
    content = {
        "aa_summary": "Grounded claim [R:atom_aaaaaaaaaa].",
        "seo_title": "Some ungated title with no citation at all here",
        "seo_meta": "Some ungated meta description with no citation whatsoever in it.",
    }
    gate = check_grounding(content, valid_ids, ATOM_TEXT)
    # word_count must reflect only the gated fields (aa_summary), not seo_title/seo_meta.
    assert gate["word_count"] == 2  # "Grounded" "claim" (citation tag itself isn't a word)


# ── check_grounding: entailment (AA-325/ADR-2026-033) ───────────────────────

def test_check_grounding_fails_on_fabricated_number_with_valid_tag():
    """The AA-325 production incident this gate exists to catch: a valid citation
    tag on a sentence that asserts a number the cited atom never states."""
    valid_ids = {"atom_aaaaaaaaaa"}
    content = {"aa_highlights": ["Ride an 800-year-old rickshaw through Chandni Chowk [R:atom_aaaaaaaaaa]"]}
    gate = check_grounding(content, valid_ids, ATOM_TEXT)
    assert gate["closed_world_pass"] is True  # tag itself is a real atom_id
    assert gate["entailment_pass"] is False
    assert gate["entailment_violations"][0]["novel_numbers"] == ["800"]


def test_check_grounding_passes_when_cited_number_matches_atom():
    valid_ids = {"atom_ccccccc0"}
    atom_text = {"atom_ccccccc0": "The Red Fort was built starting in 1638."}
    content = {"aa_summary": "The Red Fort construction began in 1638 [R:atom_ccccccc0]."}
    gate = check_grounding(content, valid_ids, atom_text)
    assert gate["entailment_pass"] is True
    assert gate["entailment_violations"] == []


def test_check_grounding_entailment_checks_union_of_multiple_citations():
    valid_ids = {"atom_a1", "atom_a2"}
    atom_text = {"atom_a1": "The temple was built in 1592.", "atom_a2": "The garden covers 3 hectares."}
    content = {"aa_summary": "Visit the temple built in 1592 and its adjoining "
                              "3-hectare garden [R:atom_a1][R:atom_a2]."}
    gate = check_grounding(content, valid_ids, atom_text)
    assert gate["entailment_pass"] is True


# ── AA-356: aa_itineraries day-block array — day is structural, not a claim ─

def test_itinerary_prose_texts_extracts_title_and_prose_excludes_day():
    val = [{"day": 1, "title": "Bolaven Plateau", "prose": "Cycle through the plateau."}]
    texts = _itinerary_prose_texts(val)
    assert texts == ["Bolaven Plateau", "Cycle through the plateau."]
    assert not any("1" in t for t in texts)  # the bare day number never appears


def test_itinerary_prose_texts_handles_multiple_day_blocks():
    val = [
        {"day": 1, "title": "Day one", "prose": "First day prose."},
        {"day": 2, "title": "Day two", "prose": "Second day prose."},
    ]
    texts = _itinerary_prose_texts(val)
    assert texts == ["Day one", "First day prose.", "Day two", "Second day prose."]


def test_itinerary_prose_texts_falls_back_to_flat_string():
    # Legacy shape / a model that ignores the array instruction — must not crash.
    assert _itinerary_prose_texts("Flat day-by-day prose, no structure.") == \
        ["Flat day-by-day prose, no structure."]


def test_itinerary_prose_texts_empty_or_none_returns_empty_list():
    assert _itinerary_prose_texts(None) == []
    assert _itinerary_prose_texts("") == []
    assert _itinerary_prose_texts([]) == []


def test_flatten_gated_text_excludes_bare_day_number_from_itinerary_array():
    content = {"aa_itineraries": [{"day": 3, "title": "T", "prose": "P."}]}
    flat = _flatten_gated_text(content)
    assert "3" not in flat  # the reported bug: day int leaking into gated text
    assert "T" in flat and "P." in flat


def test_check_grounding_does_not_flag_bare_day_number_as_novel_claim():
    # Reproduces the exact AA-356 bug shape: aa_itineraries as day-block array,
    # a cited sentence whose only "number" is the structural day field itself.
    valid_ids = {"atom_x1"}
    atom_text = {"atom_x1": "Cycle through the Bolaven Plateau to Paksong."}
    content = {
        "aa_itineraries": [
            {"day": 1, "title": "Bolaven Plateau",
             "prose": "The trip opens on the Bolaven Plateau [R:atom_x1]."},
        ],
    }
    gate = check_grounding(content, valid_ids, atom_text)
    assert gate["entailment_pass"] is True
    assert gate["entailment_violations"] == []


def test_check_grounding_still_catches_real_fabrication_inside_day_block_prose():
    # Safety-net regression: a REAL fabricated number inside prose (not the day
    # field) must still be caught — AA-356 must not weaken ADR-2026-033's
    # actual fabrication detection, only stop it from misreading structure.
    valid_ids = {"atom_x1"}
    atom_text = {"atom_x1": "Visit a hillside temple."}
    content = {
        "aa_itineraries": [
            {"day": 1, "title": "Hillside Temple",
             "prose": "Visit the 800-year-old hillside temple [R:atom_x1]."},
        ],
    }
    gate = check_grounding(content, valid_ids, atom_text)
    assert gate["entailment_pass"] is False
    assert gate["entailment_violations"][0]["novel_numbers"] == ["800"]


def test_check_grounding_still_catches_real_fabrication_in_day_block_title():
    # Entailment only examines CITED sentences (by design — uncited text isn't
    # checked at all, since there's nothing to validate it against), so the
    # fabricated number must sit in the same cited sentence as the tag.
    valid_ids = {"atom_x1"}
    atom_text = {"atom_x1": "Visit the waterfall."}
    content = {
        "aa_itineraries": [
            {"day": 1, "title": "The 22-Meter Waterfall [R:atom_x1]",
             "prose": "Visit the waterfall."},
        ],
    }
    gate = check_grounding(content, valid_ids, atom_text)
    assert gate["entailment_pass"] is False
    assert "22" in gate["entailment_violations"][0]["novel_numbers"]


def test_entailment_violations_direct_call_matches_check_grounding_behavior():
    atom_text = {"atom_x1": "Visit a hillside temple."}
    content = {
        "aa_itineraries": [
            {"day": 1, "title": "T", "prose": "The 800-year-old temple [R:atom_x1]."},
        ],
    }
    violations = _entailment_violations(content, atom_text)
    assert len(violations) == 1
    assert violations[0]["field"] == "aa_itineraries"
    assert violations[0]["novel_numbers"] == ["800"]


# ── build_user_prompt: atom pack renders every atom, no raw-itinerary leakage ─

def test_build_user_prompt_includes_all_atom_ids_and_no_feedback_block_by_default():
    prompt = build_user_prompt({"name": "Delhi Tour", "country": "India"}, ATOMS)
    assert "atom_aaaaaaaaaa" in prompt
    assert "atom_bbbbbbbbbb" in prompt
    assert "PREVIOUS ATTEMPT FEEDBACK" not in prompt


def test_build_user_prompt_includes_feedback_when_given():
    prompt = build_user_prompt({"name": "Delhi Tour", "country": "India"}, ATOMS, feedback="fix citations")
    assert "PREVIOUS ATTEMPT FEEDBACK" in prompt
    assert "fix citations" in prompt


# ── AA-355: fetch_curated_atoms selects + orders by itinerary_day ───────────

@pytest.mark.asyncio
async def test_fetch_curated_atoms_selects_and_orders_by_itinerary_day():
    pool, conn = _make_pool([_row("atom_aaaaaaaaaa", "text", itinerary_day=1)])
    await fetch_curated_atoms(TOUR_ID, pool)
    query = conn.fetch.call_args[0][0]
    assert "itinerary_day" in query
    assert "ORDER BY itinerary_day NULLS LAST, created_at" in query


def test_row_to_atom_carries_itinerary_day_through():
    row = _row("atom_aaaaaaaaaa", "text", itinerary_day=3)
    assert _row_to_atom(row)["itinerary_day"] == 3


def test_row_to_atom_itinerary_day_defaults_none_when_absent():
    # Plain dict with no "itinerary_day" key at all (pre-AA-355 row shape) — .get()
    # must not KeyError.
    row = {"atom_id": "atom_aaaaaaaaaa", "text": "text"}
    assert _row_to_atom(row)["itinerary_day"] is None


# ── AA-355: _build_atom_pack groups atoms into DAY N sections ──────────────

def test_build_atom_pack_groups_dated_atoms_under_day_headers_ascending():
    atoms = [
        _row_to_atom(_row("atom_bbbbbbbbbb", "Day 2 activity.", itinerary_day=2)),
        _row_to_atom(_row("atom_aaaaaaaaaa", "Day 1 activity.", itinerary_day=1)),
    ]
    pack = _build_atom_pack(atoms)
    assert pack.index("DAY 1:") < pack.index("atom_aaaaaaaaaa")
    assert pack.index("DAY 2:") < pack.index("atom_bbbbbbbbbb")
    assert pack.index("DAY 1:") < pack.index("DAY 2:")


def test_build_atom_pack_multiple_atoms_same_day_share_one_header():
    atoms = [
        _row_to_atom(_row("atom_aaaaaaaaaa", "Morning activity.", itinerary_day=1)),
        _row_to_atom(_row("atom_bbbbbbbbbb", "Afternoon activity.", itinerary_day=1)),
    ]
    pack = _build_atom_pack(atoms)
    assert pack.count("DAY 1:") == 1
    assert "atom_aaaaaaaaaa" in pack and "atom_bbbbbbbbbb" in pack


def test_build_atom_pack_undated_atoms_go_to_separate_section_not_a_day():
    atoms = [
        _row_to_atom(_row("atom_aaaaaaaaaa", "Dated activity.", itinerary_day=1)),
        _row_to_atom(_row("atom_bbbbbbbbbb", "Undated activity.", itinerary_day=None)),
    ]
    pack = _build_atom_pack(atoms)
    assert "UNDATED" in pack
    assert "DAY 1:" in pack
    # the undated atom must not appear inside the DAY 1 block
    day1_section = pack.split("UNDATED")[0]
    assert "atom_bbbbbbbbbb" not in day1_section


def test_build_atom_pack_all_undated_reproduces_flat_pre_aa355_shape():
    # ATOMS fixture has no itinerary_day key at all -> every atom falls back to
    # itinerary_day=None via _row_to_atom's .get(), landing in one UNDATED block.
    atoms = [_row_to_atom(a) for a in ATOMS]
    pack = _build_atom_pack(atoms)
    assert "DAY " not in pack
    assert "UNDATED" in pack
    assert "atom_aaaaaaaaaa" in pack and "atom_bbbbbbbbbb" in pack


# ── AA-355: build_user_prompt derives the day-count instruction from atoms ─

def test_build_user_prompt_states_exact_day_count_when_atoms_are_dated():
    atoms = [
        _row_to_atom(_row("atom_aaaaaaaaaa", "text", itinerary_day=1)),
        _row_to_atom(_row("atom_bbbbbbbbbb", "text", itinerary_day=2)),
    ]
    prompt = build_user_prompt({"name": "Tour", "country": "Laos"}, atoms)
    assert "exactly 2 day-block(s)" in prompt
    assert "DAY 1 to DAY 2" in prompt


def test_build_user_prompt_output_format_declares_day_block_array():
    # AA-356: OUTPUT JSON FORMAT must describe the array-of-{day,title,prose}
    # shape the model already produces once given day structure — not the
    # old flat-string example that contradicted DAY STRUCTURE.
    prompt = build_user_prompt({"name": "Delhi Tour", "country": "India"}, ATOMS)
    assert '"day":' in prompt
    assert '"title":' in prompt
    assert '"prose":' in prompt


def test_build_user_prompt_falls_back_to_undated_instruction_when_no_day_data():
    prompt = build_user_prompt({"name": "Delhi Tour", "country": "India"}, ATOMS)
    assert "No atom in this pack carries a known source day" in prompt


# ── persona layer: additive only, base grounding prompt untouched ───────────

def test_persona_block_is_additive_not_a_replacement():
    block = _persona_block(DEFAULT_PERSONA)
    assert DEFAULT_PERSONA in block
    assert _GROUNDING_SYSTEM_PROMPT not in block  # persona block never re-states the base prompt


# ── generate_draft seam: routes on model_tier ────────────────────────────────

def test_generate_draft_routes_to_claude_satellite_by_default():
    fake_result = MagicMock()
    fake_result.text = "{}"
    fake_result.model_used = "sonnet-4-6"
    fake_result.usage = {"input_tokens": 20, "output_tokens": 8}

    with patch("shared.llm_client.bedrock_satellite.invoke_claude", return_value=fake_result) as mock_invoke:
        result = generate_draft("sys", "user")  # DEFAULT_MODEL_TIER, no explicit model_tier

    mock_invoke.assert_called_once()
    assert result["provider"] == "bedrock-satellite"
    assert result["model_used"] == "satellite-sonnet-4-6"


def test_generate_draft_routes_to_claude_satellite_when_requested():
    fake_result = MagicMock()
    fake_result.text = "{}"
    fake_result.model_used = "sonnet-4-6"
    fake_result.usage = {"input_tokens": 20, "output_tokens": 8}

    with patch("shared.llm_client.bedrock_satellite.invoke_claude", return_value=fake_result) as mock_invoke:
        result = generate_draft("sys", "user", model_tier="claude")

    mock_invoke.assert_called_once()
    assert result["provider"] == "bedrock-satellite"
    assert result["model_used"] == "satellite-sonnet-4-6"


def test_generate_draft_rejects_palmyra_permanently():
    """AA-392: Palmyra X5 is permanently rejected (AA-337's measured 1 req/min
    channel-program throttle) — this must raise loudly, never silently route
    anywhere, so a stale caller-supplied model_tier="palmyra" can't slip back in."""
    with pytest.raises(ValueError, match="permanently rejected"):
        generate_draft("sys", "user", model_tier="palmyra")


def test_generate_draft_rejects_unknown_tier():
    with pytest.raises(ValueError):
        generate_draft("sys", "user", model_tier="gpt-4.1")


# ── generate_s1_from_atom: full flow with mocked pool + mocked writer ───────

@pytest.mark.asyncio
async def test_generate_s1_from_atom_no_atoms_raises_immediately():
    pool, conn = _make_pool([])
    with pytest.raises(GroundingError, match="No curated atoms"):
        await generate_s1_from_atom(TOUR_ID, {"name": "X", "country": "Y"}, pool)
    conn.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_generate_s1_from_atom_succeeds_first_try():
    atom_rows = [_row("atom_aaaaaaaaaa", "Ride a rickshaw through Chandni Chowk.")]
    pool, _ = _make_pool(atom_rows)

    good_content = {
        "aa_name": "Delhi Rickshaw Loop",
        "aa_subtitle": "A rickshaw ride through Chandni Chowk [R:atom_aaaaaaaaaa]",
        "aa_summary": "The trip opens with a rickshaw ride through Chandni Chowk [R:atom_aaaaaaaaaa].",
        "aa_highlights": ["Rickshaw ride through Chandni Chowk [R:atom_aaaaaaaaaa]"],
        "aa_itineraries": "",
    }
    fake_draft = {"text": json.dumps(good_content), "model_used": "satellite-sonnet-4-6",
                  "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}

    with patch("services.content_generation.s1_from_atom.generate_draft", return_value=fake_draft) as mock_gen:
        result = await generate_s1_from_atom(TOUR_ID, {"name": "Delhi Tour", "country": "India"}, pool)

    assert mock_gen.call_count == 1
    assert result["retries"] == 0
    assert result["gate"]["closed_world_pass"] is True
    assert result["gate"]["density_pass"] is True
    assert result["atoms_used"] == ["atom_aaaaaaaaaa"]
    assert result["atoms_available"] == 1


@pytest.mark.asyncio
async def test_generate_s1_from_atom_retries_then_succeeds():
    atom_rows = [_row("atom_aaaaaaaaaa", "Ride a rickshaw through Chandni Chowk.")]
    pool, _ = _make_pool(atom_rows)

    bad_content = {"aa_summary": "A wonderful trip with breathtaking views and unforgettable moments."}
    good_content = {
        "aa_summary": "The trip opens with a rickshaw ride through Chandni Chowk [R:atom_aaaaaaaaaa].",
    }
    bad_draft = {"text": json.dumps(bad_content), "model_used": "satellite-sonnet-4-6",
                 "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}
    good_draft = {"text": json.dumps(good_content), "model_used": "satellite-sonnet-4-6",
                  "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}

    with patch("services.content_generation.s1_from_atom.generate_draft",
               side_effect=[bad_draft, good_draft]) as mock_gen:
        result = await generate_s1_from_atom(TOUR_ID, {"name": "Delhi Tour", "country": "India"}, pool)

    assert mock_gen.call_count == 2
    assert result["retries"] == 1
    # second call's user_prompt must carry feedback about the first failure
    second_call_user_prompt = mock_gen.call_args_list[1].args[1]
    assert "PREVIOUS ATTEMPT FEEDBACK" in second_call_user_prompt


@pytest.mark.asyncio
async def test_generate_s1_from_atom_retries_on_fabricated_number_then_succeeds():
    """AA-325 regression: a fabricated measurement with a valid tag must trigger a
    retry (not silently pass just because closed_world_pass/density_pass are green),
    and the retry feedback must name the fabricated number."""
    atom_rows = [_row("atom_aaaaaaaaaa", "Ride a rickshaw through Chandni Chowk.")]
    pool, _ = _make_pool(atom_rows)

    bad_content = {"aa_summary": "A rickshaw ride down the 12-kilometer stretch of Chandni Chowk [R:atom_aaaaaaaaaa]."}
    good_content = {"aa_summary": "The trip opens with a rickshaw ride through Chandni Chowk [R:atom_aaaaaaaaaa]."}
    bad_draft = {"text": json.dumps(bad_content), "model_used": "satellite-sonnet-4-6",
                 "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}
    good_draft = {"text": json.dumps(good_content), "model_used": "satellite-sonnet-4-6",
                  "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}

    with patch("services.content_generation.s1_from_atom.generate_draft",
               side_effect=[bad_draft, good_draft]) as mock_gen:
        result = await generate_s1_from_atom(TOUR_ID, {"name": "Delhi Tour", "country": "India"}, pool)

    assert mock_gen.call_count == 2
    assert result["retries"] == 1
    second_call_user_prompt = mock_gen.call_args_list[1].args[1]
    assert "12" in second_call_user_prompt  # feedback names the fabricated figure


@pytest.mark.asyncio
async def test_generate_s1_from_atom_exhausts_retries_raises_grounding_error():
    atom_rows = [_row("atom_aaaaaaaaaa", "Ride a rickshaw through Chandni Chowk.")]
    pool, _ = _make_pool(atom_rows)

    bad_content = {"aa_summary": "A wonderful trip with breathtaking views and no citations at all here."}
    bad_draft = {"text": json.dumps(bad_content), "model_used": "satellite-sonnet-4-6",
                 "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}

    with patch("services.content_generation.s1_from_atom.generate_draft", return_value=bad_draft) as mock_gen:
        with pytest.raises(GroundingError, match="grounding gate failed"):
            await generate_s1_from_atom(TOUR_ID, {"name": "Delhi Tour", "country": "India"}, pool)

    from services.content_generation.s1_from_atom import MAX_RETRIES
    assert mock_gen.call_count == MAX_RETRIES + 1


@pytest.mark.asyncio
async def test_generate_s1_from_atom_recovers_from_malformed_json():
    atom_rows = [_row("atom_aaaaaaaaaa", "Ride a rickshaw through Chandni Chowk.")]
    pool, _ = _make_pool(atom_rows)

    good_content = {"aa_summary": "The trip opens with a rickshaw ride through Chandni Chowk [R:atom_aaaaaaaaaa]."}
    malformed_draft = {"text": "not json at all {{{", "model_used": "satellite-sonnet-4-6",
                        "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}
    good_draft = {"text": json.dumps(good_content), "model_used": "satellite-sonnet-4-6",
                  "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}

    with patch("services.content_generation.s1_from_atom.generate_draft",
               side_effect=[malformed_draft, good_draft]) as mock_gen:
        result = await generate_s1_from_atom(TOUR_ID, {"name": "Delhi Tour", "country": "India"}, pool)

    assert mock_gen.call_count == 2
    assert result["retries"] == 1


# ── AA-289: prompt_version ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_s1_from_atom_sets_prompt_version_on_success():
    atom_rows = [_row("atom_aaaaaaaaaa", "Ride a rickshaw through Chandni Chowk.")]
    pool, _ = _make_pool(atom_rows)
    good_content = {"aa_summary": "A rickshaw ride through Chandni Chowk [R:atom_aaaaaaaaaa]."}
    good_draft = {"text": json.dumps(good_content), "model_used": "satellite-sonnet-4-6",
                  "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}

    with patch("services.content_generation.s1_from_atom.generate_draft", return_value=good_draft):
        result = await generate_s1_from_atom(TOUR_ID, {"name": "Delhi Tour", "country": "India"}, pool)

    assert result["prompt_version"] and len(result["prompt_version"]) == 8


@pytest.mark.asyncio
async def test_generate_s1_from_atom_prompt_version_changes_with_persona():
    """prompt_version hashes the stable prefix (grounding rules + persona) — a different
    persona is a genuinely different prompt template and must hash differently."""
    atom_rows = [_row("atom_aaaaaaaaaa", "Ride a rickshaw through Chandni Chowk.")]
    good_content = {"aa_summary": "A rickshaw ride through Chandni Chowk [R:atom_aaaaaaaaaa]."}
    good_draft = {"text": json.dumps(good_content), "model_used": "satellite-sonnet-4-6",
                  "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}

    pool_a, _ = _make_pool(atom_rows)
    pool_b, _ = _make_pool(atom_rows)
    with patch("services.content_generation.s1_from_atom.generate_draft", return_value=good_draft):
        result_a = await generate_s1_from_atom(
            TOUR_ID, {"name": "Delhi Tour", "country": "India"}, pool_a, persona="Persona A",
        )
        result_b = await generate_s1_from_atom(
            TOUR_ID, {"name": "Delhi Tour", "country": "India"}, pool_b, persona="Persona B, totally different",
        )

    assert result_a["prompt_version"] != result_b["prompt_version"]


@pytest.mark.asyncio
async def test_generate_s1_from_atom_grounding_error_carries_prompt_version_on_gate_exhausted():
    atom_rows = [_row("atom_aaaaaaaaaa", "Ride a rickshaw through Chandni Chowk.")]
    pool, _ = _make_pool(atom_rows)
    bad_content = {"aa_summary": "A wonderful trip with breathtaking views and no citations at all here."}
    bad_draft = {"text": json.dumps(bad_content), "model_used": "satellite-sonnet-4-6",
                 "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}

    with patch("services.content_generation.s1_from_atom.generate_draft", return_value=bad_draft):
        with pytest.raises(GroundingError) as exc_info:
            await generate_s1_from_atom(TOUR_ID, {"name": "Delhi Tour", "country": "India"}, pool)

    err = exc_info.value
    assert err.prompt_version and len(err.prompt_version) == 8
    assert err.gate is not None
    assert err.gate["density_pass"] is False


@pytest.mark.asyncio
async def test_generate_s1_from_atom_grounding_error_no_prompt_version_when_no_atoms():
    """The "no curated atoms" raise happens before any system prompt is built — there is
    nothing meaningful to log a prompt_version against, so it must stay None (the router's
    _log_run treats None as "skip logging", not "log an empty string")."""
    pool, _ = _make_pool([])

    with pytest.raises(GroundingError) as exc_info:
        await generate_s1_from_atom(TOUR_ID, {"name": "Delhi Tour", "country": "India"}, pool)

    assert exc_info.value.prompt_version is None
