# AA_Ecosys — CIS + ACP Platform Handoff Document

**Last updated:** 21/05/2026 — Session 25
**Prepared by:** Nghiep (Pham Quoc Nghiep) — DevOps/AI Engineer
**For:** Ms. Thu (Tech Lead) | Leigh (Commercial Lead)

---

## 1. System Overview

### Architecture Summary

The AA_Ecosys program consists of two platforms:

| Platform | Purpose | Stack |
|----------|---------|-------|
| **AA-CIS** | Content Intelligence System — AI pipeline for rewriting supplier tours | AWS ECS Fargate, FastAPI, LangGraph, Bedrock, PostgreSQL |
| **AA-ACP** | Agency Content Pipeline — B2B content automation S0→S1→S2→S3→S4 | Same infra as CIS, multi-tenant |

**AWS Account:** `867490540162` | **Region:** `us-west-1`
**GitHub Org:** `AdventureAsia365-CIS`
**Repos:** `AA-CIS-App` | `AA-ACP-App` | `AA-CIS-Infra`

---

## 2. Current Production State (21/05/2026)

### Infrastructure

| Resource | State | Detail |
|----------|-------|--------|
| ECS Cluster | `aa-cis-dev-cluster` | Active |
| ECS Service | `aa-cis-dev-api` | Task def `api:161`, Healthy |
| RDS PostgreSQL | `aa-cis-dev-db` | PostgreSQL 15, Multi-AZ dev |
| ElastiCache Redis | `aa-cis-dev-redis` | Cache + Celery broker |
| EventBridge | `aa-cis-dev-acp-events` | 1 rule active: `acp-s3-completed-trigger-s4` |
| Lambda | `aa-cis-dev-acp-s4-trigger` | EventBridge → S4 blog trigger |
| Lambda | `aa-cis-dev-brand-brief-parser` | S0 DOCX parser |
| Lambda | `aa-cis-dev-acp-s3-campaign-planner` | S3 campaign Lambda |
| Lambda | `aa-cis-dev-acp-s4-evaluate` | H-1 Harness evaluator |
| pgvector | Enabled | `content_embedding vector(1536)` on published_tours + blog_drafts |
| WAF | `aa-cis-dev-waf` | Active, Terraform managed |

### Code State

| Repo | Branch | Latest commit | CI |
|------|--------|---------------|-----|
| AA-CIS-App | `main` | M5 Phase A+B merge (`777db72`) | ✅ CI #252, Deploy Prod |
| AA-CIS-App | `develop` | flake8 fix (`4d587d8`) | ✅ CI #252, Deploy Dev #157 |
| AA-ACP-App | `main` | AA-92 brand design (`dcdf8c9`) | ✅ CI #28, Deploy #9 (Vercel) |
| AA-CIS-Infra | `develop` | acp-s4-evaluate Lambda (`5fc5e13`) | n/a |

---

## 3. ACP Pipeline — Stage Map

```
S0 Input Manager (AA Internal)
  └─ XLSX upload + brand brief DOCX parsing
  └─ Gate 0: 48h SLA, never auto-approve
      │
      ▼
S1 Tour Content Rewrite (Step Functions + Bedrock Sonnet)
  └─ Configured rewrite per run_config (model, seo_mode, language)
  └─ Writes tour_content_versions + publishes to published_tours VIEW
      │ EventBridge: acp.s1.completed
      ▼
S2 Market Research (ECS LangGraph, 7 tools)
  └─ DataForSEO keywords + Apify competitor scrape + Google Trends + Reddit signals
  └─ confidence_scorer → Gate 1 auto-approve if ≥ 0.85 (aa_internal only)
      │ Gate 1: Auto (confidence ≥ 0.85) or Manual HITL
      ▼
S3 Campaign Planner (Lambda, Bedrock Sonnet)
  └─ 24-post content calendar (12 weeks × 2/week)
  └─ 3-tier lesson flywheel (job/agency/shared lessons)
      │ Gate 2: Ms. Thu reviews campaign plan
      ▼
S4.1 Blog Engine (ECS LangGraph, Bedrock Sonnet)      S4.2 Social Engine (ECS, 8 channels)
  └─ Factual grounding from tour_facts                  └─ Auto mode (pipeline) + Guided mode (portal)
  └─ pgvector dedup (cosine 0.92 threshold)             └─ 8 channels: FB/LI/TT/IG/Email/Newsletter/LP/Ads
  └─ Image: Pexels (primary) → none                     └─ Gate 3-social: Trang → Ms. Thu
  └─ Internal links via pgvector (≥2 per blog)
  └─ Gate 3: Trang QA → Ms. Thu final approve
      │ Gate 3 approve → CMS publish queue
      ▼
CMS WordPress (draft post via REST API)
  └─ Always status=draft, human publishes
  └─ Secret: acp/cms/{tenant_id} in Secrets Manager
```

