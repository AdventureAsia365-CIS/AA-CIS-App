# AA-CIS-App Handoff — Session 23 (21/05/2026)

## State
- Branch: feature/aa-49-harness-h1-h2 (AA-CIS-App) | Commit: 4dd923b
- Branch: feature/aa-49-harness-h1-h2 (AA-ACP-App) | Commit: ee491de
- Branch: develop (AA-CIS-Infra) | Commit: ab81ad0
- ECS: api:151 | STILL RUNNING (task 3a0a449b8fd74c34b6612eb1daaa3965)
- AWS: ECS RUNNING, RDS available
- ⚠️ Stop ECS + RDS when done reviewing

## What was built (AA-49 H-1 + H-2)

### H-1 — Isolated Evaluator Lambda (aa-cis-dev-acp-s4-evaluate)
- `services/acp_s4_evaluate/handler.py`: text-only Bedrock Haiku evaluator
  - Input: {text: str} ONLY (no brand context, no DB)
  - Output: {evaluator_score, dimension_scores, issues, evaluator_input_hash}
  - evaluator_input_hash = SHA256 of input text (isolation proof)
- Lambda deployed to AWS via Terraform ✅ | State: Active ✅
- Tested: `{"evaluator_score": 4.8, "evaluator_input_hash": "c227fb77..."}` ✅
- IAM: cross-region Bedrock wildcard (`arn:aws:bedrock:*`) — needed because `us.*` inference profile routes via us-east-1

### H-2 — Post-Processor + Rules Dashboard
- `api/services/acp_post_processor.py`: deterministic rule applier
  - Adapted to ACTUAL DB schema (rule_type/pattern/action_value/is_active — NOT rule_code/action_type)
  - 7 unit tests pass ✅
- `services/acp_s4/generate.py`: S4 blog draft generation stub with H-1/H-2 integration
- `api/routers/v1_rules.py`: GET /v1/rules + PATCH /v1/rules/{rule_id}
- `api/migrations/032_harness_columns.sql`: idempotent migration (columns already in live DB)

### Rules Dashboard UI
- `AA-ACP-App/src/app/(admin)/workspace/rules/page.tsx`
- Table with toggle, stage filter, pattern/action display

## Pending (Next Session)
1. Merge feature/aa-49-harness-h1-h2 → develop (AA-CIS-App + AA-ACP-App) after verify
2. Push to CI → ECS deploy to pick up new routes (/v1/rules)
3. Migration 031 — still NOT applied (was pending from Session 22)
4. Lambda aa-cis-dev-acp-s3-campaign-planner — still NOT deployed (Infra)
5. AA-90 (S1 trigger page), AA-43 (S2 LangGraph) — HIGH priority

## Known Deviations (accepted)
- AA-CIS-Infra committed to `develop` directly (not feature branch) because Lambda was deployed via `terraform apply` during session
- acp_output_rules schema uses `rule_type/pattern/action_value/is_active` — post_processor adapted to this, NOT the task spec column names
- Migration 032 columns already existed in live DB — migration file created as idempotent reference
- S4 graph.py: Task referenced services/content_generation/graph.py (S1 tour content). Since no S4 blog generation flow exists, created services/acp_s4/generate.py stub instead
