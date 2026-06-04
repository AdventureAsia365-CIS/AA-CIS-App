#!/usr/bin/env python3
"""
AA-125: pgvector dedup threshold calibration for S4.1 Blog Engine.

Tries real DB data first (acp_silver_s4.blog_drafts with embeddings).
Falls back to synthetic TF-IDF pairs if DB unavailable or table is empty.

Bedrock Titan Embed v2 embedding space ≠ TF-IDF space.
Synthetic results validate methodology; Titan space calibration requires live DB.
"""
import asyncio
import os
import re
import sys
from collections import Counter
from typing import Optional

import numpy as np


# ── Synthetic test pairs ───────────────────────────────────────────────────────
# "Similar" = same destination + activity, 1-2 words swapped.
# "Different" = entirely unrelated region and activity.

SIMILAR_PAIRS = [
    ("Ha Long Bay luxury cruise Vietnam exclusive experience",
     "Ha Long Bay luxury cruise Vietnam private experience"),
    ("Sapa highland trekking Vietnam mountain village remote",
     "Sapa highland hiking Vietnam mountain village remote"),
    ("Hoi An ancient town Vietnam lantern festival evening",
     "Hoi An ancient town Vietnam lantern parade evening"),
    ("Mekong Delta boat tour Vietnam rice paddies scenery",
     "Mekong Delta boat cruise Vietnam rice paddies scenery"),
    ("Phu Quoc island beach resort Vietnam snorkeling coral",
     "Phu Quoc island beach resort Vietnam diving coral"),
    ("Hanoi old quarter street food Vietnam local tour",
     "Hanoi old quarter street food Vietnam local guide"),
    ("Da Nang beach luxury hotel Vietnam coastal resort",
     "Da Nang beach luxury hotel Vietnam coastal retreat"),
    ("Hue imperial citadel history Vietnam heritage ancient",
     "Hue imperial citadel history Vietnam heritage medieval"),
    ("Ninh Binh boat cave karst landscape Vietnam scenic",
     "Ninh Binh boat cave karst terrain Vietnam scenic"),
    ("Mai Chau valley trekking ethnic village Vietnam homestay",
     "Mai Chau valley walking ethnic village Vietnam homestay"),
    ("Phong Nha cave expedition Vietnam national park adventure",
     "Phong Nha cave exploration Vietnam national park adventure"),
    ("Con Dao island diving beach Vietnam coral reef pristine",
     "Con Dao island diving beach Vietnam coral reef untouched"),
    ("Mui Ne sand dune beach Vietnam desert resort sunset",
     "Mui Ne sand dune beach Vietnam desert villa sunset"),
    ("Nha Trang bay cruise snorkeling Vietnam reef beach",
     "Nha Trang bay cruise snorkeling Vietnam reef island"),
    ("Cat Ba island kayak limestone Vietnam adventure tour",
     "Cat Ba island kayak limestone Vietnam adventure trip"),
    ("Bac Ha market hill tribe trekking Vietnam highlands",
     "Bac Ha market hill tribe hiking Vietnam highlands"),
    ("Da Lat coffee plantation Vietnam highland garden flower",
     "Da Lat coffee plantation Vietnam highland farm flower"),
    ("Ho Chi Minh City Cu Chi tunnels war history Vietnam tour",
     "Ho Chi Minh City Cu Chi tunnels war history Vietnam guide"),
    ("Quy Nhon coastal beach retreat Vietnam fishing town",
     "Quy Nhon coastal beach resort Vietnam fishing town"),
    ("Ban Gioc waterfall border Vietnam China trek photography",
     "Ban Gioc waterfall border Vietnam China hike photography"),
]

