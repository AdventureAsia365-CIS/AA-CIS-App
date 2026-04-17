export interface RawTour {
  id: string;
  name: string;
  country: string;
  duration: string;
  provider: string;
  pipeline_status: string;
  etl_at: string;
}

export interface PublishedVersion {
  id: string;
  raw_tour_id: string;
  version_number: number;
  name: string;
  subtitle: string;
  summary: string;
  highlights: string[];
  seo_title: string;
  seo_meta: string;
  trip_type: string;
  quality_score: number;
  audit_status: string;
  hitl_status: string;
  publish_ready: boolean;
  llm_model: string;
  generation_cost_usd: number;
  created_at: string;
}

export interface PipelineRun {
  id: string;
  execution_id: string;
  total_tours: number;
  processed: number;
  succeeded: number;
  failed: number;
  hitl_pending: number;
  status: string;
  total_cost_usd: number;
  started_at: string;
  completed_at: string;
}

export interface CatalogItem {
  id: string;
  name: string;
  country: string;
  trip_type: string;
  quality_score: number;
  status: string;
  slug: string;
  published_at: string;
}
