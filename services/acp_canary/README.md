# ACP Synthetic Canary — services/acp_canary

## Purpose

Weekly Lambda smoke test for the ACP pipeline. Validates that the full
S0→S1 flow runs end-to-end without regressions after any deploy.

## Wave 0 Scope (current)

- Seeds one fixture tour directly into `silver_aa_internal.raw_tours` (bypasses XLSX S0 upload)
- Creates an S1 run via `POST /acp/s1/run`
- Polls until run reaches terminal status (timeout: 5 min)
- Asserts: `status = completed`, `cost_usd < $5`, no forbidden words in S1 output
- Checks `acp_stage_runs` for S1 stage timing (requires migration 057)

S2–S4.2 assertions will be added in Wave 1–4 after the rebuild of those stages.

## Files

```
services/acp_canary/
├── __init__.py
├── fixtures/
│   └── canary_fixture.json   # Hardcoded Ha Long Bay tour (minimal valid S1 input)
└── lambda_handler.py         # Lambda entry point: handler(event, context)

infrastructure/canary/
└── eventbridge_scheduler.tf  # EventBridge Scheduler (state=DISABLED until Lambda deployed)
```

## Required Env Vars

| Var | Required | Description |
|-----|----------|-------------|
| `API_BASE_URL` | Yes | Internal ECS ALB URL, e.g. `http://aa-cis-dev-alb.internal` |
| `ADMIN_SECRET` | Yes | `X-Admin-Secret` header value from ECS task env |
| `RDS_SECRET_ID` | No | Secrets Manager secret ID (default: `aa-cis/dev/rds`) |
| `AWS_REGION` | No | AWS region (default: `us-west-1`) |
| `CANARY_ALERT_SNS_ARN` | No | SNS topic ARN for failure alerts (e.g. `aa-cis-dev-alerts`) |
| `CANARY_TENANT_ID` | No | Tenant UUID (default: aa_internal `00000000-0000-0000-0000-000000000001`) |

## Manual Trigger

```bash
# Invoke Lambda directly (after deploy)
aws lambda invoke \
  --function-name aa-cis-dev-acp-canary \
  --payload '{}' \
  --log-type Tail \
  /tmp/canary-result.json \
  --profile pqnghiep-admin \
  --region us-west-1

cat /tmp/canary-result.json
```

**Single-line (WSL2 safe):**
```bash
aws lambda invoke --function-name aa-cis-dev-acp-canary --payload '{}' --log-type Tail /tmp/canary-result.json --profile pqnghiep-admin --region us-west-1
```

## Reading Results

CloudWatch log group: `/aws/lambda/aa-cis-dev-acp-canary`

```bash
aws logs tail /aws/lambda/aa-cis-dev-acp-canary --follow --profile pqnghiep-admin --region us-west-1
```

Successful run returns:
```json
{"status": "PASSED", "run_id": "...", "cost_usd": 0.002, "stage": "S1"}
```

Failed run returns:
```json
{"status": "FAILED", "errors": ["S1 run ended with status='failed'"], "run_id": "..."}
```

## Prerequisites Before First Run

1. Apply migration 058 (`is_canary`, `skip_hitl` columns on `shared.tenants`)
2. Apply migration 055 (cost tracking — `total_llm_cost_usd`)
3. Apply migration 057 (`started_at`, `completed_at` on `acp_stage_runs`) — optional; canary degrades gracefully
4. Deploy Lambda with all env vars set
5. Set `STEP_FUNCTIONS_ARN` in Lambda env (required for S1 rewrite to actually execute)
6. Enable EventBridge Scheduler in `infrastructure/canary/eventbridge_scheduler.tf` after first successful manual run

## Adding S2–S4.2 Assertions (Wave 1–4)

After S2–S4 stages are rebuilt, add assertion steps inside `handler()`:

```python
# Wave 1: S2 market research assertion
s2_result = asyncio.run(_fetch_s2_result_async(dsn, run_id))
assert s2_result is not None, "S2 visibility report missing"

# Wave 2: S3 content calendar assertion
# ...

# Wave 3–4: S4 blog draft assertion
# ...
```

Each wave adds one assertion block. Do not modify `FORBIDDEN_WORDS` or `MAX_COST_USD`
without updating the canary fixture and re-testing.

## Canary Fixture Notes

The fixture uses `src_name` ending in `"— Canary Fixture"` to allow safe
cleanup on each run (`DELETE ... WHERE src_name LIKE '%Canary Fixture%'`).

Do not rename the suffix. Do not use real production tour names.
