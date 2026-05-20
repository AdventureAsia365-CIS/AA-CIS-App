# AA-45 S3 Campaign Planner — Compiled Spec
> Source: ACP PRD v1.0 §4, v1.1 §4.4, v1.2 §6.1 (no S3 override)
> Compiled: 20/05/2026 — Session 22

---

## Repo + Branch
- Repo: `AdventureAsia365-CIS/AA-CIS-App`
- Branch: `pqnghiep1354/aa-45-acp-s3-content-campaign-planner-lambda-llm-content-calendar`
- Base: `develop`

---

## Compute
- Lambda, 1GB RAM, 15min timeout
- Location: `services/acp_s3/`
- Named: `aa-cis-dev-acp-s3-campaign-planner` (consistent with `aa-cis-dev-brand-brief-parser` pattern)

---

## PHASE A — Migration

File: `migrations/versions/031_acp_silver_s3_v2.sql`

```sql
-- Migration 031: acp_silver_s3 v2 — ads_plan table
-- Issue: AA-45 | Sprint: M3
-- Note: social_plan moved to AA-80 (S4-social, M4)

CREATE TABLE IF NOT EXISTS acp_silver_s3.ads_plan (
    ads_plan_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        UUID NOT NULL REFERENCES acp_shared.acp_runs(run_id) ON DELETE CASCADE,
    tenant_id     VARCHAR(50) NOT NULL REFERENCES acp_shared.tenants(tenant_id),
    country       VARCHAR(100) NOT NULL,
    model_id      VARCHAR(100) NOT NULL,
    campaigns     JSONB NOT NULL DEFAULT '[]'::jsonb,
    pdf_s3_key    TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE acp_silver_s3.ads_plan ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON acp_silver_s3.ads_plan
    USING (tenant_id = current_setting('app.current_tenant'));

CREATE INDEX idx_ads_plan_run ON acp_silver_s3.ads_plan(run_id);
CREATE INDEX idx_ads_plan_tenant ON acp_silver_s3.ads_plan(tenant_id, created_at DESC);
```

---

## PHASE B — Lambda

### Project layout

```
services/acp_s3/
├── handler.py                  # Lambda entry point
├── planner.py                  # compact_packet + skeleton + expand
├── ads.py                      # Google Ads generator
├── lessons.py                  # 3-tier lesson read/write/promote
├── validators.py               # 5 deterministic checks
├── models.py                   # Pydantic schemas
├── prompts/
│   ├── planning_rules_compact.md
│   ├── calendar_expand_prompt.md
│   ├── google_ads_prompt.md
│   └── lesson_update_prompt.md
├── tests/
│   ├── test_planner.py
│   ├── test_ads.py
│   ├── test_validators.py
│   └── test_lessons.py
└── requirements.txt
```

### requirements.txt

```
boto3>=1.34.0
pydantic>=2.0
psycopg2-binary>=2.9
fpdf2>=2.7.9
```

### S3 logic flow (v1.1 §4.4 — canonical, supersedes v1.0)

**Step 1 — Read inputs from DB**
```
acp_run_context (JSONB fields):
  - s2_keyword_research   → {market_1, market_2, keywords{vol_m1, vol_m2, competition, cpc, intent}}
  - s2_visibility_report  → {content_opportunities[], blog_briefs[], social_ideas[]}
  - s1_keywords_used      → [str]  ← ANTI-CANNIBALIZATION source of truth
  - brand_brief           → JSONB

tenant_brand_rules:
  - system_prompt, style_guide, forbidden_words[]

acp_lessons_agency (tenant+country scoped, RLS):
  - tier: 'job' → last 5 runs
  - tier: 'root' → country-level durable

acp_lessons_shared (cross-tenant, no RLS):
  - tier: 'system' → all runs
```

**Step 2 — Build compact_packet**
```python
# Top 18 keywords by max(vol_market1, vol_market2)
# funnel_mix: 20/60/20 TOFU/MOFU/BOFU (configurable per tenant via brand_brief or default)
# cadence: 12 weeks × 2 posts/week = 24 posts (configurable)
compact_packet = {
    "top_keywords": top_18,
    "funnel_mix": {"tofu": 20, "mofu": 60, "bofu": 20},
    "cadence_weeks": 12,
    "posts_per_week": 2,
    "country": run.country,
    "lesson_summary": "...",  # concat job+root+system lessons
}
```

