import pandas as pd
import json
import math
from typing import Any

COLUMN_MAP = {
    "Tour ID": "tour_id_external",
    "SKU": "sku",
    "Country": "country",
    "Name": "name",
    "Subtitle": "subtitle",
    "Duration": "duration",
    "Group Size": "group_size",
    "Period": "period",
    "Summary": "summary",
    "Description": "description",
    "Highlights": "highlights",
    "Itineraries": "itineraries",
    "Inclusions": "inclusions",
    "Exclusions": "exclusions",
    "Provider": "provider",
    "Price": "price_raw",
    "Links": "links",
    "Activities": "activities",
    "Feature": "feature",
    "Best Time To Go": "best_time_to_go",
}

class ExcelParser:
    def __init__(self, file_path: str, source_file: str = None):
        self.file_path = file_path
        self.source_file = source_file

    def parse(self) -> list[dict]:
        df = pd.read_excel(self.file_path, engine="openpyxl")

        records = []
        for _, row in df.iterrows():
            record = {}
            for excel_col, db_field in COLUMN_MAP.items():
                if excel_col in df.columns:
                    record[db_field] = self._clean(row.get(excel_col))

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
