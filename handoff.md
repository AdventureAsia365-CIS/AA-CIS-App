# AA-CIS-App Handoff — Session 51
Updated: 2026-06-03

## Status
- Branch: fix/aa-167-168-s3-model-confidence | Last commit: 419c559
- ECS: api:246 (⚠️ STOP if still running)
- RDS: aa-cis-dev-db (⚠️ STOP if still running)
- Migrations 052–060: NOT YET APPLIED

## Completed This Session

### AA-167 — S3 planner.py Sonnet model ID fix (commit 419c559)

**Bug**: `_SONNET = "us.anthropic.claude-haiku-4-5-20251001-v1:0"` — variable named SONNET but assigned Haiku model ID.

**Fix:**
- `services/acp_s3/planner.py`: `_SONNET` → `SONNET_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20251001-v1:0"`
- `services/acp_s3/ads.py`: `_HAIKU` → `HAIKU_MODEL_ID` (value correct, rename only)
- `services/acp_s3/lessons.py`: `_HAIKU` → `HAIKU_MODEL_ID` (value correct, rename only)
- `services/acp_s3/handler.py`: updated references to public names

**Impact**: Steps 3 (skeleton) and 4 (expand) now use actual Sonnet model instead of Haiku.
Cost tracking via `_calc_cost("sonnet")` now matches actual model → no more billing undercount.

### AA-168 — H-3 programmatic confidence threshold (commit 419c559)

**Bug**: `write_lessons` wrote all `system_promotions` to `acp_lessons_shared` regardless of quality.
The LLM was trusted entirely — no programmatic gate.

**Fix:**
- `models.py`: added `SystemPromotion(content: str, confidence: float = 0.0)`; changed `LessonUpdateOutput.system_promotions` from `list[str]` to `list[SystemPromotion]`
- `lessons.py`: added `H3_PROMOTION_THRESHOLD = 0.80`; filter in `write_lessons` — skip promotions with `confidence < 0.80`
- `prompts/lesson_update_prompt.md`: updated to return `system_promotions` as `[{"content": str, "confidence": float}]`

**Notes:**
- `h3_rule_extractor.py` (gate rejection path) was already correctly implementing `H3_CONFIDENCE_THRESHOLD = 0.80` — no changes needed there.
- The lesson update path now mirrors the same pattern.
- `default confidence=0.0` on SystemPromotion means if Haiku omits the field, the promotion is silently dropped (safe).

**Tests:** 57/57 acp_s3 tests pass (13 new: 6 for AA-167, 7 for AA-168)

### Branch history
- `fix/aa-167-168-s3-model-confidence` (this session) — pushed, awaiting CI
- `feature/aa-122-s3-context-guardrail` (session 50) — pushed, awaiting CI
- `feature/aa-112-s2-async-postgres-saver` (session 49) — pushed, DO NOT merge

## Open Issues (carried forward)
- Migration 052–060: all pending
- OPENAI_API_KEY needs rotation (exposed session 39)
- API Gateway 29s timeout on long tour rewrites
- `s2_keyword_research.keywords` always empty → planner top_18 always empty (documented AA-122 audit)
- DataForSEO format mismatch (`search_volume` vs `vol_m1`/`vol_m2`) — separate ticket

## Cost Checklist (MANUAL — do not auto-run)
```
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 0 --profile pqnghiep-admin --region us-west-1
aws rds stop-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
```
