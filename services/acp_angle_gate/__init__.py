"""
services.acp_angle_gate — AA-449, T8 Angle Gate.

Written fresh, per ADR-2026-038 §0.5 ("viết lại HOÀN TOÀN, KHÔNG dùng lại code
acp_s4_social") — no import from services.acp_s4_social anywhere in this package. Reference
material only (docs/AI-gent-for automation works/stage4.2_ Social-media contents_v2/SKILL_v2.md
+ the "writing formulars"/"Channel Output Structures" tables, quoted in full in
docs/claude_tasks/AA-449-00-step0-t8-angle-gate-investigation.md's Bang 1/Bang 2), not code.

Terminology (STEP0 §2 / build task §1 — use consistently, do not mix up):
- **Goal** = the 8-value list in `goals.py` (Promotion, Lead Generation, ...). Called "Angle" in
  the build task's Bang 1 header, but that word is reserved for the tier below per SKILL_v2.md's
  own vocabulary — this package always says "goal", never "angle", for this tier.
- **Angle** = one of the 3 LLM-generated options per request (`generate.py`), each with
  name/why_it_works/formula_fit/best_final_style. This is the only tier this package calls
  "angle".

Module layout:
- `goals.py` — static 8-goal table (Bang 1: name, description, logic, marketing_term).
- `channel_style.py` — static 8-channel style table (Bang 2's 7 channels + "blog", which has no
  Bang-2 row — see that module's own docstring).
- `brand_audience.py` — reads the tenant's already-existing "fixed brand audience"
  (shared.tenant_brand_rules.customer_segment/customer_mindset), per STEP0 §6.
- `prompts.py` — builds the system/user prompt for the one real LLM call this package makes.
- `generate.py` — the LLM call itself (Bedrock Sonnet 4.5, shared.llm_client.client.LLMClient,
  the same "exclusive LLM layer" services/content_generation/graph.py already uses) + JSON
  parsing/repair, same pattern as that module.
- `service.py` — DB read/write: create request, set goal (triggers generate), choose angle,
  fetch request. Talks to acp_shared.angle_gate_request/angle_gate_option (migration 113).
"""
