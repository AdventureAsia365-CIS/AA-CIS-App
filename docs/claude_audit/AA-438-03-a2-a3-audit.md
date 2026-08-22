# AA-438 — Audit A2→A3 (Admin QA Gate → Master Content Pool)

Audit only. No code changed. One live action was taken (approving 1 real hitl tour through the
real endpoint), explicitly authorized by the task prompt as a low-risk, non-rollback-guaranteed
test. Every claim below is backed by a `path:line` snippet or a real DB query / real HTTP
response (S3-mediated ECS exec + an in-container `POST` to the app itself, `aa-cis-dev-cluster`
/ `aa-cis-dev-db`, run 22/08/2026 15:34-15:52 UTC). Continues from
`docs/claude_audit/AA-438-02-a1-a2-audit.md`.

**Headline: the live test not only confirmed A2→A3 works automatically, it accidentally caught
a real, currently-live data-integrity bug in `published_tours` (partial UPSERT — see §3) and
concrete evidence for Nghiep's brand_audit-too-strict hypothesis (see §7).**

---

## 1. `services/export/handler.py::process_export()` — full read

```python
async def process_export(version_id: str) -> dict:
    conn = await asyncpg.connect(get_database_url())
    tenant_slug = os.environ.get("TENANT_SLUG", "aa_internal")
    silver = f"silver_{tenant_slug}"
    ...
    row = await conn.fetchrow(f"""
        SELECT gc.*, rt.country, rt.duration, rt.batch_id, qs.id AS quality_score_id,
               qs.score_overall AS quality_score
        FROM {silver}.generated_content gc
        JOIN {silver}.raw_tours rt ON rt.tour_id = gc.tour_id
        LEFT JOIN {silver}.quality_scores qs ON qs.generated_content_id = gc.id
        WHERE gc.id = $1::uuid AND gc.status = 'approved'
    """, version_id)
    if not row:
        raise ValueError(f"Version not approved or not found: {version_id}")
```
(`handler.py:12-30`)

