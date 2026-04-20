"""
scripts/seed_chromadb.py
Seed ChromaDB với 20 golden tours từ CIS_Golden_Tours_20_v1.xlsx

Usage:
    # Dev (local ChromaDB):
    CHROMA_MODE=local CHROMA_LOCAL_PATH=./chromadb_data \
        python scripts/seed_chromadb.py

    # Production (ChromaDB ECS):
    CHROMA_MODE=http CHROMA_HOST=<ecs-host> CHROMA_PORT=8000 \
        python scripts/seed_chromadb.py

    # Custom xlsx path:
    XLSX_PATH=/path/to/CIS_Golden_Tours_20_v1.xlsx \
        python scripts/seed_chromadb.py
"""
import os
import sys
import json

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from shared.rag import GoldenTourRepository

# ── Config ──────────────────────────────────────────────────────────────────
XLSX_PATH   = os.getenv("XLSX_PATH", "CIS_Golden_Tours_20_v1.xlsx")
TENANT_ID   = os.getenv("SEED_TENANT_ID", "aa-internal")
QUALITY_MIN = float(os.getenv("SEED_QUALITY_MIN", "7.0"))  # Only seed high-quality tours


# ── Column mapping from xlsx → internal fields ───────────────────────────────
# Adjust these if xlsx column names differ
COL_MAP = {
    # Source fields (before rewrite)
    "src_name":       ["Tour Name", "Name", "src_name", "tour_name"],
    "src_summary":    ["Summary", "Description", "src_summary"],
    "country":        ["Country", "Destination", "country"],
    "duration":       ["Duration", "duration"],

    # AA rewritten fields (after rewrite — ground truth)
    "aa_name":        ["AA Name", "Rewritten Name", "aa_name"],
    "aa_summary":     ["AA Summary", "Rewritten Summary", "aa_summary"],
    "aa_highlights":  ["AA Highlights", "Highlights", "aa_highlights"],
    "quality_score":  ["Quality Score", "Score", "quality_score"],
}


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Find first matching column name (case-insensitive)."""
    df_cols_lower = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in df_cols_lower:
            return df_cols_lower[candidate.lower()]
    return None


def parse_highlights(raw) -> list[str]:
    """Parse highlights from string or list."""
    if pd.isna(raw) or raw == "":
        return []
    if isinstance(raw, list):
        return raw
    # Try JSON parse
    try:
        parsed = json.loads(str(raw))
        if isinstance(parsed, list):
            return [str(h) for h in parsed]
    except Exception:
        pass
    # Fall back: split by newline or bullet
    lines = [
        line.strip().lstrip("•-*").strip()
        for line in str(raw).split("\n")
        if line.strip()
    ]
    return [l for l in lines if l]


def load_xlsx(path: str) -> pd.DataFrame:
    """Load xlsx, try all sheets, return first non-empty."""
    xl = pd.ExcelFile(path)
    print(f"Sheets found: {xl.sheet_names}")

    for sheet in xl.sheet_names:
        df = xl.parse(sheet)
        if not df.empty:
            print(f"Using sheet: '{sheet}' ({len(df)} rows, {len(df.columns)} cols)")
            print(f"Columns: {list(df.columns)}")
            return df

    raise ValueError(f"No non-empty sheet found in {path}")


def seed(xlsx_path: str, tenant_id: str) -> int:
    """
    Load xlsx and seed ChromaDB.
    Returns number of tours seeded.
    """
    print(f"\n{'='*60}")
    print(f"Seeding ChromaDB from: {xlsx_path}")
    print(f"Tenant: {tenant_id}")
    print(f"Min quality: {QUALITY_MIN}")
    print(f"{'='*60}\n")

    # Load file
    if not os.path.exists(xlsx_path):
        raise FileNotFoundError(f"xlsx not found: {xlsx_path}")

    df = load_xlsx(xlsx_path)

    # Map columns
    col_src_name      = find_column(df, COL_MAP["src_name"])
    col_country       = find_column(df, COL_MAP["country"])
    col_aa_name       = find_column(df, COL_MAP["aa_name"])
    col_aa_summary    = find_column(df, COL_MAP["aa_summary"])
    col_aa_highlights = find_column(df, COL_MAP["aa_highlights"])
    col_quality       = find_column(df, COL_MAP["quality_score"])
    col_src_summary   = find_column(df, COL_MAP["src_summary"])

    print("Column mapping:")
    print(f"  src_name      → {col_src_name}")
    print(f"  country       → {col_country}")
    print(f"  aa_name       → {col_aa_name}")
    print(f"  aa_summary    → {col_aa_summary}")
    print(f"  aa_highlights → {col_aa_highlights}")
    print(f"  quality_score → {col_quality}")
    print()

    if not col_src_name:
        raise ValueError(
            f"Cannot find 'src_name' column. Available: {list(df.columns)}"
        )

    # Init repository
    repo = GoldenTourRepository()

    seeded = 0
    skipped = 0

    for idx, row in df.iterrows():
        src_name = str(row.get(col_src_name, "")).strip() if col_src_name else ""
        if not src_name or src_name == "nan":
            skipped += 1
            continue

        # Quality filter
        quality = 0.0
        if col_quality:
            try:
                quality = float(row[col_quality])
            except (ValueError, TypeError):
                quality = 8.0  # assume good if no score

        if quality < QUALITY_MIN and col_quality:
            print(f"  SKIP [{idx+1:02d}] {src_name[:50]} (score: {quality})")
            skipped += 1
            continue

        # Build record
        data = {
            "id":            f"golden_{idx+1:03d}",
            "tenant_id":     tenant_id,
            "src_name":      src_name,
            "country":       str(row.get(col_country, "")).strip() if col_country else "",
            "aa_name":       str(row.get(col_aa_name, "")).strip() if col_aa_name else src_name,
            "aa_summary":    str(row.get(col_aa_summary, "")).strip() if col_aa_summary else "",
            "aa_highlights": parse_highlights(row.get(col_aa_highlights) if col_aa_highlights else None),
            "quality_score": quality,
        }

        try:
            doc_id = repo.insert(data)
            print(f"  ✓ [{idx+1:02d}] {src_name[:50]} → {doc_id}")
            seeded += 1
        except Exception as e:
            print(f"  ✗ [{idx+1:02d}] {src_name[:50]} ERROR: {e}")
            skipped += 1

    print(f"\n{'='*60}")
    print(f"Seed complete: {seeded} inserted, {skipped} skipped")
    print(f"Total in collection: {repo.count(tenant_id)}")
    print(f"{'='*60}\n")

    return seeded


def verify(tenant_id: str):
    """Quick verify: query a few examples."""
    print("\nVerification — querying similar tours:")
    repo = GoldenTourRepository()

    test_queries = [
        ("Vietnam", "Ha Long Bay cruise"),
        ("Japan", "Tokyo city tour"),
        ("Thailand", "Bangkok temples"),
    ]

    for country, name in test_queries:
        results = repo.query_similar(name, country, tenant_id, n_results=2)
        print(f"\n  Query: '{name}' ({country})")
        for r in results:
            print(f"    → {r['aa_name'][:50]} (similarity: {r['similarity']})")

    print(f"\nTotal golden tours: {repo.count(tenant_id)}")


if __name__ == "__main__":
    xlsx_path = XLSX_PATH

    # Allow CLI override: python seed_chromadb.py /path/to/file.xlsx
    if len(sys.argv) > 1:
        xlsx_path = sys.argv[1]

    try:
        count = seed(xlsx_path, TENANT_ID)
        if count > 0:
            verify(TENANT_ID)
        else:
            print("WARNING: 0 tours seeded — check xlsx column names above")
            sys.exit(1)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        print(f"Set XLSX_PATH env var or pass path as argument:")
        print(f"  python scripts/seed_chromadb.py /path/to/CIS_Golden_Tours_20_v1.xlsx")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        raise
