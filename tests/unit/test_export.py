import pytest
from shared.repository.published_catalog_repository import PublishedCatalogRepository

# --- slug generation tests ---

def test_slug_basic():
    slug = PublishedCatalogRepository.generate_slug("Halong Bay Cruise", "Vietnam")
    assert slug == "halong-bay-cruise-vietnam"

def test_slug_no_country():
    slug = PublishedCatalogRepository.generate_slug("Angkor Wat Trek")
    assert slug == "angkor-wat-trek"

def test_slug_special_chars():
    slug = PublishedCatalogRepository.generate_slug("Bali's Best Tour!", "Indonesia")
    assert "!" not in slug
    assert "'" not in slug

def test_slug_multiple_spaces():
    slug = PublishedCatalogRepository.generate_slug("Sri  Lanka   Wildlife", "Sri Lanka")
    assert "--" not in slug

def test_slug_max_length():
    long_name = "A" * 200
    slug = PublishedCatalogRepository.generate_slug(long_name)
    assert len(slug) <= 120

def test_slug_lowercase():
    slug = PublishedCatalogRepository.generate_slug("VIETNAM LUXURY TOUR", "VIETNAM")
    assert slug == slug.lower()

def test_slug_unicode_stripped():
    slug = PublishedCatalogRepository.generate_slug("Hội An Ancient Town", "Vietnam")
    assert "ộ" not in slug
    assert "vietnam" in slug

def test_slug_no_leading_trailing_dash():
    slug = PublishedCatalogRepository.generate_slug("  Mekong Delta  ", "Vietnam")
    assert not slug.startswith("-")
    assert not slug.endswith("-")
