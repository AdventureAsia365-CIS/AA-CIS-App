"""AA-518/AA-505 — shared Bedrock/OpenAI pricing table, extracted out of client.py so both
LLMClient (Mechanism A) and the Mechanism-B call sites that invoke shared/llm_client/
bedrock_satellite.py::invoke_claude() directly (T5 atomize, N7 E2-E5, s1_from_atom.py, DFS gap
research) can compute a real cost_usd for shared.llm_call_log without duplicating the table or
importing client.py (which would be a heavier/circular-risking import for those modules).

Values themselves are UNCHANGED from client.py's own COST_TABLE — this is a pure relocation, not
a repricing. client.py re-exports the same names so nothing importing from client.py breaks.
"""

# Bedrock model IDs (cross-region inference profiles)
BEDROCK_SONNET = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
BEDROCK_HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# $ per 1K tokens, {"in": ..., "out": ...}
COST_TABLE = {
    BEDROCK_SONNET: {"in": 0.003, "out": 0.015},
    BEDROCK_HAIKU: {"in": 0.00025, "out": 0.00125},
    "gpt-4.1": {"in": 0.002, "out": 0.008},
}

# Mechanism-B callers (invoke_claude) pass the short model key ("sonnet"/"haiku"), not the full
# Bedrock model id — this maps that key to the same COST_TABLE entry Mechanism A uses, so both
# mechanisms price identically instead of drifting.
_SHORT_KEY_TO_MODEL_ID = {"sonnet": BEDROCK_SONNET, "haiku": BEDROCK_HAIKU}


def calc_cost(model: str, in_tok: int, out_tok: int) -> float:
    """`model` accepts either a full Bedrock model id, a short key ("sonnet"/"haiku"), or
    "gpt-4.1". Unknown model falls back to Sonnet-tier rates (matches client.py's own prior
    `_calc_cost` fallback exactly) rather than raising — pricing must never be the reason an LLM
    call fails."""
    resolved = _SHORT_KEY_TO_MODEL_ID.get(model, model)
    rates = COST_TABLE.get(resolved, {"in": 0.003, "out": 0.015})
    return round((in_tok * rates["in"] + out_tok * rates["out"]) / 1000, 6)
