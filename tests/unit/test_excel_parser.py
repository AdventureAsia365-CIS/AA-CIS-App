import pytest
import pandas as pd
import tempfile
import os
from services.ingestion.excel_parser import ExcelParser

# AA-343: use a real-length itinerary body so pandas/`_clean` never collapses it to something
# that could be confused with a short placeholder — closer to real supplier/export content.
_SOURCE_ITIN = "Day 1: Arrive Hanoi, transfer to hotel.\nDay 2: Halong Bay cruise, kayaking."
_AI_ITIN = "Embark on an unforgettable journey through the misty limestone karsts of Halong Bay..."

def make_excel(rows: list[dict], path: str):
    df = pd.DataFrame(rows)
    df.to_excel(path, index=False, engine="openpyxl")

def test_parse_basic():
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([
            {"Name": "Halong Bay Tour", "Country": "Vietnam", "Duration": "3 days"},
            {"Name": "Angkor Wat Trek", "Country": "Cambodia", "Duration": "2 days"},
        ], path)
        parser = ExcelParser(path, source_file="test.xlsx")
        records = parser.parse()
        assert len(records) == 2
        assert records[0]["src_name"] == "Halong Bay Tour"
        assert records[0]["country"] == "Vietnam"
        assert records[1]["src_name"] == "Angkor Wat Trek"
    finally:
        os.unlink(path)

def test_skip_row_without_name():
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([
            {"Name": "Valid Tour", "Country": "Thailand"},
            {"Name": None, "Country": "Vietnam"},   # ← skip này
            {"Name": "", "Country": "Laos"},        # ← skip này
        ], path)
        parser = ExcelParser(path, source_file="test.xlsx")
        records = parser.parse()
        assert len(records) == 1
        assert records[0]["src_name"] == "Valid Tour"
    finally:
        os.unlink(path)

def test_source_file_attached():
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{"Name": "Tour A", "Country": "Japan"}], path)
        parser = ExcelParser(path, source_file="raw-inbox/Supplier/file.xlsx")
        records = parser.parse()
        assert records[0]["source_file"] == "raw-inbox/Supplier/file.xlsx"
    finally:
        os.unlink(path)

def test_nan_becomes_none():
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{"Name": "Tour B", "Country": "India", "Duration": None}], path)
        parser = ExcelParser(path, source_file="test.xlsx")
        records = parser.parse()
        assert records[0]["duration"] is None
    finally:
        os.unlink(path)

def test_includes_excludes_alias_maps_to_inclusions_exclusions():
    """AA-247: 10/14 real supplier files use the shortened "Includes"/"Excludes" header
    instead of "Inclusions"/"Exclusions" — without this alias those two columns don't hit
    COLUMN_MAP and their data is silently dropped on ingest."""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{
            "Name": "Sapa Trek", "Country": "Vietnam",
            "Includes": "Guide, meals, transport",
            "Excludes": "Flights, insurance",
        }], path)
        parser = ExcelParser(path, source_file="test.xlsx")
        records = parser.parse()
        assert records[0]["inclusions"] == "Guide, meals, transport"
        assert records[0]["exclusions"] == "Flights, insurance"
    finally:
        os.unlink(path)

def test_inclusions_exclusions_full_word_still_works():
    """Regression guard: adding the includes/excludes alias must not break the existing
    full-word "Inclusions"/"Exclusions" header some supplier files already use."""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{
            "Name": "Sapa Trek", "Country": "Vietnam",
            "Inclusions": "Guide, meals, transport",
            "Exclusions": "Flights, insurance",
        }], path)
        parser = ExcelParser(path, source_file="test.xlsx")
        records = parser.parse()
        assert records[0]["inclusions"] == "Guide, meals, transport"
        assert records[0]["exclusions"] == "Flights, insurance"
    finally:
        os.unlink(path)


# ── AA-343: mapper collision (source vs. AA_* columns targeting src_itineraries) ──────────────