### HITL Gates Summary

| Gate | Stage | Auto-approve? | Reviewer | SLA |
|------|-------|---------------|----------|-----|
| Gate 0 | S0 review | Never | AA Internal (Nghiep/Ms. Thu) | 48h |
| Gate 1 | S2 complete | Yes if confidence ≥ 0.85 (aa_internal) | AA Internal | 24h |
| Gate 2 | S3 complete | No | Ms. Thu | 24h |
| Gate 3 | S4.1 blog | No | Trang QA → Ms. Thu final | 48h |
| Gate 3-social | S4.2 social | No | Trang → Ms. Thu | 48h |

---

## 4. Database Schema Summary

PostgreSQL schemas:

| Schema | Purpose |
|--------|---------|
| `shared` | Tenants, brand rules, schema_versions |
| `acp_shared` | Run context, HITL requests, audit log, lessons, output rules, quota, checkpoints, CMS queue |
| `acp_silver_s2` | Competitor inputs, visibility_reports |
| `acp_silver_s3` | Campaign plans, ads plans |
| `acp_silver_s4` | Blog drafts, social_content, CMS publish queue |
| `acp_gold_output` | Published content |
| `gold_aa_internal` | Published tours (source of truth for aa_internal) |
| `silver_aa_internal` | Raw tours from supplier XLSX |

**Migration head:** `042` (sequence `025→042` continuous, gap-filled in Session 25)
**pgvector:** Enabled, `content_embedding vector(1536)` on published_tours + blog_drafts

---

## 5. Secrets Manager Keys (us-west-1)

| Secret | Purpose |
|--------|---------|
| `aa-cis/dev/rds` | PostgreSQL credentials (plain DSN) |
| `aa-cis/dev/anthropic-key` | Bedrock fallback / direct API |
| `aa-cis/dev/openai-key` | GPT-4.1 fallback |
| `aa-cis/dev/dataforseo` | SEO keyword research API |
| `aa-cis/dev/langfuse` | LLM observability |
| `aa-cis/dev/redis` | Redis connection |
| `aa-cis/dev/pexels-api-key` | Blog featured image sourcing |
| `aa-cis/dev/admin-secret` | Admin API auth |
| `aa-cis/dev/acp-partner-api` | B2B partner API key |
| `aa-cis/dev/acp-webhook-secret` | Webhook signature verification |
| `acp/cms/{tenant_id}` | WordPress credentials per tenant |

---

## 6. Cost Management

Stop resources after each session (not in production yet):

```bash
# Stop ECS (desired=0)
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 0 --profile pqnghiep-admin --region us-west-1

# Stop RDS
aws rds stop-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1
```

Start resources:

```bash
# Start RDS first — wait ~2 min for warm-up
aws rds start-db-instance --db-instance-identifier aa-cis-dev-db --profile pqnghiep-admin --region us-west-1

# Then start ECS
aws ecs update-service --cluster aa-cis-dev-cluster --service aa-cis-dev-api --desired-count 1 --profile pqnghiep-admin --region us-west-1
```

**May 2026 cost forecast:** ~$153.98 | **Budget alert:** $180

---

## 7. M5 UAT Readiness (Next: AA-47)

