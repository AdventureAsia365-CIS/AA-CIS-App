import pytest
import pandas as pd
import tempfile
import os
from services.ingestion.excel_parser import ExcelParser

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
