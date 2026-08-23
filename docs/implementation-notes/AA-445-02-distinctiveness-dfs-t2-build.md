# AA-445-02 — B4 CompetitorIndex + score_distinctiveness() + DFS→T2 + competitor UI

Branch `feature/aa-445-02-distinctiveness-dfs-t2-build`, worktree `../aa-445-02-worktree`.
Continues `AA-445-01` (`docs/claude_audit/AA-445-01-dfs-distinctiveness-step0-audit.md`) —
findings from that report are treated as given, not re-derived.

## Decisions (not specified in the task prompt)

1. **`score_distinctiveness()` is wired only at T5 (`run_t5_atomize`, `owner_scope=tenant_id`
   atoms), not at N2's platform-scope decompose (`v1_atoms.py::_decompose_inline`,
   `owner_scope='platform'`).** Reason: `CompetitorIndex` is inherently tenant-relative
   (`competitor_inputs.tenant_id`); platform-scope atoms have no single owning tenant to score
   against (D3 — atoms stay platform-scoped, tenancy only inherited via `tour_id ->
   raw_tours.tenant_id`, and platform tours are aa_internal's own catalog, not any one paying
   tenant's). Leaving N2-inserted atoms at their migration-079 default (`LOW`) is the correct,
   already-intentional behavior, not a gap this task should also close. Without this wiring
   `score_distinctiveness()` would exist but never actually run against a real atom — this
   decision is what makes the task's own "verify tổng" step (an atom's `distinctiveness` visibly
   changes, N5/N6-readable) possible at all.
2. **New table for the CompetitorIndex corpus**: `acp_shared.competitor_index_cache`
   (migration 111) — nothing in the current schema persists fetched competitor phrase text
   (confirmed in AA-445-01 Q4: `competitor_inputs` stores only input URLs, never fetched
   content). Cached per `(tenant_id, country)`, TTL 24h (same order of magnitude as
   `seo_context`'s Redis 24h layer and S2 Apify's 3-day cache — picked 24h since this is live
   homepage scraping of a tenant-declared list that can change at any time, shorter felt safer
   than S2's 3d for a first cut). Without this, every T5 atomize call for a tenant with several
   tours would re-fetch every competitor homepage from scratch — real latency in a synchronous
   T2→T3→T5 chain and needless outbound traffic to competitor sites.
3. **`requests.get` → `httpx.AsyncClient`, not the `requests` package.** The task's own prose
   (and AA-317/`aamc/corpus.py`) says "`requests.get`, best-effort" — but `requests` isn't in
   `requirements.txt` (only `httpx>=0.27.0`, already used the same way for outbound best-effort
   fetches in `services/acp/s2/tools/apify.py`). Using the already-pinned async-native client
   avoids a new dependency and avoids blocking the event loop synchronously inside an `async def`
   (which a real `requests.get` call would do without an `asyncio.to_thread` wrapper). Same
   "one plain best-effort GET per domain" semantics either way.
4. **Sentence-split/phrase-cap constants kept from the reference (`40 < len < 220` chars per
   phrase, cap 120 phrases/domain)** — these are tuning constants, not architecture, and the
   reference values are the only ones with any real-world grounding behind them.
5. **UI location: a second tab inside the existing `/portal/t0-brand` page**, not a new
   top-level route. ADR-2026-038 §0.4's own reasoning ("cùng chỗ tenant nhập thông tin riêng của
   họ") and the task prompt's own suggestion both point here; the real route naming convention
   already in this repo (`t0-brand`, `t1-rewrite`, `t4-pool`, `t6-atoms`) has no natural "t0b"
   slot, and this data is genuinely T0-stage tenant setup, not a separate pipeline stage.

## Changed (vs. the reference `aamc/corpus.py`)

- `CompetitorIndex` here is a small dataclass (`phrases: list[str]`, `competitors: dict[str,
  list[str]]`), not the reference's full `Workspace`-persisted pydantic model — this repo has no
  `Workspace`/`LAYOUT` file-store concept (JSON-on-disk), everything is Postgres-backed.
- Domain source: `acp_silver_s2.competitor_inputs` (already-built AA-88 table/API), not a fresh
  `domains: list[str]` input — per the task's own decision #3.

## Should know before reading the diff

- `run_t5_atomize()`'s signature gained a `country: str` param (competitor lookup is
  `(tenant_id, country)`-scoped, matching `competitor_inputs`' own grain) — its one real caller
  (`v1_tours.py`) already has `tour_dict["country"]` in scope.
- `run_t3_qa_gate()`'s signature gained an optional `seo_data: dict | None` param, threaded to
  its internal repair-round `_rewrite_tour()` call — without this, a T3 repair round would keep
  regenerating with `seo={}` even after the T2 entry-point fix.

## Tradeoffs

- **Reused `run_t3_qa_gate()`'s repair-round `seo_data` rather than re-fetching per attempt.**
  A repair round re-runs `_rewrite_tour()` with the SAME `seo_data` computed once at the T2
  entry point, not a fresh `process_seo()` call per attempt — correct, since the tour's SEO
  context doesn't change between repair attempts on the same tour_id within one request; a
  second fetch would just be the same $0.18 spent twice for identical data.
- **`build_competitor_index()` cost is paid inline, synchronously, inside T5** (not
  backgrounded/queued) — consistent with T5 itself already running inline inside the
  `_do_rewrite_and_save()` background task (not blocking the HTTP response), and with the
  24h cache meaning most real calls are a single indexed DB read, not a network fetch. A
  tenant's FIRST atomize call after declaring new competitor domains (or after the 24h TTL
  expires) pays the real fetch cost — accepted as the same class of latency AA-317's own
  design already accepted for A1's `process_seo()` call.
