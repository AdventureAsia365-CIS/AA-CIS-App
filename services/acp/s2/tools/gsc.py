"""
Google Search Console tool. STUB — OAuth setup deferred.
Conditional: only if tenant has gsc_property_url configured.
Returns gsc_s3_key=None unconditionally until OAuth is wired.
"""
import structlog

logger = structlog.get_logger()


def make_gsc_node(pool):

    async def gsc(state: dict) -> dict:
        logger.info("gsc_stub_skipped", run_id=state.get("run_id"))
        completed = list(state.get("completed_tools", []))
        completed.append("gsc")
        return {"gsc_s3_key": None, "gsc_data_present": False, "completed_tools": completed}

    return gsc
