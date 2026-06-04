"""Unit tests for S4.2 whitelist field extraction (AA-108)."""
from services.acp_s4_social.brief import extract_tour_fields, ALLOWED_TOUR_FIELDS


def test_allowed_fields_pass():
    tour = {
        'aa_name': 'Mekong Delta Explorer',
        'aa_subtitle': 'Journey through emerald waterways',
        'aa_summary': 'A 7-day immersive journey',
        'aa_highlights': ['Floating markets', 'Village homestay'],
        'aa_itineraries': [{'day': 1, 'title': 'Arrival'}],
        'duration': 7,
        'activities': ['kayaking', 'cycling'],
        'links': ['https://example.com/tour'],
    }
    result = extract_tour_fields(tour)
    assert set(result.keys()) == ALLOWED_TOUR_FIELDS
    assert result['aa_name'] == 'Mekong Delta Explorer'
    assert result['duration'] == 7


def test_sensitive_fields_blocked():
    tour = {
        'aa_name': 'Halong Bay Cruise',
        'aa_summary': 'Overnight cruise through karst limestone',
        'provider': 'Horizon Voyages',
        'price': 1200.00,
        'raw_operator': 'HV-HALONG-001',
    }
    result = extract_tour_fields(tour)
    assert 'provider' not in result
    assert 'price' not in result
    assert 'raw_operator' not in result
    assert result['aa_name'] == 'Halong Bay Cruise'
    assert result['aa_summary'] == 'Overnight cruise through karst limestone'


def test_unknown_future_field_blocked():
    tour = {
        'aa_name': 'Sapa Trek',
        'aa_highlights': ['Rice terraces', 'Ethnic villages'],
        'provider_raw_price': 'USD 850 pp',
    }
    result = extract_tour_fields(tour)
    assert 'provider_raw_price' not in result
    assert result['aa_name'] == 'Sapa Trek'
    assert result['aa_highlights'] == ['Rice terraces', 'Ethnic villages']


def test_empty_tour():
    result = extract_tour_fields({})
    assert result == {}
