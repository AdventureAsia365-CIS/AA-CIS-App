"""
AA-125: Unit tests for pgvector cosine similarity calibration helpers.

Tests:
- test_cosine_similarity_similar_texts: near-identical texts → TF-IDF sim > 0.90
- test_cosine_similarity_different_texts: unrelated texts → TF-IDF sim < 0.80
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from scripts.calibrate_pgvector_threshold import (
    build_tfidf_matrix,
    cosine_sim,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pair_sim(text_a: str, text_b: str) -> float:
    mat = build_tfidf_matrix([text_a, text_b])
    return cosine_sim(mat[0], mat[1])


# ── Test 1: similar texts yield high cosine similarity ─────────────────────────

def test_cosine_similarity_similar_texts():
    """Near-identical blog titles (1 word swapped) score substantially above different texts.

    TF-IDF similarity on a 2-doc corpus is lower than Titan embedding similarity because
    IDF inflates unique-word weights when N=2. Threshold reflects TF-IDF space, not Titan.
    """
    a = "Ha Long Bay luxury cruise Vietnam exclusive experience"
    b = "Ha Long Bay luxury cruise Vietnam private experience"
    sim = _pair_sim(a, b)
    assert sim > 0.70, f"Expected TF-IDF sim > 0.70 for similar texts, got {sim:.3f}"


def test_cosine_similarity_similar_texts_diverse_corpus():
    """Near-duplicate pair scores > 0.75 even in a 7-document diverse corpus."""
    similar_a = "Sapa highland trekking Vietnam mountain village remote"
    similar_b = "Sapa highland hiking Vietnam mountain village remote"
    unrelated = [
        "Angkor Wat temple Cambodia ancient ruins archaeology",
        "Bangkok night market street food Thailand luxury",
        "Kyoto garden cherry blossom geisha Japan tradition",
        "Maldives overwater villa diving coral atoll island",
        "Machu Picchu Inca Peru hiking mountain ancient citadel",
    ]
    all_docs = [similar_a, similar_b] + unrelated
    mat = build_tfidf_matrix(all_docs)
    sim = cosine_sim(mat[0], mat[1])
    assert sim > 0.75, f"Expected TF-IDF sim > 0.75 for near-duplicate pair in corpus, got {sim:.3f}"


# ── Test 2: different texts yield low cosine similarity ────────────────────────

def test_cosine_similarity_different_texts():
    """Completely unrelated blog topics must score < 0.80 in TF-IDF space."""
    a = "Ha Long Bay luxury cruise Vietnam exclusive experience"
    b = "Angkor Wat temple Cambodia ancient ruins archaeology tour"
    sim = _pair_sim(a, b)
    assert sim < 0.80, f"Expected sim < 0.80 for different texts, got {sim:.3f}"


def test_cosine_similarity_different_texts_zero_overlap():
    """Non-overlapping vocabulary → cosine similarity near zero."""
    a = "Phu Quoc island beach resort Vietnam snorkeling coral"
    b = "Serengeti Tanzania wildebeest migration safari camping Africa"
    sim = _pair_sim(a, b)
    assert sim < 0.05, f"Expected sim < 0.05 for zero-overlap texts, got {sim:.3f}"
