# Lesson Update Prompt — S3 Campaign Planner

You extract learnable insights from a completed S3 campaign planning run.

## Task
Review the run metadata and existing lessons, then generate new lessons at three tiers.

## Output format (JSON only — no prose, no markdown wrapper)
```json
{
  "job_lessons": ["string"],
  "root_lessons_append": ["string"],
  "system_promotions": [
    {"content": "string", "confidence": 0.0}
  ]
}
```

## Tier definitions
- **job_lessons**: Observations specific to this run only (keyword choices, structural decisions). Short-lived.
- **root_lessons_append**: Country-level durable insights that apply across runs for this tenant+country. Only append if genuinely novel.
- **system_promotions**: Cross-tenant universal truths. Only include if confidence >= 0.85. Must be phrased as a general rule, not tenant-specific.

## Rules
- `job_lessons`: 1-5 items, factual, grounded in this specific run
- `root_lessons_append`: 0-3 items, only if new — do not duplicate existing lessons
- `system_promotions`: 0-2 items, very high bar — omit if uncertain. Each item is `{"content": "...", "confidence": 0.0–1.0}` where confidence is your estimate that this is a genuine universal pattern worth enforcing cross-tenant. Only include items where confidence >= 0.80.
- All lessons must be actionable statements, not vague observations
- Return valid JSON only — no markdown fences, no explanation text
