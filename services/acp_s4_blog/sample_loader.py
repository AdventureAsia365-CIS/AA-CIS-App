"""
Lazy loader for benchmark samples used by ValidatorAgent (AA-80).
Calculates style metrics for cosine similarity comparison.

Source: Ms. Thư's stage-4 pipeline production output (May 2026).
Benchmark thresholds defined in compiled_writer_rules.json v2.0.
"""
import re
from functools import lru_cache
from pathlib import Path

SAMPLES_DIR = Path(__file__).parent / "samples"


@lru_cache(maxsize=None)
def load_samples() -> dict[str, str]:
    """Load all .md sample files. Cached after first load."""
    samples = {}
    for f in sorted(SAMPLES_DIR.glob("*.md")):
        if f.name != "README.md":
            samples[f.stem] = f.read_text(encoding="utf-8")
    return samples


def compute_style_metrics(text: str) -> dict:
    """
    Compute style metrics for cosine similarity comparison against benchmark samples.
    All counts are raw integers; normalization done by caller for cosine distance.
    """
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    h2_count = len(re.findall(r"^## ", text, re.MULTILINE))
    h3_count = len(re.findall(r"^### ", text, re.MULTILINE))

    faq_depth = len(re.findall(r"^\*\*Q:", text, re.MULTILINE)) + len(
        re.findall(r"^\d+\.\s+.+\?", text, re.MULTILINE)
    )

    # Proof points: numbers with units (km, m, ft, %, USD, days, hours, mins)
    proof_points = len(
        re.findall(
            r"\b\d+(?:[.,]\d+)?(?:\s*(?:km|m|ft|%|USD|days?|hours?|mins?))\b",
            text,
            re.IGNORECASE,
        )
    )

    word_count = len(text.split())

    return {
        "avg_sentence_length": sum(len(s.split()) for s in sentences) / max(len(sentences), 1),
        "avg_paragraph_length": sum(len(p.split()) for p in paragraphs) / max(len(paragraphs), 1),
        "h2_count": h2_count,
        "h3_count": h3_count,
        "h2_h3_ratio": h2_count / max(h3_count, 1),
        "faq_depth": faq_depth,
        "proof_point_density": proof_points / max(word_count / 100, 1),
        "word_count": word_count,
    }


def get_sample_metrics() -> dict[str, dict]:
    """Return style metrics for all loaded benchmark samples."""
    return {name: compute_style_metrics(content) for name, content in load_samples().items()}
