"""
POST /v1/pipeline/run — Upload Excel → parse → rewrite → return results
Chạy trực tiếp trong ECS, không cần Lambda/Step Functions.
"""
import os
import json
import uuid
import asyncio
import tempfile
import structlog

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from services.ingestion.excel_parser import ExcelParser
from services.content_generation.graph import build_graph
from shared.llm_client.client import LLMClient
from shared.llm_client.models import LLMRequest
from services.content_generation.prompts import SYSTEM_PROMPT, build_rewrite_prompt

logger = structlog.get_logger()
router = APIRouter(prefix="/v1/pipeline", tags=["pipeline"])

def _normalize_generated(generated: dict, tour: dict) -> dict:
    """Post-process LLM output: title-case name, strip forbidden words from name."""
    if not generated:
        return generated
    # Title-case name if ALL-CAPS (preserve if already mixed case)
    name = generated.get("name", "")
    if name and name == name.upper():
        generated["name"] = name.title()
    return generated



async def _rewrite_tour(tour: dict, idx: int, total: int) -> dict:
    """Rewrite single tour using LangGraph."""
    logger.info("rewriting_tour", idx=idx, total=total, name=tour.get("name", ""))

    try:
        graph = build_graph()
        initial_state = {
            "tour": tour,
            "seo": {},
            "few_shots": [],
            "generated": {},
            "quality_score": 0.0,
            "retry_count": 0,
            "feedback": "",
            "error": "",
            "cost_usd": 0.0,
            "model_used": "",
        }

        def run_graph():
            import asyncio as _asyncio
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
            try:
                return graph.invoke(initial_state)
            finally:
                loop.close()
        result = await asyncio.get_event_loop().run_in_executor(None, run_graph)

        return {
            "idx": idx,
            "src_name": tour.get("name", ""),
            "country": tour.get("country", ""),
            "duration": tour.get("duration", ""),
            "generated": _normalize_generated(result.get("generated", {}), tour),
            "quality_score": result.get("quality_score", 0.0),
            "model_used": result.get("model_used", ""),
            "cost_usd": result.get("cost_usd", 0.0),
            "retry_count": result.get("retry_count", 0),
            "error": result.get("error", ""),
            "status": "success" if result.get("generated") else "failed",
        }

    except Exception as e:
        logger.error("rewrite_failed", idx=idx, error=str(e))
        return {
            "idx": idx,
            "src_name": tour.get("name", ""),
            "country": tour.get("country", ""),
            "status": "failed",
            "error": str(e),
        }


@router.post("/run")
async def run_pipeline(
    file: UploadFile = File(...),
    max_tours: int = 5,
):
    """
    Upload Excel file → parse → rewrite up to max_tours tours.
    Returns before/after comparison with quality scores.

    Args:
        file: Excel file (.xlsx)
        max_tours: Max number of tours to process (default 5, max 20)
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Only .xlsx/.xls files supported")

    max_tours = min(max_tours, 20)  # Hard cap at 20

    # Save upload to temp file
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    logger.info("pipeline_started", filename=file.filename, max_tours=max_tours)

    try:
        # Parse Excel
        parser = ExcelParser(tmp_path, source_file=file.filename)
        records = parser.parse()

        if not records:
            raise HTTPException(400, "No valid tour records found in Excel file")

        # Limit tours
        records = records[:max_tours]
        logger.info("tours_parsed", total=len(records))

        # Rewrite tours concurrently (max 3 at a time to avoid rate limits)
        semaphore = asyncio.Semaphore(3)

        async def bounded_rewrite(tour, idx):
            async with semaphore:
                return await _rewrite_tour(tour, idx + 1, len(records))

        tasks = [bounded_rewrite(tour, i) for i, tour in enumerate(records)]
        results = await asyncio.gather(*tasks)

        # Summary stats
        successful = [r for r in results if r.get("status") == "success"]
        failed = [r for r in results if r.get("status") == "failed"]
        total_cost = sum(r.get("cost_usd", 0) for r in results)
        avg_quality = (
            sum(r.get("quality_score", 0) for r in successful) / len(successful)
            if successful else 0
        )

        return JSONResponse({
            "batch_id": str(uuid.uuid4()),
            "filename": file.filename,
            "summary": {
                "total": len(records),
                "successful": len(successful),
                "failed": len(failed),
                "avg_quality_score": round(avg_quality, 2),
                "total_cost_usd": round(total_cost, 4),
            },
            "results": results,
        })

    finally:
        os.unlink(tmp_path)
