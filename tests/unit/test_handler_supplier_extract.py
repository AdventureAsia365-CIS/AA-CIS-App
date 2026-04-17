from services.ingestion.handler import _extract_supplier

def test_extract_supplier_normal():
    assert _extract_supplier("raw-inbox/Exo/file.xlsx") == "Exo"

def test_extract_supplier_nested():
    assert _extract_supplier("raw-inbox/AsiaTrails/2026/tours.xlsx") == "AsiaTrails"

def test_extract_supplier_no_subfolder():
    assert _extract_supplier("raw-inbox/file.xlsx") is None
