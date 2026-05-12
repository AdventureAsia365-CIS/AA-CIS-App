from pydantic import BaseModel
from typing import Optional

class LLMRequest(BaseModel):
    system_prompt: str
    user_prompt:   str
    few_shots:     list[dict] = []
    max_tokens:    int = 2000
    temperature:   float = 0.7
    # model_tier controls which Bedrock model to start from:
    #   "haiku"  → skip T1, go directly to T2 (Haiku) — fast/cheap
    #   "sonnet" → try T1 (Sonnet) first, fall back to T2 then T3
    model_tier:    str = "haiku"

class LLMResponse(BaseModel):
    content:       str
    model_used:    str
    provider:      str
    input_tokens:  int = 0
    output_tokens: int = 0
    cost_usd:      float = 0.0
    fallback_used: bool = False
