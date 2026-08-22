# AA-438 — Audit A1→A2 (Generic Rewrite → Admin QA Gate)

Audit only. No code changed. Every claim below is backed by a `path:line` snippet or a real
DB query result (S3-mediated ECS exec, `aa-cis-dev-cluster` / `aa-cis-dev-db`, run 22/08/2026).
Continues directly from `docs/claude_audit/AA-438-01-a0-a1-audit.md` (A0→A1). ADR-2026-038's
own text was **not** re-attempted here (confirmed absent from the repo in AA-438-01) — this
report is code+data only, same as the prior one.

---

## 1. Answer to the core question: yes, A2 = the `status='hitl'` rows, reviewed via the Review Queue

**A2 (Admin QA Gate) is not a separate endpoint or a not-yet-wired step.** It is exactly the
set of `silver_aa_internal.generated_content` rows written with `status='hitl'` by A1's own
writer, surfaced to a human through the real `/admin/review` page ("Review Queue" in the
sidebar). There is no other "QA check" step running after A1 that isn't yet connected to a UI —
the gate *is* the review page, confirmed end-to-end below (graph → writer → queue table → API →
FE → approve → export).

---

## 2. Where `status='hitl'` is actually decided — NOT inside `graph.py`

This nuance matters and the task prompt's framing needed correcting: **no node in
`services/content_generation/graph.py::build_graph` writes to the database or sets a string
`'hitl'` on `generated_content`.** The graph only produces an in-memory `ContentState`. The
literal string `'hitl'`/`'approved'` is decided by the **caller**, in
`api/routers/admin_pipeline.py`, using a value computed from the graph's final state.

- `graph.py:708-717` (`should_retry`) is the actual branch point:
  ```python
  def should_retry(state: ContentState) -> str:
      retry_count = state.get("retry_count", 0)
      score       = state.get("quality_score", 0)
      if score >= MIN_QUALITY:      # 7.0
          return "done"
      if retry_count < MAX_RETRIES - 1:   # MAX_RETRIES = 3
          return "retry"
      return "hitl"
  ```
- The conditional edge (`graph.py:825-829`) wires this: `"done" → brand_audit` (continues to
  `flag_fix → revalidate → END`), `"retry" → increment_retry → generate` (loop, re-attempt),
  `"hitl" → END` **directly** — skipping `brand_audit`/`flag_fix`/`revalidate` entirely. So a
  tour that never clears `quality_score >= 7.0` within `MAX_RETRIES=3` attempts exits the graph
  with no brand audit and no auto-fix pass at all.
- Back in the caller, `_is_publishable()` (`admin_pipeline.py:73-85`) is the actual DB-status
  gate, and it is **stricter** than just `should_retry`'s score check — it also blocks on
  `brand_audit_status == "manual_check"` and on `flagged`-but-unfixed:
  ```python
  def _is_publishable(result: dict) -> bool:
      audit = result.get("brand_audit_status")
      return (
          result.get("quality_score", 0.0) >= 7.0
          and audit != "manual_check"
          and not (audit == "flagged" and not result.get("fix_pass_applied"))
      )
  ```
- The write itself, `admin_pipeline.py:531`: `status = "approved" if _is_publishable(result) else
  "hitl"`, then `INSERT INTO silver_aa_internal.generated_content (..., status, ...)` at
  `:557-577`.

**So `status='hitl'` fires for two structurally different reasons, both landing on the same
label:**
1. Never reached `quality_score >= 7.0` after 3 retries (routed to `END` before brand_audit even
   ran — `should_retry` → `"hitl"`), **or**
2. Did clear 7.0 but failed the audit-aware gate post-`revalidate` (`brand_audit_status ==
   "manual_check"`, or `"flagged"` with no successful `flag_fix`) — this path DID run
   `brand_audit → flag_fix → revalidate`, it just didn't come out clean.

Nothing in the DB (`generated_content.status='hitl'` alone) distinguishes case 1 from case 2 —
you'd need `quality_scores.brand_audit_status` / `failure_codes` (both are in fact returned by
`/admin/review-queue`, see §4) to tell them apart per-row. Not further disambiguated per-row in
this audit (out of scope — the queue UI already surfaces `failure_summary` per row for this).

