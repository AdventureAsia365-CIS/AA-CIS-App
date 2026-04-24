import pandas as pd
import json
import math
from typing import Any

COLUMN_MAP = {
    "tour id": "tour_id_external",
    "sku": "sku",
    "country": "country",
    "region": "region",
    "name": "name",
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
}

class ExcelParser:
    def __init__(self, file_path: str, source_file: str = None):
        self.file_path = file_path
        self.source_file = source_file

    def parse(self) -> list[dict]:
        df = pd.read_excel(self.file_path, engine="openpyxl")
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
            if not record.get("name"):
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