**Step 3 — Bedrock Sonnet skeleton call**
```
model: us.anthropic.claude-sonnet-4-5  ← MUST use cross-region inference profile
anthropic_version: "bedrock-2023-05-31"
prompt: planning_rules_compact.md + compact_packet JSON
output: JSON {document_title, weeks: [{week: N, posts: [{title_topic, primary_keyword,
         secondary_keywords[], search_intent, word_count, format, brief_outline[], lead_magnet_cta}]}]}
```

**Step 4 — Bedrock Sonnet expand call**
```
model: us.anthropic.claude-sonnet-4-5
prompt: calendar_expand_prompt.md + skeleton JSON + tenant rules
output: rich Markdown — H2 "## Week N", post blocks with "Primary Keyword:", "Lead Magnet CTA:"
```

**Step 5 — Bedrock Haiku ads call**
```
model: us.anthropic.claude-haiku-4-5
prompt: google_ads_prompt.md + compact_packet
output: {campaigns: [{campaign_name, objective, ad_groups: [{name, keywords[], headlines[], descriptions[]}]}]}
Note: JSON + strategy → store in ads_plan.campaigns JSONB + generate PDF via fpdf2 → upload to S3
```

**Step 6 — Deterministic validators (validators.py — 5 checks)**
```python
# All 5 must pass. On failure: return partial output + validation_errors[], do NOT block run.
def check_week_structure(markdown: str) -> bool:
    # "### Week N" present for each week (regex r"### Week \d+")

def check_primary_keyword_labels(markdown: str) -> bool:
    # "Primary Keyword:" present in each post block

def check_lead_magnet_cta(markdown: str) -> bool:
    # "Lead Magnet CTA:" present at least once

def check_no_banned_country(posts: list, active_country: str) -> bool:
    # primary_keyword must not contain names of OTHER countries
    # (e.g. if running Vietnam, "Korea cycling tours" as primary_keyword = fail)

def check_anti_cannibalization(posts: list, s1_keywords_used: list[str]) -> bool:
    # Zero overlap between post primary_keywords and s1_keywords_used
    # Case-insensitive exact match
```

**Step 7 — Bedrock Haiku lesson_update call**
```
model: us.anthropic.claude-haiku-4-5
prompt: lesson_update_prompt.md + run metadata + existing lesson_summary
output JSON:
{
  "job_lessons": ["..."],           # tier 1 — this run only
  "root_lessons_append": ["..."],   # tier 2 — country-level durable
  "system_promotions": ["..."]      # tier 3 — cross-tenant (only if confidence >= 0.85)
}
```

**Step 8 — Write lessons**
```sql
-- Tier 1+2: tenant+country scoped
INSERT INTO acp_shared.acp_lessons_agency (run_id, tenant_id, country, tier, content, created_at)
VALUES (..., 'job', ...), (..., 'root', ...);

-- Tier 3: cross-tenant shared (only system_promotions with confidence >= 0.85)
INSERT INTO acp_shared.acp_lessons_shared (content, country, promoted_from_run_id, created_at)
VALUES (...);
```

**Step 9 — Write outputs**
```sql
-- acp_run_context (JSONB UPDATE)
UPDATE acp_shared.acp_run_context SET
    s3_content_calendar = <calendar_json>,
    s3_ads_plan = <ads_json>,
    s3_funnel_mix = '{"tofu":20,"mofu":60,"bofu":20}'
WHERE run_id = <run_id>;

-- content_calendars (existing table in acp_silver_s3)
INSERT INTO acp_silver_s3.content_calendars (...) VALUES (...);

-- ads_plan (new table, migration 031)
INSERT INTO acp_silver_s3.ads_plan (run_id, tenant_id, country, model_id, campaigns, pdf_s3_key, input_tokens, output_tokens)
VALUES (...);
```

**Step 10 — Gate 2 HITL + EventBridge**
```sql
-- acp_hitl_requests
INSERT INTO acp_shared.acp_hitl_requests (run_id, gate, reviewer_email, status, expires_at, created_at)
VALUES (<run_id>, 2, 'ms.thu@adventure-asia.com', 'pending', NOW() + interval '24 hours', NOW());
```
```python
# EventBridge emit
eventbridge.put_events(Entries=[{
    "Source": "acp.s3",
    "DetailType": "acp.s3.completed",
    "Detail": json.dumps({"run_id": str(run_id), "tenant_id": tenant_id, "gate": 2}),
    "EventBusName": "aa-cis-dev-acp-events"
}])
```