**The gate is `gc.status = 'approved'` — nothing else.** Re-verified per the task's explicit
instruction not to just trust AA-438-02's summary: grepped every `pipeline_runs` reference in
this file (`:78`, `:94`, `:130`) — all three are **writes** (`tours_passed` count, `status=
'completed'` when the batch's tours are all published) or a single read used only to fetch
`tenant_id` for the manifest step (`:130`, only reached inside the `if batch_id:` block, only
useful for the ACP-S1 manifest below — see §6). **`pipeline_runs.status` is never read to
decide whether export proceeds.** Confirms AA-438-02's finding with a second, independent read
of the same file — no contrary evidence found.

Steps after the fetch:
1. `PublishedCatalogRepository(conn, tenant_slug).insert({...})` — writes the gold row (§2).
2. `UPDATE raw_tours SET pipeline_status = 'published'` (`:69-73`).
3. If `batch_id` is set: update `pipeline_runs.tours_passed` to the batch's exact published
   count (`:77-84`), then check `pending = COUNT(*) WHERE pipeline_status != 'published'`
   (`:86-90`); **only when `pending == 0`** does it flip `pipeline_runs.status` to `'completed'`
   (`:92-97`) **and** kick off an ACP-S1 manifest/EventBridge publish
   (`upload_manifest`/`publish_s1_completed`, `:100-186`) — this writes `shared.acp_runs` and
   `write_run_context_stage(..., "s1", ...)`, i.e. **A3's "batch fully published" event is
   itself the trigger for the ACP N-pipeline's S1 stage** (out of scope to trace further here —
   noted because it's a second, real downstream consumer of A3 completion beyond T1's pool
   browse in §6, discovered while reading this file for the task's actual question).

## 2. A3 confirmed = `gold_aa_internal.published_tours`, via `PublishedCatalogRepository`

`shared/repository/published_catalog_repository.py:15-55` — the `insert()` used by the live
`process_export()` path:
```sql
INSERT INTO gold_aa_internal.published_tours (
    tour_id, generated_content_id, tenant_id, aa_name, aa_subtitle, aa_summary, aa_description,
    aa_highlights, aa_itineraries, mobile_card_text, seo_title, seo_meta, seo_keywords_used,
    og_tags, quality_score, quality_score_id, s3_gold_path, approved_by
) VALUES (...)
ON CONFLICT (tour_id) DO UPDATE SET
    generated_content_id = EXCLUDED.generated_content_id,
    aa_name              = EXCLUDED.aa_name,
    quality_score        = EXCLUDED.quality_score,
    published_at         = NOW()
```

**Structure vs `generated_content` (A1/A2 tier):** essentially a straight column copy — no real
transform. `aa_highlights`/`seo_keywords_used`/`og_tags` are passed through as the already-JSON
-encoded strings `generated_content` stores them as (a prior double-encoding bug is noted inline
at `handler.py:46-52`, already fixed by NOT re-`json.dumps()`-ing). The only genuinely new thing
`published_tours` adds over `generated_content` is `quality_score`/`quality_score_id` (joined in
from `quality_scores`) and `published_at`. `published_tours.tour_id` is `UNIQUE`
(`api/migrations/003_schema_v3.sql:463`) — **one gold row per tour, ever** — confirmed by the
`ON CONFLICT (tour_id)` clause and (destructively) by the live test in §3.

**Real, confirmed bug found by reading this `ON CONFLICT` clause, then proven live in §3: the
UPDATE branch only touches 4 of the 18 inserted columns** (`generated_content_id`, `aa_name`,
`quality_score`, `published_at`). Every other field — `aa_subtitle`, `aa_summary`,
`aa_description`, `aa_highlights`, `aa_itineraries`, `mobile_card_text`, `seo_title`,
`seo_meta`, `seo_keywords_used`, `og_tags` — is **silently left at whatever the FIRST publish of
that `tour_id` wrote**, even when a later, different `generated_content` version is approved and
exported for the same tour.

**Dead/stale code found while comparing structure, noted for completeness:**
`shared/services/export_service.py`'s `ExportService.publish_tour()` is a **different,
unused** writer for the same table — grepped for callers (`ExportService`/`export_service`)
across the whole repo: **zero non-test call sites**. It's also internally inconsistent with the
real schema — its `INSERT` references `slug`, `country`, `is_active` columns that **do not
exist** on `gold_aa_internal.published_tours` per the actual migration (`003_schema_v3.sql:
459-482`); those only exist in this file's own imagination. Its sibling methods
(`create_export`, `trigger_webhook`, `record_delivery_result`) reference
`gold_aa_internal.content_exports`/`webhook_deliveries`, both already flagged as tech debt in
`AA-CIS-App/.claude/CLAUDE.md` ("content_exports table does not exist", "webhook_deliveries =
0"). Conclusion: this file is a stale PRD-v4-era draft, not part of any live path — don't let it
mislead a future reader into thinking `published_tours` has a `slug`/`is_active`/`country`
column, or that webhooks fire on publish.

## 3. Live test — approve 1 real hitl tour → confirmed synchronous export, AND caught the bug from §2 live

Per the task's explicit instruction, picked the single oldest hitl row from AA-438-02's list
that was still `review_status='pending'` (re-checked fresh immediately before acting, not
trusted from the prior report): `generated_content.id = 745532c1-...` (tour "South Korea by
Bicycle: Seoul, DMZ & East Coast — 9 Days", `tour_id = ff413f0e-...`, created 2026-06-24, i.e.
the ~59-day-old row). Confirmed pre-state: `gc.status='hitl'`, `review_queue.review_status
='pending'`.

Called the **real endpoint**, from inside the same ECS task the app runs in
(`POST http://localhost:8000/admin/review-queue/{review_id}/approve`, real `X-Admin-Secret`
read from the container's own env — this is the actual FastAPI process, not a simulation):

```json
{"status": "approved", "review_id": "e4d4d33e-...", "exported": true, "sf_notified": false}
```

Post-state, queried immediately after:
```
generated_content.status:      hitl → approved       ✔ confirmed
review_queue.review_status:    pending → approved    ✔ confirmed
raw_tours.pipeline_status:     -> published           ✔ confirmed
published_tours row (tour_id ff413f0e-...): EXISTED ALREADY before this test (id
  3e6dda3a-...), now updated in place, generated_content_id -> 745532c1 (the version just
  approved), aa_name -> its aa_name, quality_score -> 9.00, published_at -> now.
```

**§3a is answered — yes, approve→export is fully automatic and synchronous** (confirmed by a
real HTTP response, not by reading code this time).

**But `published_before` was NOT null.** This tour_id already had a `published_tours` row
*before* my approve call. Pulling every `generated_content` version for this `tour_id`
explained why: this tour was rewritten **4 times** (`version_num` 1-4, all within one morning,
03:31→08:55 on 24/06/2026) — v1 and v2 were *already* `status='approved'` (i.e. they cleared
`_is_publishable()` immediately at generation time and auto-exported without ever touching
Review Queue — confirmed this is the SAME `_execute_run_tour` code path from AA-438-02 §2, the
direct-approve branch), v3 (`745532c1`) is the one I just approved via Review Queue, v4 sits in
`hitl` untouched.

**Live-confirmed the §2 bug**, comparing the published row's current field values against all 4
`generated_content` versions:

| Column | Value now in `published_tours` | Matches which version |
|---|---|---|
| `generated_content_id` | `745532c1` (v3) | v3 ✔ (just approved) |
| `aa_name` | "South Korea by Bicycle: Seoul, DMZ & East Coast — 9 Days" | v3 ✔ |
| `aa_subtitle` | "A Private Cycling Journey from Seoul's Urban Core to the DMZ..." | **v1** (03:31, the FIRST publish — stale by 4 rewrite rounds and ~59 days) |
| `seo_title` | "South Korea Cycling Tour: Seoul to Busan \| 9 Days" | **v1** (stale — v3's real seo_title is "...Seoul, DMZ & East Coast", never shown) |
| `seo_meta` | "Discover premium South Korea tours packages..." | **v1** (stale — word-for-word v1, not v3's actual meta) |

**This is a real, currently-live data bug, not a hypothetical**: `gold_aa_internal
.published_tours` — which both Master Content (§4) and the tenant-facing T1 pool (§6) read
directly — now shows a tour whose **name** claims to be the (freshly-approved) v3 rewrite, but
whose **subtitle and both SEO fields are actually v1's**, a version from 4 rewrite rounds
earlier that was never meant to be the "current" content once v2/v3 existed. Any tour on this
platform that has ever been rewritten more than once **and republished** carries this same
mismatch — this is not specific to the one row this test touched, it's inherent to the
`ON CONFLICT ... DO UPDATE SET` in `PublishedCatalogRepository.insert()` (§2) and will recur on
every future re-approve of an already-published tour.

## 4. FE "Master Content" — confirmed reading `published_tours` directly

Sidebar: `frontend/app/admin/_components/AdminSidebar.tsx:42` — `{ href:
"/admin/master-content", label: "Master Content" }`.

The page's data load (`frontend/app/admin/master-content/page.tsx:810-817`) calls
`GET /api/tenant/admin/tenants/${AA_INTERNAL_ID}/details` (note: a *different* Next.js proxy
prefix, `/api/tenant/admin/*`, not the `/api/admin/*` convention used by Review Queue/Upload —
still same-origin BFF pattern, just a different route group). Backend:
`api/routers/admin.py:483-540` (`get_tenant_details`) — for the internal tenant
(`plan_tier=='internal'`) it runs:
```sql
SELECT pt.id, pt.tour_id, pt.aa_name, rt.country, pt.quality_score,
       pt.master_status::text AS master_status, ...
FROM gold_aa_internal.published_tours pt
LEFT JOIN silver_aa_internal.raw_tours rt ON rt.tour_id = pt.tour_id
ORDER BY pt.published_at DESC LIMIT 200
```
**Confirmed: yes, directly `published_tours`, no intermediate cache/table.** `total_rewrites`
(the summary count shown at the top of the page) is a plain `COUNT(*) FROM
gold_aa_internal.published_tours` (`:503-505`) — same table, unconditional.

Trash/restore/activate/deactivate actions on this page (`page.tsx:984-1027`, hitting
`PATCH /api/admin/master/{tour_id}/{trash|restore|activate|deactivate}` →
`api/routers/admin.py:1287-1592`) toggle `published_tours.master_status`
(`active`/`inactive`/`trashed`, enum added by migration 052/ADR-018) and `deleted_at` — this
matters directly for §6.

## 5. Real DB counts — before/after the live test

Before (from AA-438-02, unchanged at start of this task): `generated_content` approved=189,
hitl=39. `review_queue` pending=48, approved=2, rejected=2. `published_tours` — AA-438-01 had
reported 72 (said to match `raw_tours.pipeline_status='published'` count at that time).

**After the live approve** (query 22/08 15:52 UTC):
```
generated_content:  approved=190 (+1)   hitl=38 (-1)         — exactly as expected
review_queue:        pending=47 (-1)    approved=3 (+1)   rejected=2 (unchanged)
published_tours:     total = 71
```

**Note, not caused by this test**: `published_tours` total is **71**, not AA-438-01's 72 — my
test only `UPDATE`d an existing row (`ON CONFLICT`, §3), it did not insert a new one, so the
row count could not have changed because of this test (before-test and after-test counts are
identical; I did not separately capture the immediately-pre-test total, but the mechanism proves
it). The 72→71 gap predates this session and is **not investigated further here** — plausibly a
`master_status='trashed'` tour that a hard-delete or cascade elsewhere quietly removed (soft
-delete alone, per §4, would not change `COUNT(*)`), but that would need its own audit. Flagged,
out of scope.

## 6. Does T1 (Tour Selection) read A3 output? Yes — confirmed end-to-end, AND found a real gap vs. Master Content's own gate

Traced the full chain:
- `frontend/app/(tenant)/portal/t1-rewrite/page.tsx:3` (comment: "Was the 'pool' tab... T1 —
  Tour Selection") wraps `<PoolTab />`.
- `frontend/app/(tenant)/portal/_components/PoolTab.tsx:3-4,68-69`: `GET /api/tenant/v1/tours
  /pool` and `GET /api/tenant/v1/tours/my-versions`.
- Backend: `api/routers/v1_tours.py:84-97` (`browse_pool`, docstring: `"""Browse AA shared pool
  (published_tours from aa_internal)."""`) queries `gold_aa_internal.published_tours pt LEFT
  JOIN silver_aa_internal.raw_tours rt` directly (`:130-157`).

**Confirmed: yes, T1's tenant-facing pool reads A3's output directly, no intermediate layer.**

**Real gap found, directly relevant to the A3↔T1 handoff this step asked about**: `browse_pool`'s
`WHERE` clause (`v1_tours.py:104-128`) only ever filters `pt.tenant_id = master` plus optional
user-supplied filters (country/quality/search/duration) — **it does not filter
`pt.master_status = 'active'` or `pt.deleted_at IS NULL` at all.** Compare this to
`acp_contract.v_trip_registry` (migration `090_v_trip_registry_filter_deleted_at.sql:44-47`,
the N4-N6 planning input), which explicitly does: `AND pt.master_status = 'active' AND
pt.deleted_at IS NULL`. **Consequence: a tour an admin has trashed or deactivated in Master
Content (§4's trash/deactivate actions) still shows up, fully browsable and rewritable, in every
tenant's T1 pool.** This is a live, confirmed inconsistency between two real consumers of the
same gold table — one (`v_trip_registry`) respects the lifecycle gate, the other (`/v1/tours
/pool`, the actual tenant-facing endpoint) ignores it entirely.

## 7. Encountered while reading — concrete evidence for Nghiep's brand_audit-too-strict suspicion

The task said not to investigate this deeply but to note anything seen in passing. The live
test in §3 handed a direct, concrete data point: pulled `quality_scores` + the `review_queue`
failure summary for the exact row just approved (`745532c1`, was `hitl` for ~59 days):

```
score_overall: 9.00   score_brand: 10.00   score_seo: 8.50   score_structure: 10.00  score_quality: 10.00
failure_codes (validate_node):       ["META_TOO_SHORT", "DFS_INTENT_UNDERUSED"]
brand_audit_status:                  "manual_check"
brand_audit_codes:                   ["ITINERARY_MEAL_TIME_INVENTED"]
brand_audit_issues (the model's own written justification):
  "The rewrite is highly tailored to the discreet executive adventure angle, with strong
   emphasis on privacy, executive-level logistics, capped group size, and confidential
   arrangements. The language and details ... are all on-brand. To reach a perfect 10, further
   reinforce the 'discreet' aspect ... Consider adding subtle cues about security,
   confidentiality, and seamless transitions..."
```

**This is a tour that scored 9.0/10 overall, a perfect 10/10 on brand fit, whose own
brand-audit narrative reads as an unambiguous compliment ("all on-brand", suggestions are all
"to reach a perfect 10", not "this violates X") — yet `brand_audit_status='manual_check'`
hard-blocked it from publishing via `_is_publishable()`'s `audit != "manual_check"` check
(`admin_pipeline.py:73-85`, per AA-438-02 §2) for 59 days**, over `ITINERARY_MEAL_TIME_INVENTED`
(one brand-audit code, no severity/weight visible anywhere in the row) plus two low-stakes
validate codes (a meta description a few characters under the 140-char floor, and a keyword
not literally echoed in the SEO title/meta). **Not investigated further per the task's
instruction** (a dedicated task on the brand_audit/DFS threshold question was mentioned as
planned) — but this is a real, live example, not a hypothetical, and worth having on hand for
that task: the gap here looks like it's between `brand_audit_status` (a categorical judgment
call from the LLM judge) and the actual content risk its own free-text explanation describes,
not between the rewrite's real quality and the 7.0 score floor.

## Summary

| Question | Answer |
|---|---|
| Does export gate on `pipeline_runs.status`? | **No**, re-confirmed independently — only ever reads it for `tenant_id`, never to decide. |
| A3 = `published_tours`? | **Confirmed.** |
| Structure vs `generated_content`? | Straight column copy + `quality_score`/`published_at` joined in. No real transform. |
| Is approve→export automatic? | **Yes, confirmed live** — synchronous, `exported: true` in the same HTTP response. |
| Any gap in the publish path? | **Yes, confirmed live** — `ON CONFLICT DO UPDATE` on `published_tours` only refreshes 4 of 18 columns; re-publishing a tour leaves subtitle/SEO fields stale from its very first publish. |
| Master Content FE real? | **Yes** — reads `published_tours` directly, no cache layer. |
| Does T1 read A3 output? | **Yes, confirmed** — `/v1/tours/pool` reads `published_tours` directly. |
| Does T1 respect the Master Content trash/deactivate gate? | **No, confirmed gap** — `/v1/tours/pool` has zero `master_status`/`deleted_at` filter, unlike `v_trip_registry` which does. |
| `published_tours` count | 71 now (was 72 per AA-438-01 — 1-row gap unreconciled, out of scope). |

## Open items — explicitly unconfirmed / out of scope

- The 72→71 `published_tours` count gap (§5) — not investigated, plausibly predates this task.
- ACP-S1 manifest/EventBridge trigger on batch completion (`process_export`'s `pending==0`
  branch, §1) — noted as a real second downstream consumer of A3, not traced further (out of
  scope for this task's question).
- The `ExportService`/`export_service.py` dead code (§2) was not deleted or flagged for removal
  — just noted, since the task said no code changes.
- Brand_audit/DFS threshold investigation (§7) — deliberately not pursued per the task's
  instruction; a live data point was captured for whoever picks up that follow-up task.
- Only 1 tour's re-publish history was inspected for the partial-UPSERT bug (§3) — did not scan
  all 71 published rows for how many are affected; the mechanism (§2) guarantees it affects every
  tour republished more than once, but the exact count of currently-affected rows is unknown.