**A second, structurally identical call site exists in the same function** at
`admin_pipeline.py:670-683` (`status = "approved" if _is_publishable(result) else "pending"` —
note: the *local variable* here is literally named `"pending"`, not `"hitl"`; it is **never**
written to the DB column, it only decides in-function whether to call
`process_export()` immediately or call `_enqueue_review()`). Confirmed by reading both blocks
in full (`admin_pipeline.py:334` `_execute_run_tour`, single function) — this is not two
different rewrite paths, just the same gate computed twice with two different local-variable
names for the same boolean, one used for the DB `status` column, one used for control flow.

---

## 3. Trigger A1→A2: automatic within one rewrite run — no separate manual step

`should_retry`'s branch (§2) fires automatically inside `_execute_run_tour`, the same function
that A1's "Run Rewrite" button calls (`POST /admin/run-tour-async`, confirmed in AA-438-01 §2).
There is **no manual action between A1 finishing a tour and it landing in `status='hitl'`** —
the moment a rewrite scores below 7.0 (after retries) or fails the post-fix audit, the same
request that ran the rewrite also does the INSERT with `status='hitl'` and the
`_enqueue_review()` call (`admin_pipeline.py:679-683`). The only manual step is what happens
**after** that — a human has to open Review Queue and click Approve/Reject (§5).

---

## 4. `review_queue` table — the actual HITL work queue (separate from `generated_content.status`)

`_enqueue_review()` (`admin_pipeline.py:103-127`) inserts into
`silver_aa_internal.review_queue` (`tour_id, generated_content_id, tenant_id, failure_summary,
score_overall, review_status='pending'`), idempotently (guarded by a `NOT EXISTS` on a pending
row for the same `generated_content_id`). This is the table the Review Queue UI actually reads
— **not** a raw `WHERE status='hitl'` scan of `generated_content`.

- `GET /admin/review-queue` (`admin_pipeline.py:2161-2258`) joins
  `review_queue rq JOIN generated_content gc ... LEFT JOIN quality_scores qs ... JOIN raw_tours
  rt`, defaults `status="pending"` (i.e. `rq.review_status='pending'`), returns all 11 editable
  `gc.*` fields + `failure_summary`, `score_overall`, `failures` (per-field failure reasons via
  `_derive_field_failures`), `human_edited`, `revalidate_passed`, etc.
- `POST /admin/review-queue/{id}/approve` / `/reject` / `/supersede`
  (`admin_pipeline.py:2268-2309`) — the approve/reject ones are thin wrappers that call straight
  into `api/routers/v1_pipeline.py`'s `approve_review`/`reject_review` (comment at
  `admin_pipeline.py:2261-2266` explains why: the `/v1/*` routes sit behind the API Gateway
  Lambda authorizer, admin BFF can't call them directly, so `/admin/*` re-exposes the same logic
  verbatim).

---

## 5. FE: `/admin/review` ("Review Queue" in sidebar) — real, not mocked

Confirmed: `frontend/app/admin/_components/AdminSidebar.tsx:40` — `{ href: "/admin/review",
icon: <ClipboardList/>, label: "Review Queue" }`.

`frontend/app/admin/review/page.tsx` (767 lines) is a real page, not a stub:
- Loads `GET /api/admin/review-queue?status=${filterStatus}` (`:647`), default filter
  `"pending"` (`:639`).
- **Edit**: `PATCH /api/admin/tours/{tour_id}/generated/{generated_content_id}` (`:197-199`),
  resets `revalidate_passed=NULL`, sets `human_edited=true` (per file header comment `:4`).
- **Re-validate**: `POST .../generated/{id}/revalidate` (`:217-218`) — runs
  `build_revalidation_graph()` (`graph.py:787-806`: `validate → llm_judge → brand_audit →
  human_edit_gate → END`, no `generate`/no `flag_fix` — the human edit is treated as final,
  only re-scored).
