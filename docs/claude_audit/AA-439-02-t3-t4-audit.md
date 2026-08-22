# AA-439-02 — Audit T3→T4 (Tenant QA Gate → Tenant Tour Pool)

Audit only, no code changed. Branch `feature/aa-439-tenant-tier-audit`. Continues directly from
`AA-439-01-t0-t1-audit.md` (T0→T1), which already confirmed T1's "Rewrite" triggers T2→T3→T5 in
one job and found T4's "Extra QA pass" badge — this task audits T4 ("Tenant Tour Pool") as its
own independent concept, which AA-439-01 didn't do.

---

## 1. T3 has no dedicated route (confirmed, consistent with prior findings)

Per `AA-436-t3-ui-step0-audit.md` (already on disk, cross-checked, not re-derived): no
`t2-*`/`t3-*`/`t5-*` folder exists under `frontend/app/(tenant)/portal/`. T3's only tenant-
visible surface remains the "Extra QA pass" badge on T4 (confirmed AA-439-01 §3). Nothing found
in this task's own read of the file tree contradicts that — still true today.

## 2. T4 route — confirmed

`frontend/app/(tenant)/portal/t4-pool/page.tsx` → renders `<CatalogTab />`. Sidebar label "My
Catalog" (`Sidebar.tsx:27`). Not to be confused with `/portal/t1-rewrite` ("Browse Pool") — two
distinct pages, confirmed by both route folder names and sidebar entries; no naming ambiguity
found.

## 3. What CatalogTab.tsx actually shows — full read

Data source: `GET /api/tenant/v1/tours/my-versions?page_size=50&status=X`
(`CatalogTab.tsx:3,79`) — **exclusively the tenant's OWN `tenant_tour_versions` rows** (their
rewrites), never raw/un-rewritten pool tours. A tenant with zero rewrites sees an empty catalog,
not the platform's 763-trip pool (that's what T1/Browse Pool is for).

**Filters** (`STATUS_FILTERS`, `:33-36`): "All" / "Queued" (pending) / "In Catalog" (approved) /
"New Version Requested" (rejected) — matches the `tenant_tour_versions.status` enum values seen
live in AA-439-01's DB query (`needs_review`, `approved`, `rejected`, `ai_generated`, `pending`).

**Live polling** (`:97-147`): while any listed version has `status='pending'`, the component
polls `GET .../my-versions` every 5s for up to 5 minutes, auto-refreshing badges and firing a
toast ("✅ rewrite complete — click to review") the moment a row transitions out of pending —
confirmed real, not a static list.

**Per-version display**: `StatusBadge` (maps DB status → label/color, `:594-622`, already
covered in AA-439-01) + `QaAutoPassBadge` (AA-439-01 §3) + a detail panel
(`loadDetail()`, `:154+`) that fetches `GET /v1/tours/versions/{id}` and shows a "See Original"
diff toggle against the source `published_tours` row, plus an inline **edit** form (name,
subtitle, summary, highlights, SEO title/meta — `editName`/`editSubtitle`/etc. state,
`:67-72`) with its own save/approve/reject actions. This is real editing capability, not just a
read-only viewer.

**No atom-count or T5-result field anywhere in this component** — grepped the whole file for
`atom`/`t6`/`distinctiveness`, zero matches. T5's output (how many atoms this rewrite produced)
is invisible on T4, confirmed by absence, not inference.

## 4. From T4, is there any path to T6? Confirmed: no

Grepped the whole file for any `Link`/`router.push`/`href` pointing at `/portal/t6-atoms` or
mentioning atoms — **none found.** `NextStepGuide.tsx` (the status-guidance banner T4 shows,
`CatalogTab.tsx` imports it) — read in full — only maps `status` → a short guidance sentence
("Content is ready. Review below, then add to your catalog.") with **no** T6 pointer either.

**Confirmed: T4 and T6 are two fully independent pages from the tenant's point of view.** A
tenant who wants to see the atoms their rewrite produced has to know to click "Atom Curation" in
the sidebar separately — nothing on T4 tells them that page exists or that a rewrite even
produces atoms. (The empty-state copy on T6 itself does explain the link the other direction —
see AA-439-03 §C — but that's only visible once the tenant has already navigated there.)

## 5. Real DB state (task step 4)

From this task's own live query (22/08 17:32 UTC) plus AA-439-01's already-run query (same data,
cross-referenced, not re-run redundantly):

```
tenant_tour_versions: 23 total, all under 5 tenants (test-agency=13, wanderlux-travel=8,
                       wildkind-travel=2, + 2 more not shown in the by-tenant breakdown
                       — see AA-439-01 §4 for the full table)
By status: needs_review=12, approved=8, rejected=2, ai_generated=1
```

A real tenant logging into T4 today (e.g. `wanderlux-travel`) would see up to 8 rows, mostly (per
AA-439-01's per-tenant breakdown) dated 2026-05, i.e. old test data, not live traffic. No tenant
currently has a large, actively-growing catalog — consistent with this whole tier being newly
built/tested rather than in real production use yet.

---

## Summary

| Question | Answer |
|---|---|
| T3 dedicated route? | No — confirmed still true, consistent with AA-436 STEP0 |
| T4 route | `/portal/t4-pool`, `CatalogTab.tsx` |
| What does T4 list? | Only the tenant's own rewritten `tenant_tour_versions`, never raw pool tours |
| Filters | All / Queued / In Catalog / New Version Requested |
| T4 → T6 navigation? | **None** — fully separate pages, no cross-link either direction from T4 |
| T5 (atom) result shown on T4? | No — confirmed by full-file grep, not inference |
| Real tenant data on T4 today? | Yes, but sparse and mostly stale (2026-05 test data) |