DIFFERENT_PAIRS = [
    ("Ha Long Bay luxury cruise Vietnam exclusive experience",
     "Angkor Wat temple Cambodia ancient ruins archaeology tour"),
    ("Sapa highland trekking Vietnam mountain village remote",
     "Bangkok night market street food Thailand luxury shopping"),
    ("Hoi An ancient town Vietnam lantern festival evening",
     "Bali rice terrace monkey forest Indonesia temple ritual"),
    ("Mekong Delta boat tour Vietnam rice paddies scenery",
     "Singapore marina bay hotel business luxury conference travel"),
    ("Phu Quoc island beach resort Vietnam snorkeling coral",
     "Kyoto garden cherry blossom geisha Japan tradition season"),
    ("Hanoi old quarter street food Vietnam local tour",
     "Maldives overwater villa diving resort coral atoll island"),
    ("Da Nang beach luxury hotel Vietnam coastal resort",
     "Machu Picchu Inca Peru hiking mountain ancient citadel"),
    ("Hue imperial citadel history Vietnam heritage ancient",
     "Kenya safari Masai Mara wildlife photography Africa savanna"),
    ("Ninh Binh boat cave karst landscape Vietnam scenic",
     "Norwegian fjord glacier cruise midnight sun Europe luxury"),
    ("Mai Chau valley trekking ethnic village Vietnam homestay",
     "Dubai desert camel gold souk luxury skyscraper fountain"),
    ("Phong Nha cave expedition Vietnam national park adventure",
     "Amazon jungle river Brazil wildlife ecology expedition canopy"),
    ("Con Dao island diving beach Vietnam coral reef pristine",
     "Iceland aurora volcano glacier snowmobile expedition northern"),
    ("Mui Ne sand dune beach Vietnam desert resort sunset",
     "Paris fashion Eiffel Tower luxury hotel France culture"),
    ("Nha Trang bay cruise snorkeling Vietnam reef beach",
     "Swiss Alps ski resort fondue chocolate Zurich winter luxury"),
    ("Cat Ba island kayak limestone Vietnam adventure tour",
     "New York Broadway museum luxury penthouse city break culture"),
    ("Bac Ha market hill tribe trekking Vietnam highlands",
     "Morocco desert camel medina souq riad Marrakesh artisan craft"),
    ("Da Lat coffee plantation Vietnam highland garden flower",
     "Galapagos wildlife tortoise bird Ecuador island endemic unique"),
    ("Ho Chi Minh City Cu Chi tunnels war history Vietnam tour",
     "Scottish Highlands castle whisky distillery golf tour Europe"),
    ("Quy Nhon coastal beach retreat Vietnam fishing town",
     "Santorini Greece dome sunset cruise Aegean luxury caldera"),
    ("Ban Gioc waterfall border Vietnam China trek photography",
     "Serengeti Tanzania wildebeest migration safari camping Africa"),
]

THRESHOLDS = [0.80, 0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94, 0.96, 0.98]


# ── TF-IDF (pure numpy, no sklearn) ───────────────────────────────────────────

def _tokenize(text: str) -> list:
    return text.lower().split()


