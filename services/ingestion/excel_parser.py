import pandas as pd
import json
import math
import structlog
from typing import Any
from shared.llm_client.column_mapper import build_dynamic_column_map

logger = structlog.get_logger()

COLUMN_MAP = {
    "tour id":            "tour_id_external",
    "sku":                "sku",
    "country":            "country",
    "region":             "region",
    "name":               "src_name",
    "subtitle":           "subtitle",
    "duration":           "duration",
    "group size":         "group_size",
    "period":             "period",
    "summary":            "src_summary",
    "description":        "src_description",
    "highlights":         "src_highlights",
    "itineraries":        "src_itineraries",
    "itinerary":          "src_itineraries",
    "itinerary_summary":  "src_itineraries",
    "trip_type":          "trip_type",
    "price_usd":          "price_raw",
    "tour_id":            "tour_id_external",
    "inclusions":         "inclusions",
    "exclusions":         "exclusions",
    "provider":           "provider",
    "price":              "price_raw",
    "links":              "links",
    "activities":         "activities",
    "feature":            "feature",
    "best time to go":    "best_time_to_go",
    "source_name":        "src_name",
    "source_subtitle":    "subtitle",
    "source_summary":     "src_summary",
    "source_highlights":  "src_highlights",
    "source_itineraries": "src_itineraries",
    "aa_name":            "src_name",
    "aa_subtitle":        "subtitle",
    "aa_summary":         "src_summary",
    "aa_highlights":      "src_highlights",
    "aa_itineraries":     "src_itineraries",
    "seo_title":          "seo_title",
    "seo_meta":           "seo_meta",
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

        # Build column map — static first, LLM fallback if needed
        excel_columns = [str(c).strip() for c in df.columns]
        active_map, llm_used = build_dynamic_column_map(excel_columns, COLUMN_MAP)

        if llm_used:
            logger.info("llm_column_map_applied",
                        file=self.source_file,
                        mapped_cols=len(active_map))
        else:
            logger.info("static_column_map_applied",
                        file=self.source_file,
                        matched_cols=len(active_map))

        # Build col_name → db_field lookup using active_map
        # active_map keys are lowercase excel col names
        col_lookup = {}
        for col in df.columns:
            lower = str(col).strip().lower()
            if lower in active_map:
                col_lookup[str(col)] = active_map[lower]

        records = []
        for _, row in df.iterrows():
            record = {}
            for excel_col, db_field in col_lookup.items():
                record[db_field] = self._clean(row.get(excel_col))

            # Must have src_name
            if not record.get("src_name"):
                continue

            record["source_file"] = self.source_file
            record["raw_data"] = json.dumps(row.to_dict(), default=str)
            records.append(record)

        logger.info("excel_parse_complete",
                    file=self.source_file,
                    records=len(records),
                    llm_used=llm_used)
        return records

    def _clean(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float) and math.isnan(value):
            return None
        cleaned = str(value).strip()
        return cleaned if cleaned and cleaned.lower() != "nan" else None
