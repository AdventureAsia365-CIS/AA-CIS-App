"""
SLO/SLA helper functions for the Run-Health dashboard (AA-141).

All functions are pure Python — no DB or external calls.
"""

# Stage duration SLO thresholds (seconds). Exceeding = stuck alert.
STAGE_SLO_SECONDS: dict[str, int] = {
    "s2":         30 * 60,   # 30 min
    "s3":         15 * 60,   # 15 min
    "s4_blog":    60 * 60,   # 60 min
    "s4_social":  30 * 60,   # 30 min
}

# Gate SLA: gate_num (0-indexed, maps stage 1→0, 2→1, 3→2, 4→3) → hours
GATE_SLA_HOURS: dict[int, float] = {
    0: 48.0,
    1: 4.0,
    2: 24.0,
    3: 48.0,
}

# acp_hitl_requests.stage (int) → gate_num (0-indexed)
STAGE_INT_TO_GATE: dict[int, int] = {1: 0, 2: 1, 3: 2, 4: 3}

COST_CAP_USD: float = 10.0
EVALUATOR_SCORE_FLOOR: float = 7.0


def check_stage_slo(stage: str, duration_seconds: float) -> bool:
    """Return True if stage exceeded its SLO duration threshold."""
    threshold = STAGE_SLO_SECONDS.get(stage)
    if threshold is None:
        return False
    return duration_seconds > threshold


def check_gate_sla(gate: int, elapsed_hours: float) -> bool:
    """Return True if gate exceeded its SLA elapsed-hours threshold."""
    sla = GATE_SLA_HOURS.get(gate)
    if sla is None:
        return False
    return elapsed_hours > sla


def check_cost_cap(cost_usd: float, cap: float = COST_CAP_USD) -> bool:
    """Return True if run LLM cost exceeded the cap threshold."""
    return cost_usd > cap