def build_tfidf_matrix(docs: list) -> np.ndarray:
    tokens_per_doc = [_tokenize(d) for d in docs]
    vocab = sorted({w for tokens in tokens_per_doc for w in tokens})
    word_idx = {w: i for i, w in enumerate(vocab)}
    N, V = len(docs), len(vocab)

    tf = np.zeros((N, V))
    for i, tokens in enumerate(tokens_per_doc):
        counts = Counter(tokens)
        total = len(tokens) or 1
        for w, c in counts.items():
            if w in word_idx:
                tf[i, word_idx[w]] = c / total

    df = np.zeros(V)
    for tokens in tokens_per_doc:
        for w in set(tokens):
            if w in word_idx:
                df[word_idx[w]] += 1
    idf = np.log((N + 1) / (df + 1)) + 1  # smoothed IDF (sklearn convention)

    tfidf = tf * idf
    norms = np.linalg.norm(tfidf, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return tfidf / norms


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # vectors already L2-normalised


# ── Threshold analysis (shared by real + synthetic paths) ─────────────────────

def run_threshold_analysis(pairs: list) -> float:
    """
    pairs: list of (text_a, text_b, similarity, label)
    label 1 = ground-truth duplicate, 0 = ground-truth unique.
    Returns recommended threshold (best F1).
    """
    n_pos = sum(1 for *_, lbl in pairs if lbl == 1)
    best_f1, best_thresh = 0.0, THRESHOLDS[0]

    print(
        f"\n{'Threshold':>10} | {'Precision':>10} | {'Recall':>8} | "
        f"{'F1':>8} | {'Dups caught':>13} | {'False blocks':>12}"
    )
    print("-" * 82)

    for thresh in THRESHOLDS:
        tp = sum(1 for *_, sim, lbl in [(a, b, s, l) for a, b, s, l in pairs] if lbl == 1 and sim >= thresh)
        fp = sum(1 for *_, sim, lbl in [(a, b, s, l) for a, b, s, l in pairs] if lbl == 0 and sim >= thresh)

        # Unpack properly
        tp = sum(1 for a, b, sim, lbl in pairs if lbl == 1 and sim >= thresh)
        fp = sum(1 for a, b, sim, lbl in pairs if lbl == 0 and sim >= thresh)
        fn = n_pos - tp

        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / n_pos if n_pos > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        marker = " ← current" if abs(thresh - 0.92) < 1e-9 else ""
        print(
            f"{thresh:>10.2f} | {precision:>10.3f} | {recall:>8.3f} | "
            f"{f1:>8.3f} | {tp:>5}/{n_pos:<6} | {fp:>12}{marker}"
        )

        if f1 > best_f1:
            best_f1 = f1
            best_thresh = thresh

    print(f"\nRecommended: {best_thresh:.2f}  (best F1 = {best_f1:.3f})")
    return best_thresh


# ── Synthetic benchmark ────────────────────────────────────────────────────────

def run_synthetic() -> float:
    print("=" * 82)
    print("AA-125 — pgvector Dedup Threshold Calibration  [SYNTHETIC TF-IDF mode]")
    print("=" * 82)
    print("Note: TF-IDF scores ≠ Titan Embed v2 scores. This validates methodology.")
    print(f"      {len(SIMILAR_PAIRS)} similar pairs + {len(DIFFERENT_PAIRS)} different pairs = "
          f"{len(SIMILAR_PAIRS) + len(DIFFERENT_PAIRS)} total")

    all_docs = [text for pair in SIMILAR_PAIRS + DIFFERENT_PAIRS for text in pair]
    mat = build_tfidf_matrix(all_docs)

    pairs: list = []
    for i, (a, b) in enumerate(SIMILAR_PAIRS):
        sim = cosine_sim(mat[i * 2], mat[i * 2 + 1])
        pairs.append((a, b, sim, 1))

    offset = len(SIMILAR_PAIRS) * 2
    for i, (a, b) in enumerate(DIFFERENT_PAIRS):
        sim = cosine_sim(mat[offset + i * 2], mat[offset + i * 2 + 1])
        pairs.append((a, b, sim, 0))

    sims_s = [sim for _, _, sim, lbl in pairs if lbl == 1]
    sims_d = [sim for _, _, sim, lbl in pairs if lbl == 0]
    print(f"\nSimilarity stats:")
    print(f"  Similar   pairs — min={min(sims_s):.3f}  max={max(sims_s):.3f}  "
          f"mean={sum(sims_s)/len(sims_s):.3f}")
    print(f"  Different pairs — min={min(sims_d):.3f}  max={max(sims_d):.3f}  "
          f"mean={sum(sims_d)/len(sims_d):.3f}")

    return run_threshold_analysis(pairs)


# ── Real DB benchmark ──────────────────────────────────────────────────────────

def _parse_pg_vector(s: str) -> np.ndarray:
    nums = [float(x) for x in re.findall(r"[-\d.e+]+", s)]
    return np.array(nums, dtype=np.float32)


async def _try_real_db(dsn: str) -> Optional[float]:
    try:
        import asyncpg
    except ImportError:
        print("  asyncpg not available — skipping real DB path.")
        return None

    print(f"  Connecting to DB...")
    try:
        conn = await asyncpg.connect(dsn, ssl="require", timeout=10)
    except Exception as exc:
        print(f"  DB connect failed: {exc}")
        return None

    try:
        rows = await conn.fetch(
            """
            SELECT draft_id::text, title,
                   content_embedding::text
            FROM acp_silver_s4.blog_drafts
            WHERE content_embedding IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 200
            """
        )
    except Exception as exc:
        print(f"  Query failed: {exc}")
        await conn.close()
        return None

    await conn.close()

    if len(rows) < 2:
        print(f"  Only {len(rows)} blog(s) with embeddings — need ≥2 for calibration.")
        return None

    print(f"  Fetched {len(rows)} blogs with embeddings.")

    records = []
    for r in rows:
        vec = _parse_pg_vector(r["content_embedding"])
        norm = np.linalg.norm(vec)
        records.append((r["draft_id"], r["title"], vec / norm if norm > 0 else vec))

    import random
    random.seed(42)
    indices = list(range(len(records)))
    sample = random.sample(indices, min(20, len(records)))

    pairs: list = []
    for i in range(len(sample)):
        for j in range(i + 1, len(sample)):
            _, title_a, vec_a = records[sample[i]]
            _, title_b, vec_b = records[sample[j]]
            sim = float(np.dot(vec_a, vec_b))
            # Ground truth: pairs with sim > 0.95 treated as duplicates
            label = 1 if sim > 0.95 else 0
            pairs.append((title_a, title_b, sim, label))

    n_dup = sum(1 for *_, lbl in pairs if lbl == 1)
    n_uniq = len(pairs) - n_dup
    sims = [sim for _, _, sim, _ in pairs]
    print(f"  Pairs: {len(pairs)} total | {n_dup} ground-truth dups | {n_uniq} unique")
    print(f"  Similarity range: min={min(sims):.3f}  max={max(sims):.3f}  "
          f"mean={sum(sims)/len(sims):.3f}")

    return run_threshold_analysis(pairs)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> float:
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        print("DATABASE_URL found — attempting real DB calibration...")
        result = asyncio.run(_try_real_db(dsn))
        if result is not None:
            return result
        print("Falling back to synthetic calibration...\n")

    return run_synthetic()


if __name__ == "__main__":
    recommended = main()
    current = 0.92

    print("\n" + "=" * 82)
    if abs(recommended - current) > 1e-9:
        print(f"ACTION REQUIRED: recommended threshold {recommended:.2f} != current {current:.2f}")
        print("  Update _DEDUP_THRESHOLD in services/acp_s4/embeddings.py")
    else:
        print(f"NO CHANGE: current threshold {current:.2f} matches recommendation.")
    print("=" * 82)

    sys.exit(0)
