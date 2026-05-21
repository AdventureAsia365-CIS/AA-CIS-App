"""Unit tests for services/acp_s4_blog/sample_loader.py (AA-84)."""
import pytest
from services.acp_s4_blog.sample_loader import load_samples, compute_style_metrics, get_sample_metrics


def test_samples_load():
    samples = load_samples()
    assert len(samples) >= 3, f"Expected 3+ samples, got {len(samples)}"
    assert "blog1_cycling_korea" in samples
    assert "blog2_sanmani_trail" in samples
    assert "social_content_korea" in samples


def test_sample_word_count():
    samples = load_samples()
    for name, content in samples.items():
        if "blog" in name:
            wc = len(content.split())
            assert wc >= 1500, f"{name} too short: {wc} words"


def test_compute_style_metrics():
    text = (
        "## Section One\n\n"
        "This is a sentence. Another sentence here.\n\n"
        "### Subsection\n\n"
        "Paragraph two with 500m trail and 3 days journey."
    )
    metrics = compute_style_metrics(text)
    assert "avg_sentence_length" in metrics
    assert "proof_point_density" in metrics
    assert metrics["h2_count"] == 1
    assert metrics["h3_count"] == 1
    assert metrics["word_count"] > 0


def test_get_sample_metrics():
    metrics = get_sample_metrics()
    assert len(metrics) >= 3
    for name, m in metrics.items():
        assert m["word_count"] > 0
        assert "avg_sentence_length" in m
        assert "proof_point_density" in m
        assert "faq_depth" in m


def test_proof_point_detection():
    text = "The trail climbs 1200m over 3 days covering 45km total distance."
    metrics = compute_style_metrics(text)
    assert metrics["proof_point_density"] > 0


def test_faq_detection():
    text = "**Q: How fit do I need to be?\n\n1. Is this suitable for beginners?\n\nSome text."
    metrics = compute_style_metrics(text)
    assert metrics["faq_depth"] >= 1
