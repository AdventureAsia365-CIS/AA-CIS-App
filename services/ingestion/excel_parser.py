import pandas as pd
import json
import math
from typing import Any

COLUMN_MAP = {
    "tour id": "tour_id_external",
    "sku": "sku",
    "country": "country",
    "region": "region",
    "name": "src_name",
    "subtitle": "subtitle",
    "duration": "duration",
    "group size": "group_size",
    "period": "period",
    "summary": "summary",
    "description": "description",
    "highlights": "highlights",
    "itineraries": "itineraries",
    "itinerary": "itineraries",
    "itinerary_summary": "itineraries",
    "trip_type": "trip_type",
    "price_usd": "price_raw",
    "tour_id": "tour_id_external",
    "inclusions": "inclusions",
    "exclusions": "exclusions",
    "provider": "provider",
    "price": "price_raw",
    "links": "links",
    "activities": "activities",
    "feature": "feature",
    "best time to go": "best_time_to_go",
    "source_name": "src_name",
    "source_subtitle": "subtitle",
    "source_summary": "summary",
    "source_highlights": "highlights",
    "source_itineraries": "itineraries",
    "aa_name": "src_name",
    "aa_subtitle": "subtitle",
    "aa_summary": "summary",
    "aa_highlights": "highlights",
    "aa_itineraries": "itineraries",
    "seo_title": "seo_title",
    "seo_meta": "seo_meta",
}

class ExcelParser:
    def __init__(self, file_path: str, source_file: str = None):
        self.file_path = file_path
        self.source_file = source_file

    def parse(self) -> list[dict]:
        # Try header=0 first; if columns look like group labels, use header=1
        df = pd.read_excel(self.file_path, engine="openpyxl", header=0)
        first_cols = [str(c).strip().lower() for c in df.columns]
        group_labels = {"identity", "source", "final content", "seo", "audit", "dfs context"}
        if any(c in group_labels for c in first_cols):
            df = pd.read_excel(self.file_path, engine="openpyxl", header=1)
        # Normalize column names: strip + lowercase for case-insensitive lookup
        col_map = {col.strip().lower(): col for col in df.columns}

        records = []
        for _, row in df.iterrows():
            record = {}
            for lower_key, db_field in COLUMN_MAP.items():
                if lower_key in col_map:
                    original_col = col_map[lower_key]
                    record[db_field] = self._clean(row.get(original_col))

            # Bắt buộc phải có name
            if not record.get("src_name"):
                continue

            record["source_file"] = self.source_file
            record["raw_data"] = json.dumps(row.to_dict(), default=str)
            records.append(record)

        return records

    def _clean(self, value: Any) -> str | None:
        # Check NaN/None trước khi convert sang string
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        cleaned = str(value).strip()
        return cleaned if cleaned and cleaned.lower() != "nan" else None
