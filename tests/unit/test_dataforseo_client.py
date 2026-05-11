import pytest
from services.seo_intelligence.dataforseo_client import DataForSEOClient

def test_parse_keywords_happy():
    client = DataForSEOClient(login="test", password="test")
    # DataForSEO search_volume returns flat list of keyword objects
    mock_data = {
        "tasks": [{"result": [
            {"keyword": "vietnam tour",   "search_volume": 5000},
            {"keyword": "vietnam travel", "search_volume": 3000},
        ]}]
    }
    result = client._parse_keywords(mock_data)
    assert "vietnam tour" in result["top_keywords"]
    assert result["search_volumes"]["vietnam tour"] == 5000

def test_parse_keywords_empty():
    client = DataForSEOClient(login="test", password="test")
    assert client._parse_keywords({}) == {}

def test_parse_paa_happy():
    client = DataForSEOClient(login="test", password="test")
    mock_data = {
        "tasks": [{"result": [{"items": [{
            "type": "people_also_ask",
            "items": [
                {"title": "Is Vietnam safe for tourists?"},
                {"title": "Best time to visit Vietnam?"},
            ]
        }]}]}]
    }
    result = client._parse_paa(mock_data)
    assert len(result) == 2
    assert "Is Vietnam safe for tourists?" in result

def test_parse_paa_empty():
    client = DataForSEOClient(login="test", password="test")
    assert client._parse_paa({}) == []