- **Approve**: `POST /api/admin/review-queue/{id}/approve` (`:673`).
- **Reject**: `POST /api/admin/review-queue/{id}/reject` (`:679`).
- **Regenerate**: fires `POST /api/admin/run-tour-async` again (`:488`), then on success
  auto-supersedes the *old* review row via `POST .../review-queue/{id}/supersede` once the new
  version comes back `status==="approved"` (`:517-534` — comment explicitly: "publishable gate =
  gc.status === 'approved' ... never a score guess").

No mock data path found — every action is a real same-origin `/api/admin/[...path]` proxy call
per the documented convention (`AA-CIS-App/.claude/CLAUDE.md`).

---

## 6. What happens after Approve — confirmed automatic straight to A3 (export/gold), no extra manual step

Read `api/routers/v1_pipeline.py:408-511` (`approve_review`, called by the admin alias
`admin_approve_review`):

1. Atomic claim: `UPDATE review_queue SET review_status='approved' ... WHERE review_status
   ='pending'` (`:432-441`) — also gates human-edited rows on `revalidate_passed IS TRUE`
   (`:439`), 409 with a specific message if blocked (`:454-459`).
2. `UPDATE generated_content SET status = 'approved' WHERE id = $1` (`:465-469`).
3. Branch on `task_token` (legacy Step Functions token, always NULL on the admin/direct path —
   AA-212 enqueue never sets one): NULL → **`await process_export(str(generated_content_id))`
   runs synchronously in the same request** (`:493-498`), `exported=True` returned in the
   response body.

`services/export/handler.py` is the writer for gold (`published_tours`, per AA-438-01's schema
notes) — **not independently re-read line-by-line in this task** (out of scope: task asked to
confirm approve → "does it auto-continue to A3", not to re-audit A3's own internals), but the
call chain (`approve → process_export`, no queued/deferred step, no separate cron/Lambda in
between) is enough to confirm: **yes, approving a hitl tour in the Review Queue auto-continues
to A3 in the same request — no separate manual "publish" click exists or is needed.**
`Reject` (`:515-560`) has **no export call at all** — it only flips `review_status='rejected'`
and (if a legacy SF token existed) calls `send_task_failure`; a rejected tour's
`generated_content.status` is **not** touched and stays `'hitl'` forever (see §7 — this is a
real, confirmed gap, not speculation).

**Not tested live** (no real approve/reject/regenerate call was fired against the 39 real hitl
rows in dev — the task allowed this only "if not risky"; given these are the same 39 real
production-shaped rows AA-438-01 already surfaced and Nghiep hasn't decided what to do with
them, actually approving/rejecting one felt like the kind of state change that should be the
human's call, not this audit's). Everything in §6 is read from code, not observed live —
flagged as such per the task's own instruction.

---

## 7. Real DB state — full status breakdown + age of the 39 hitl rows

Query run 22/08/2026 15:30 UTC via S3-mediated ECS exec against `aa-cis-dev-db`:

```
generated_content BY status:
  approved: 189
  hitl:      39         (matches AA-438-01's count exactly, unchanged)

review_queue BY review_status:
  pending:   48
  approved:   2
  rejected:   2

hitl rows (39) joined to their review_queue row, BY review_status:
  pending:   37
  rejected:   2

hitl rows with NO matching review_queue row at all: 0   (every hitl row IS enqueued — the
                                                          _enqueue_review idempotency guard
                                                          is working as designed)
```

**Confirmed real gap #1: 2 of the 39 hitl rows are `review_status='rejected'` — but
`generated_content.status` is still `'hitl'`.** Reject only flips `review_queue.review_status`
(`v1_pipeline.py:533-537`); it never touches `generated_content.status` (confirmed by reading
the full function, §6). Consequence, confirmed by reading the FE default filter (`review/
page.tsx:639`, `filterStatus="pending"` by default): **these 2 rejected tours are invisible in
the Review Queue's default view** — an admin has to manually switch the status dropdown to
"Rejected" or "All" to ever see them again. They are not stuck/lost data-wise (the reject
decision is durably recorded), but they're not visibly distinguishable from "still needs review"
by glancing at `generated_content.status` alone, and the default UI view undercounts hitl-needing
-attention by 2 (37 shown vs 39 real).

**Age of the 39 hitl rows** (`NOW()` at query time: 2026-08-22 15:30:42 UTC):
```
oldest: created 2026-06-24 03:35 UTC  → age 59 days, 11h54m   (Bike tour)
newest: created 2026-08-21 11:59 UTC  → age  1 day,  3h31m    (Full day city tour — this is
                                                                the same row AA-438-01 already
                                                                flagged as the most recent
                                                                generated_content row overall)
```
So yes — **some tours have been sitting in hitl for close to 2 months**, not days. The oldest 5
rows span 24/06→25/06/2026 (all `review_status='pending'`, `edited_at=null` — never touched by
a reviewer). The 5 newest span 17/08→21/08/2026, one of which (the 21/08 row) is the single
`review_status='rejected'` one from §-above whose newest-created counterpart is invisible in the
default view.

**Secondary, out-of-scope finding surfaced by this query, noted for completeness only:** 11 of
the 48 `review_queue` rows with `review_status='pending'` belong to a **different**
`tenant_id` (`9fb0a3db-59aa-468a-a082-ded01ac50bee`, not the master `00000000-...-000000000001`
this whole A1/A2 pipeline uses) and their `generated_content_id` does **not** match any row in
`silver_aa_internal.generated_content` at all (`LEFT JOIN` → `NULL` status, confirmed
orphaned — not merely a different status). This is very likely a `silver_{tenant_slug}.*`
per-tenant-schema mismatch (per `AA-CIS-App/.claude/CLAUDE.md`'s documented per-tenant schema
pattern) rather than data corruption in the aa_internal pipeline this task audits — **not
investigated further, flagged only, out of scope for A1→A2 (aa_internal/master-tenant only)**.

---

## 8. `pipeline_runs.status` stuck at `'ingesting'` — double-checked, confirmed dashboard-only

Re-verified (not just trusted from AA-438-01): grepped `services/export/handler.py` and
`api/routers/v1_pipeline.py` for every reference to `pipeline_runs` in the approve/export path.
`process_export` only **writes** to `pipeline_runs` (`export/handler.py:78,94`: sets
`status='completed'` when all tours in the batch published) and reads it once, only to fetch
`tenant_id` for a batch (`:130`) — **never reads or branches on `pipeline_runs.status` to
decide whether to run**. Same for `_enqueue_review`, `admin_review_queue`, `approve_review`,
`reject_review` — none of them touch `pipeline_runs` at all. **Confirmed: the stuck
`'ingesting'` status has zero effect on whether a tour can move A1→A2→A3 — it is purely a
dashboard-metrics artifact, exactly as AA-438-01 concluded.** No new contrary evidence found.

---

## Summary

| Question | Answer |
|---|---|
| Is A2 = `status='hitl'` rows? | **Yes, confirmed.** |
| Where is `'hitl'` actually set? | `admin_pipeline.py:531`, using `_is_publishable()` (`:73-85`) fed by `graph.py`'s final `ContentState` — not inside `graph.py` itself. |
| Auto or manual trigger into hitl? | **Automatic** — same request that runs A1 also decides and writes the hitl status. |
| Is there a real UI for the 39 tours? | **Yes** — `/admin/review` ("Review Queue"), real fetch/PATCH/approve/reject/regenerate, no mocks. |
| Does hitl→approved auto-continue to A3? | **Yes** (by code read, not live-tested) — `approve_review` calls `process_export` synchronously in the same request. |
| Does reject clean up `generated_content.status`? | **No** — confirmed gap, 2 real rows currently affected, invisible in the default Review Queue view. |
| Does the `pipeline_runs='ingesting'` bug block A1→A2? | **No**, double-checked — dashboard-only, no code path in the approve/export chain reads it. |
| How stale are the 39 hitl rows? | 1 day to **59 days** old; several from late June never touched. |

## Open items — explicitly unconfirmed

- Which of the 39 hitl rows failed via "never hit 7.0 after 3 retries" (graph exits before
  brand_audit) vs "failed the post-audit gate" (§2, case 1 vs case 2) — not broken down
  per-row in this pass; the data to do it (`quality_scores.brand_audit_status`/
  `failure_codes`, already returned by `/admin/review-queue`) exists but wasn't cross-tabulated
  here.
- `services/export/handler.py`'s own internals (how it writes `published_tours`) — not
  re-read line-by-line; only its call boundary with `approve_review`/`pipeline_runs` was
  checked, since that's what this task's question was about.
- The 11 orphaned/other-tenant `review_queue` rows (§7) — flagged, not investigated (out of
  scope: not part of the aa_internal A1→A2 flow this task covers).
- No live approve/reject/regenerate was fired against real data — §6 is code-read only, per
  the task's own risk guidance.
