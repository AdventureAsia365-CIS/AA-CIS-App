# AA-CIS-App Handoff — Session 22 (21/05/2026)

## State
- Branch: develop | Commit: ae2ba56
- ECS: api:151 | CI #241 ✅ | Deploy Dev #147 ✅
- AWS: STOPPED (ECS desired=0, RDS stopped)

## What was built (AA-45)
- services/acp_s3/: Lambda handler — skeleton-then-expand (Sonnet), ads (Haiku), 5 validators, 3-tier lessons
- api/routers/v1_s3.py: POST /v1/s3/run, GET /v1/s3/runs/{id}, POST /v1/hitl/gate2/{id}/approve|reject
- migrations/versions/031_acp_silver_s3_v2.sql: ads_plan + acp_run_context + acp_lessons_agency/shared + ALTER content_calendars

## Pending (Session 23 must do FIRST)
1. Apply migration 031 via S3-mediated ECS exec (RDS must be running)
2. Deploy Lambda aa-cis-dev-acp-s3-campaign-planner via AA-CIS-Infra Terraform
3. AA-89: B2B self-approval — migration 021

## Known deviations (accepted)
- InvocationType=Event for S3 Lambda (not RequestResponse) — correct for 15-min Lambda
- acp_shared.tenants FK dropped in migration 031 — table does not exist in DB
- social_plan table NOT in S3 — moved to AA-80 (M4)
- GET /v1/s3/runs/{id} returns full expanded_markdown + campaigns (UI requires it)