### ✅ Done (Phase A + B — Sessions 18–25)

- **AA-97:** All pending migrations verified and applied (035–042)
- **AA-98:** S2 LangGraph — 7 tools, 5 Ms. Thư prompts wired, Gate 1 auto-approve
- **AA-99:** S3 lessons flywheel verified, H-3 Mistake→Rule pipeline implemented
- **AA-100:** CMS Adapter (WordPress), EventBridge E2E chain, Gate 3 per-blog HITL
- **AA-62:** pgvector dedup + factual grounding + image sourcing (Pexels) + Gate 3 2-step Trang→Ms. Thu
- **AA-63:** Admin onboarding API + GDPR offboard + quota ledger + run comparison endpoint
- **AA-92:** AA brand design system (Fraunces, IBM Plex Sans, AA color tokens, SLATimer)
- **AA-102:** schema_versions gap fixed (025→042 continuous, Session 25)

### 🔴 Next: AA-47 — Full E2E UAT

Pre-UAT checklist:

1. **Update Lambda ALB URL** (placeholder currently):
```bash
aws lambda update-function-configuration --function-name aa-cis-dev-acp-s4-trigger --environment "Variables={ALB_INTERNAL_URL=http://<INTERNAL_ALB_DNS>,INTERNAL_API_KEY=<secret>}" --profile pqnghiep-admin --region us-west-1
```

2. **Setup WordPress Docker** (local UAT):
```bash
cd docker/wordpress-uat && docker-compose up -d
# Go to http://localhost:8090/wp-admin → create application password
aws secretsmanager create-secret --name "acp/cms/aa_internal" --secret-string '{"wp_url":"<ngrok_url>","username":"admin","app_password":"XXXX"}' --profile pqnghiep-admin --region us-west-1
```

3. **Verify aa_internal tenant UUID** in DB (Gate 1 hardcodes this in router.py)
4. **Onboard vietnam-uat tenant:** `POST /v1/admin/tenants`
5. **Upload 5 Vietnam tours** via S0 XLSX upload

---

## 8. M6 Roadmap (Master Content)

Goal: Show Ms. Thu full quality output of pipeline on 20 golden AA tours.

- **AA-101:** Golden Tours 20 (`CIS_Golden_Tours_20_v1.xlsx`) → 3 configs × 20 tours = 60 versions
- **Dashboard:** `/workspace/master-content` — score comparison, version activate
- **DOCX report** for Ms. Thu sign-off

---

## 9. Known Tech Debt

| Item | Priority | Notes |
|------|----------|-------|
| `api_task_def_arn` hardcoded `:21` in main.tf | P2 | Update after next ECS deploy cycle |
| Lambda DATABASE_URL plaintext | P2 | Migrate to Secrets Manager (P4-S6) |
| Lambda s4-trigger `ALB_INTERNAL_URL` placeholder | P0 | Must fix before AA-47 UAT |
| WordPress UAT setup | P0 | Docker + ngrok + Secrets Manager |
| Gate 1 `aa_internal` UUID hardcoded in router.py | P0 | Verify against actual DB tenant_id |
| AA-81 S4-social sub-pipeline | Low | Likely superseded by AA-93 — confirm close with Leigh |
| AAA image migration to S3 (AA-7) | High | Due 30/06 |
| AAA DEV RDS 19-table schema (AA-65) | High | Due 30/06 |

---

## 10. Contacts

| Name | Role | Scope |
|------|------|-------|
| Ms. Thu | Tech Lead, approval authority | All deliverables, DNS (lumiguides.com via Namecheap) |
| Leigh | Commercial Lead | AAA Q2 tasks, AWS Partner Activate |
| Trang | Content team | Gate 3 QA reviewer for blog drafts |
| Mr. HoangQuan | Solution PM | AAA handover coordinator |
| Mr. ManhQuan | Solution Backend | AAA ERD + migrations |

---

*This document is auto-maintained. Last session: 25 (21/05/2026). Next: Session 26 — AA-47 E2E UAT.*
