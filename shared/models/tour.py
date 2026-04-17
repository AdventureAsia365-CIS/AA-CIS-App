from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid

class RawSource(BaseModel):
    id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    s3_bucket: str
    s3_key: str
    supplier_name: Optional[str] = None
    original_filename: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    status: str = "queued"
    row_count: Optional[int] = None
    error_message: Optional[str] = None

class RawTour(BaseModel):
    id: Optional[str] = None
    source_id: Optional[str] = None
    tour_id_external: Optional[str] = None
    sku: Optional[str] = None
    country: Optional[str] = None
    name: str
    subtitle: Optional[str] = None
    duration: Optional[str] = None
    group_size: Optional[str] = None
    period: Optional[str] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    highlights: Optional[str] = None
    itineraries: Optional[str] = None
    inclusions: Optional[str] = None
    exclusions: Optional[str] = None
    provider: Optional[str] = None
    price_raw: Optional[str] = None
    links: Optional[str] = None
    activities: Optional[str] = None
    feature: Optional[str] = None
    best_time_to_go: Optional[str] = None
    source_file: Optional[str] = None
    raw_data: Optional[str] = None
    etl_at: Optional[datetime] = None
    pipeline_status: str = "queued"
