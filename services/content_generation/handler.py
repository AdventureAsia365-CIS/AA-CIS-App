import asyncio
import asyncpg
import json
import os
import structlog

from .graph import build_graph
from shared.repository.raw_tour_repository import RawTourRepository
from shared.repository.seo_context_repository import SeoContextRepository

logger = structlog.get_logger()

async def process_tour(raw_tour_id: str, seo_id: str = None) -> dict:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        tour_repo = RawTourRepository(conn)
        seo_repo  = SeoContextRepository(conn)

        tour = await tour_repo.get_by_id(raw_tour_id)
        if not tour:
            raise ValueError(f"Tour not found: {raw_tour_id}")

        seo = {}
        if seo_id:
            seo_row = await seo_repo.get_by_id(seo_id)
            if seo_row:
                seo = {
                    "keywords":        json.loads(seo_row.get("keywords") or "{}"),
                    "people_also_ask": [],
                }

        # Run LangGraph
        graph = build_graph()
        initial_state = {
            "tour":          dict(tour),
            "seo":           seo,
            "few_shots":     [],
            "generated":     {},
            "quality_score": 0.0,
            "retry_count":   0,
            "feedback":      "",
            "error":         "",
            "cost_usd":      0.0,
            "model_used":    "",
        }

        final_state = graph.invoke(initial_state)
        logger.info("graph_complete",
                    score=final_state["quality_score"],
                    retries=final_state["retry_count"],
                    cost=final_state["cost_usd"])

        # Insert vào silver.published_tour_versions
        generated = final_state["generated"]
        version_id = await conn.fetchval("""
            INSERT INTO silver.published_tour_versions (
                raw_tour_id, version_number, name, subtitle, summary,
                highlights, seo_title, seo_meta, trip_type,
                quality_score, publish_ready, hitl_status,
                llm_model, generation_cost_usd, is_active
            ) VALUES (
                $1, 1, $2, $3, $4, $5, $6, $7, $8,
                $9, $10, $11, $12, $13, FALSE
            ) RETURNING id
        """,
            raw_tour_id,
            generated.get("name"),
            generated.get("subtitle"),
            generated.get("summary"),
            generated.get("highlights", []),
            generated.get("seo_title"),
            generated.get("seo_meta"),
            generated.get("trip_type"),
            final_state["quality_score"],
            final_state["quality_score"] >= 7.0,
            "pending" if final_state["quality_score"] < 7.0 else "approved",
            final_state["model_used"],
            final_state["cost_usd"],
        )

        return {
            "status":      "done" if final_state["quality_score"] >= 7.0 else "hitl",
            "version_id":  str(version_id),
            "score":       final_state["quality_score"],
            "retries":     final_state["retry_count"],
            "cost_usd":    final_state["cost_usd"],
        }

    finally:
        await conn.close()

def lambda_handler(event: dict, context) -> dict:
    results = []
    for record in event.get("Records", []):
        try:
            body        = json.loads(record["body"])
            raw_tour_id = body.get("raw_tour_id")
            seo_id      = body.get("seo_id")

            if not raw_tour_id:
                logger.warning("missing_raw_tour_id")
                continue

            result = asyncio.run(process_tour(raw_tour_id, seo_id))
            results.append(result)

        except Exception as e:
            logger.error("content_gen_failed", error=str(e))
            results.append({"status": "failed", "error": str(e)})

    return {"processed": len(results), "results": results}