def test_t1_1_source_before_aa_itineraries_source_wins():
    """T1.1: SOURCE_ITINERARIES then AA_ITINERARIES (AA_* last, the real corrupted-file order)
    — src_itineraries must take SOURCE_ITINERARIES, never the AA_* content."""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{
            "Name": "Halong Bay Tour", "Country": "Vietnam",
            "Source_Itineraries": _SOURCE_ITIN,
            "AA_Itineraries": _AI_ITIN,
        }], path)
        parser = ExcelParser(path, source_file="test.xlsx")
        records = parser.parse()
        assert records[0]["src_itineraries"] == _SOURCE_ITIN
        assert _AI_ITIN not in records[0]["src_itineraries"]
    finally:
        os.unlink(path)


def test_t1_2_column_order_reversed_result_unchanged():
    """T1.2: reversing column order (AA_Itineraries before Source_Itineraries) must not change
    the outcome — resolution is priority-based, not order-based."""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{
            "Name": "Halong Bay Tour", "Country": "Vietnam",
            "AA_Itineraries": _AI_ITIN,
            "Source_Itineraries": _SOURCE_ITIN,
        }], path)
        parser = ExcelParser(path, source_file="test.xlsx")
        records = parser.parse()
        assert records[0]["src_itineraries"] == _SOURCE_ITIN
        assert _AI_ITIN not in records[0]["src_itineraries"]
    finally:
        os.unlink(path)


def test_t1_3_audit_status_column_rejected():
    """T1.3: a file carrying AUDIT_STATUS is an exported/reviewed file, not a raw upload —
    must be rejected outright (fail at the code level), not silently parsed."""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{
            "Name": "Halong Bay Tour", "Country": "Vietnam",
            "Audit_Status": "reviewed",
        }], path)
        parser = ExcelParser(path, source_file="test.xlsx")
        with pytest.raises(ValueError):
            parser.parse()
    finally:
        os.unlink(path)


def test_t1_4_plain_source_file_no_regression():
    """T1.4: a normal raw file with only ITINERARIES (no AA_* at all) parses exactly as before."""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{
            "Name": "Sapa Trek", "Country": "Vietnam",
            "Itineraries": _SOURCE_ITIN,
        }], path)
        parser = ExcelParser(path, source_file="test.xlsx")
        records = parser.parse()
        assert records[0]["src_itineraries"] == _SOURCE_ITIN
    finally:
        os.unlink(path)


def test_t1_5_aa_itineraries_alone_never_seeds_src_itineraries():
    """T1.5 (Nghiep, mandatory): AA_Itineraries present with NO corresponding real source column
    (no Source_Itineraries, no Itineraries) — src_itineraries must never be silently populated
    from AA_* content. This is the exact shape that produced the original 46-row corruption and
    previously had no test coverage."""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{
            "Name": "Halong Bay Tour", "Country": "Vietnam",
            "AA_Itineraries": _AI_ITIN,
        }], path)
        parser = ExcelParser(path, source_file="test.xlsx")
        records = parser.parse()
        assert records[0].get("src_itineraries") is None
        assert records[0].get("src_itineraries") != _AI_ITIN
    finally:
        os.unlink(path)


def test_t2_format_b_real_case_no_ai_prose_in_src_itineraries():
    """T2: reproduce the real corrupted-batch file shape (Format B: Source_Itineraries then
    AA_Itineraries, plus the other source/AA field pairs) and confirm src_itineraries — and the
    other src_* fields — never contain AI-rewritten prose."""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{
            "Name": "Halong Bay Tour", "Country": "Vietnam",
            "Source_Name": "Halong Bay Tour", "AA_Name": "Discreet Executive Halong Escape",
            "Source_Summary": "3-day cruise in Halong Bay.",
            "AA_Summary": "An exclusive voyage crafted for the discerning traveler...",
            "Source_Itineraries": _SOURCE_ITIN,
            "AA_Itineraries": _AI_ITIN,
        }], path)
        parser = ExcelParser(path, source_file="raw-inbox/format_b_export.xlsx")
        records = parser.parse()
        record = records[0]
        assert record["src_itineraries"] == _SOURCE_ITIN
        assert _AI_ITIN not in record["src_itineraries"]
        assert record["src_summary"] == "3-day cruise in Halong Bay."
        assert "discerning traveler" not in record["src_summary"]
    finally:
        os.unlink(path)
