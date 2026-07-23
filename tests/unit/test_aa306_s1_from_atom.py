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
    DEFAULT_PERSONA, GroundingError, _GROUNDING_SYSTEM_PROMPT, _persona_block,
    build_user_prompt, check_grounding, generate_draft, generate_s1_from_atom,
)

TOUR_ID = "11111111-1111-1111-1111-111111111111"

ATOMS = [
    {"atom_id": "atom_aaaaaaaaaa", "text": "Ride a rickshaw through Chandni Chowk.",
     "activity_type": "culture", "emotional_hook": "chaos and colour", "season_note": None},
    {"atom_id": "atom_bbbbbbbbbb", "text": "Watch the Taj Mahal sunrise.",
     "activity_type": "culture", "emotional_hook": "golden hour", "season_note": None},
]


def _make_pool(atom_rows):
    conn = AsyncMock()
    conn.fetch.return_value = atom_rows
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool, conn


def _row(atom_id, text, activity_type="culture", hook=None, season=None):
    return {"atom_id": atom_id, "text": text, "activity_type": activity_type,
            "emotional_hook": hook, "season_note": season}


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
    gate = check_grounding(content, valid_ids)
    assert gate["closed_world_pass"] is True
    assert gate["density_pass"] is True
    assert gate["citation_count"] == 5  # 1 (subtitle) + 2 (summary) + 2 (highlights)
    assert gate["unknown_citations"] == []


def test_check_grounding_fails_on_unknown_atom_id():
    valid_ids = {"atom_aaaaaaaaaa"}
    content = {"aa_summary": "A rickshaw ride [R:atom_aaaaaaaaaa] and a made-up elephant trek [R:atom_zzzzzzzzzz]."}
    gate = check_grounding(content, valid_ids)
    assert gate["closed_world_pass"] is False
    assert gate["unknown_citations"] == ["atom_zzzzzzzzzz"]


def test_check_grounding_fails_on_zero_citations():
    valid_ids = {"atom_aaaaaaaaaa"}
    content = {"aa_summary": "A lovely trip with breathtaking views and unforgettable moments throughout."}
    gate = check_grounding(content, valid_ids)
    assert gate["citation_count"] == 0
    assert gate["density_pass"] is False


def test_check_grounding_fails_below_density_threshold():
    valid_ids = {"atom_aaaaaaaaaa"}
    # One citation, then >300 filler words with no further citation -> words_per_citation > 300.
    filler = " ".join(["word"] * 320)
    content = {"aa_summary": f"Opening claim [R:atom_aaaaaaaaaa]. {filler}"}
    gate = check_grounding(content, valid_ids)
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
    gate = check_grounding(content, valid_ids)
    # word_count must reflect only the gated fields (aa_summary), not seo_title/seo_meta.
    assert gate["word_count"] == 2  # "Grounded" "claim" (citation tag itself isn't a word)


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


# ── persona layer: additive only, base grounding prompt untouched ───────────

def test_persona_block_is_additive_not_a_replacement():
    block = _persona_block(DEFAULT_PERSONA)
    assert DEFAULT_PERSONA in block
    assert _GROUNDING_SYSTEM_PROMPT not in block  # persona block never re-states the base prompt


# ── generate_draft seam: routes on model_tier ────────────────────────────────

def test_generate_draft_routes_to_palmyra_by_default():
    fake_payload = {
        "choices": [{"message": {"content": "{}"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    fake_body = MagicMock()
    fake_body.read.return_value = json.dumps(fake_payload).encode()
    fake_client = MagicMock()
    fake_client.invoke_model.return_value = {"body": fake_body}

    with patch("services.content_generation.s1_from_atom.boto3.client", return_value=fake_client) as mock_boto:
        result = generate_draft("sys", "user", model_tier="palmyra")

    mock_boto.assert_called_once_with("bedrock-runtime", region_name="us-west-1")
    assert result["provider"] == "bedrock-acc2"
    assert result["model_used"] == "us.writer.palmyra-x5-v1:0"
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 5


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
    fake_draft = {"text": json.dumps(good_content), "model_used": "us.writer.palmyra-x5-v1:0",
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
    bad_draft = {"text": json.dumps(bad_content), "model_used": "us.writer.palmyra-x5-v1:0",
                 "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}
    good_draft = {"text": json.dumps(good_content), "model_used": "us.writer.palmyra-x5-v1:0",
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
async def test_generate_s1_from_atom_exhausts_retries_raises_grounding_error():
    atom_rows = [_row("atom_aaaaaaaaaa", "Ride a rickshaw through Chandni Chowk.")]
    pool, _ = _make_pool(atom_rows)

    bad_content = {"aa_summary": "A wonderful trip with breathtaking views and no citations at all here."}
    bad_draft = {"text": json.dumps(bad_content), "model_used": "us.writer.palmyra-x5-v1:0",
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
    malformed_draft = {"text": "not json at all {{{", "model_used": "us.writer.palmyra-x5-v1:0",
                        "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}
    good_draft = {"text": json.dumps(good_content), "model_used": "us.writer.palmyra-x5-v1:0",
                  "provider": "bedrock-acc2", "input_tokens": 100, "output_tokens": 50}

    with patch("services.content_generation.s1_from_atom.generate_draft",
               side_effect=[malformed_draft, good_draft]) as mock_gen:
        result = await generate_s1_from_atom(TOUR_ID, {"name": "Delhi Tour", "country": "India"}, pool)

    assert mock_gen.call_count == 2
    assert result["retries"] == 1