### Bedrock client pattern
```python
import boto3, json

bedrock = boto3.client("bedrock-runtime", region_name="us-west-1")

def invoke_bedrock(model_id: str, prompt: str, max_tokens: int = 4096) -> dict:
    response = bedrock.invoke_model(
        modelId=model_id,  # us.anthropic.claude-sonnet-4-5 or us.anthropic.claude-haiku-4-5
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]
        })
    )
    body = json.loads(response["body"].read())
    # Log for cost tracking
    log_tokens(body["usage"]["input_tokens"], body["usage"]["output_tokens"])
    return body

# ThrottlingException: retry 2x → fallback gpt-4.1 (v1.0 Q3)
```

---

## PHASE C — API + Portal

### FastAPI router: `api/routers/v1_s3.py`
Register in `main.py` alongside existing v1_s1, v1_s2 routers.

```
POST /v1/s3/run
  Body: {run_id: UUID, tenant_id: str}
  Action: boto3 lambda invoke RequestResponse "aa-cis-dev-acp-s3-campaign-planner"
  Response: {run_id, status: "running"}

GET /v1/s3/runs/{run_id}
  Response: {run_id, status, calendar_summary, ads_summary, validation_errors[], created_at}
  Source: acp_shared.acp_runs JOIN acp_silver_s3.content_calendars

POST /v1/hitl/gate2/{run_id}/approve
  Auth: hitl_reviewer only
  Action: UPDATE acp_hitl_requests SET status='approved'
          INSERT acp_shared.audit_log (action='hitl.gate2.approve', actor_type='hitl_reviewer')
          PUT EventBridge acp.s3.gate2.approved
  ⚠️ NEVER auto-approve. NEVER skip audit_log.

POST /v1/hitl/gate2/{run_id}/reject
  Body: {notes: str}  ← required, 422 if empty
  Action: UPDATE acp_hitl_requests SET status='rejected'
          INSERT acp_shared.audit_log (action='hitl.gate2.reject', actor_type='hitl_reviewer', notes=notes)
```

### Portal: `app/workspace/s3/review/page.tsx` (AA-ACP-App)
- Use existing `WorkspaceLayout` shell
- Use existing `apiClient` pattern
- Show:
  - Header badge: "Gate 2 — Ms. Thu Required" (red/amber)
  - Content calendar: render expanded_markdown as `<ReactMarkdown>`
  - Ads plan: JSON accordion per campaign → ad groups → headlines/descriptions
  - Funnel mix stats: TOFU/MOFU/BOFU bar (simple CSS, no chart lib needed)
  - Validation warnings: if validation_errors[] non-empty, show yellow banner
- Actions:
  - "Approve" button → POST /v1/hitl/gate2/{run_id}/approve (confirm modal)
  - "Reject" button → POST /v1/hitl/gate2/{run_id}/reject (requires notes textarea, min 10 chars)

---

## Gate 2 Rules (NON-NEGOTIABLE — v1.0 Q5 + §2.2)

| Rule | Value |
|------|-------|
| Reviewer | Ms. Thu ONLY |
| Auto-approve | NEVER |
| actor_type in audit_log | `hitl_reviewer` always |
| SLA | 24h (expires_at = created_at + 24h) |
| Escalation at 20h | Nghiep sends reminder to Ms. Thu |
| Emergency approve at 24h | Nghiep only IF Ms. Thu confirms unavailable |
| audit_log | Mandatory on every approve/reject — no exceptions |

---

## Tests (add to existing test suite)

```
tests/services/test_acp_s3_validators.py  — 5 validator functions, happy + fail paths
tests/services/test_acp_s3_planner.py     — compact_packet (top 18, funnel math, cadence calc)
tests/services/test_acp_s3_handler.py     — mock Bedrock → full handler flow, mock DB writes
```

CI gate: existing `ci.yml` — Lint + Unit + Integration + Docker. All must pass.

---

## Commit + Linear

```
Commit: feat: S3 campaign planner Lambda + Gate 2 HITL [AA-45]
Linear: Update AA-45 → In Progress when starting, Done when CI green
```
