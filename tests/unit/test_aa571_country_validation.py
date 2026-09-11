"""AA-571 Việc 2B: OKINAWA alias in country_resolver + excel_parser stops silent-NULL loss.

Full-dataset audit (Linear AA-571) found OKINAWA in raw_tours.country — not covered by
COUNTRY_MASTER's alias list, unlike SRI-LANDKA (AA-313). Migration 149 backfilled the 1
pre-existing row; this alias stops a NEW upload from reproducing it.
"""
import os
import tempfile
from unittest.mock import patch

import pandas as pd

from shared.country_resolver import resolve_country, COUNTRY_MASTER
from services.ingestion.excel_parser import ExcelParser


def make_excel(rows: list[dict], path: str):
    pd.DataFrame(rows).to_excel(path, index=False, engine="openpyxl")


# ── country_resolver: new OKINAWA alias ───────────────────────────────────────

def test_resolve_okinawa_maps_to_japan():
    assert resolve_country("OKINAWA") == "Japan"
    assert resolve_country("Okinawa") == "Japan"


def test_resolve_okinawa_from_filename():
    assert resolve_country(None, "OKINAWA_tours.xlsx") == "Japan"


def test_country_master_has_okinawa_alias():
    assert "OKINAWA" in COUNTRY_MASTER["Japan"]


def test_existing_japan_aliases_unaffected_by_okinawa_addition():
    assert resolve_country("JAPAN") == "Japan"
    assert resolve_country("JAPANESE") == "Japan"


# ── excel_parser: unresolved country logs instead of silently going NULL ─────

def test_unresolved_country_still_null_but_logs_warning():
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{"Name": "Mystery Tour", "Country": "Neverland"}], path)
        with patch("services.ingestion.excel_parser.logger") as mock_logger:
            parser = ExcelParser(path, source_file="weird_region.xlsx")
            records = parser.parse()

        assert len(records) == 1
        assert records[0]["country"] is None  # unchanged: still NULL, not blocked here (Cách A)
        # AA-571 round 3: raw value preserved for later querying (migration 151)
        assert records[0]["country_raw_unresolved"] == "Neverland"
        mock_logger.warning.assert_any_call(
            "country_unresolved_null", file="weird_region.xlsx",
            raw_country="Neverland", tour_name="Mystery Tour",
        )
    finally:
        os.unlink(path)


def test_resolved_country_does_not_log_warning():
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{"Name": "Fuji Tour", "Country": "Japan"}], path)
        with patch("services.ingestion.excel_parser.logger") as mock_logger:
            parser = ExcelParser(path, source_file="japan.xlsx")
            records = parser.parse()

        assert records[0]["country"] == "Japan"
        assert records[0].get("country_raw_unresolved") is None
        for call in mock_logger.warning.call_args_list:
            assert call.args[0] != "country_unresolved_null"
    finally:
        os.unlink(path)


def test_empty_country_does_not_log_warning():
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = f.name
    try:
        make_excel([{"Name": "No Country Tour", "Country": None}], path)
        with patch("services.ingestion.excel_parser.logger") as mock_logger:
            parser = ExcelParser(path, source_file="no_country.xlsx")
            records = parser.parse()

        assert records[0]["country"] is None
        assert records[0].get("country_raw_unresolved") is None
        for call in mock_logger.warning.call_args_list:
            assert call.args[0] != "country_unresolved_null"
    finally:
        os.unlink(path)
