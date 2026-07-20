"""
Unit tests for AA-313: COUNTRY_MASTER missing Pakistan + Sri Lanka typo alias.

Bug 1: COUNTRY_MASTER had no "Pakistan" entry at all -> PAKISTAN.xlsx 19/19 records
blocked with "MISSING FIELDS: country".
Bug 2: Company-wide source typo "SRI-LANDKA" (extra D) wasn't covered by Sri Lanka's
alias list -> SRI-LANDKA.xlsx 116/116 records blocked for the same reason.
"""
from shared.country_resolver import resolve_country, COUNTRY_MASTER


# ── Pakistan ─────────────────────────────────────────────────────────────────

def test_resolve_pakistan_from_cell_value_and_filename():
    assert resolve_country("Pakistan", "PAKISTAN.xlsx") == "Pakistan"


def test_resolve_pakistan_uppercase_cell_value():
    assert resolve_country("PAKISTAN") == "Pakistan"


def test_resolve_pakistan_iso_code():
    assert resolve_country("PAK") == "Pakistan"


def test_resolve_pakistan_from_filename_only():
    assert resolve_country(None, "PAKISTAN.xlsx") == "Pakistan"


# ── Sri Lanka typo ("SRI-LANDKA") ───────────────────────────────────────────

def test_resolve_sri_landka_typo_cell_value():
    assert resolve_country("SRI-LANDKA") == "Sri Lanka"


def test_resolve_sri_landka_typo_filename():
    assert resolve_country(None, "SRI-LANDKA.xlsx") == "Sri Lanka"


def test_resolve_sri_landka_typo_cell_and_filename_together():
    assert resolve_country("SRI-LANDKA", "SRI-LANDKA.xlsx") == "Sri Lanka"


def test_resolve_sri_landka_typo_lowercase_cell_value():
    assert resolve_country("sri-landka") == "Sri Lanka"


# ── Regression guard: pre-existing aliases still work ───────────────────────

def test_existing_sri_lanka_aliases_unaffected():
    assert resolve_country("SRI LANKA") == "Sri Lanka"
    assert resolve_country("SRILANKA") == "Sri Lanka"
    assert resolve_country("LKA") == "Sri Lanka"


def test_existing_entries_unaffected_by_pakistan_addition():
    assert resolve_country("JAPAN") == "Japan"
    assert resolve_country("KOR") == "South Korea"
    assert resolve_country("VNM") == "Vietnam"
    assert resolve_country("MDV") == "Maldives"


def test_unresolvable_value_still_returns_none():
    assert resolve_country("Atlantis", "unknown_file.xlsx") is None


def test_country_master_has_pakistan_and_sri_lanka_typo_alias():
    assert "Pakistan" in COUNTRY_MASTER
    assert "SRI-LANDKA" in COUNTRY_MASTER["Sri Lanka"]
    assert "SRI LANDKA" in COUNTRY_MASTER["Sri Lanka"]