- **No backfill for the 2,566 already-`LOW` atoms** (2,551 platform-scope + 15 pre-existing
  tenant-scope, per AA-439-03) — this task only wires new T5 atomize calls going forward, since
  N2's platform-scope atoms are explicitly out of scope (Decision 1) and re-scoring existing
  tenant-scope atoms would need a separate backfill job, not asked for in this task's steps.

## Verify results (this session, in a local ephemeral venv — no live ECS/RDS touched)

- **New tests**: `tests/unit/test_aa445_competitor_index.py` (13 tests: `score_distinctiveness()`
  pure-logic cases incl. empty-index-returns-MED, high/partial/zero overlap bucketing, output
  always ∈ {HIGH,MED,LOW}; `_extract_phrases()` tag-stripping/length-bounds/120-cap;
  `build_competitor_index()` cache-hit-skips-fetch, no-domains, fetch-failure-doesn't-raise,
  successful-fetch) + `tests/unit/test_aa445_t5_distinctiveness.py` (2 tests: the real INSERT
  carries per-atom `score_distinctiveness()` output — not a flat/hardcoded value — and an
  empty country doesn't crash T5). **15/15 passed.**
- **Full existing suite**: `pytest tests/unit/ -q` → **1380 passed, 1 skipped, 1 failed** (fresh
  venv, `pip install -r requirements.txt` + local `AA-ACP-Core` editable install). The 1 failure
  (`test_aa300_admin_atoms.py::test_bulk_route_registered_before_dynamic_atom_id_route`) is a
  pre-existing, unrelated FastAPI/Starlette version-pinning conflict (`TypeError: Client.__init__()
  got an unexpected keyword argument 'app'`, inside Starlette's own `TestClient.__init__`) — not
  in any file this task touched (`api/routers/admin_atoms.py` is untouched this session), and the
  test's own docstring already documents this exact class of environment fragility from an
  unpinned `fastapi>=0.110.1` resolving a newer major than the pinned Starlette supports. Not
  fixed here (out of scope — a dependency-pinning issue, not a code defect this task introduced).
- **`flake8 --max-line-length=120`**: clean on every changed/new Python file.
- **Frontend**: `npx tsc --noEmit` — 0 errors, whole project. `npx eslint` on the new/changed
  `.tsx` files surfaces the same `react-hooks/set-state-in-effect` finding that ALSO fires,
  identically, on the pre-existing unmodified `BrandTab.tsx`/`AtomsTab.tsx` (same
  `useEffect(() => { load(); }, [])` pattern already used throughout this codebase's portal tab
  components) — confirmed via a side-by-side eslint run. Not a regression, matches established
  convention; also confirmed this repo's CI does not run frontend ESLint at all (grepped
  `.github/workflows/*.yml` for `eslint`/`next lint` — zero hits), so this isn't a merge-blocking
  finding either way.
- **NOT verified live** (no ECS/RDS access from this environment, `main.py` needs `acpcore`
  which was only pip-installed in the local ephemeral venv for testing, not deployed): migration
  111 has not been applied to any real database; the end-to-end chain (UI add domain -> T5
  atomize -> N5/N6 read the new value) has not been run against real Bedrock/DataForSEO/live
  competitor homepages. This is flagged explicitly, not glossed over — the task's own "Verify
  tổng" section asks for this; it requires `cis-start` (AWS resources currently stopped per this
  repo's own CLAUDE.md) and is a live-session action for Nghiep/a follow-up session, not
  something achievable from this sandboxed build session.
