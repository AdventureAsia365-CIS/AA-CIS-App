# AA-455 — STEP 0: T11 (Publish) Investigation

Investigate-only. No code changed, no branch built, no migration run. Worktree:
`../aa-cis-app-t11-investigate` (`feature/t11-publish-step0`), isolated from the parallel
AA-454 session per the AA-444 lesson (never share a working tree with another in-flight session).

---

## 1. What SKILL_v2.md (Ms. Thư's research doc) says about T11 — nothing

Read in full: `docs/AI-gent-for automation works/stage4.2_ Social-media contents_v2/SKILL_v2.md`.

This document is a **content-strategy/copywriting spec**, not a pipeline spec. Its scope: brand/
audience/channel intake → 9-goal list → CTA → 3 angles → human picks one → write final content →
internal quality checklist. The workflow (§"Human-In-The-Loop Workflow") has 11 steps and **stops
at step 11: "Save final content if using `content_agent.py`."** There is:

- no mention of "publish," "distribute," "post," "schedule," or any delivery verb
- no mention of any social-platform API, CMS, or external channel integration
- no step after "final content" — the document's own scope ends at content creation

**Conclusion: T11 has no source-of-truth definition in Ms. Thư's research doc at all.** Everything
this doc covers maps to T8/T9 (angle gate + write), confirmed already by AA-439-07 finding #15/#17
(9-step Nghiep workflow traces to this doc's 11-step HITL workflow, angle field mismatch). T11 is
purely a Nghiep/AA-side architectural stage (ADR-2026-038, §3), not something Ms. Thư ever
specified — this matches ADR-2026-038 §11.2's own admission that T11 is "chưa scope kỹ" (not yet
scoped in detail).

---

## 2. AA-439-00-SUMMARY findings #21 and #22 (verbatim)

From `docs/claude_audit/AA-439-00-SUMMARY-tenant-tier-audit.md`:

> **#21** — T11 (Publish) confirmed cleanly absent — by the code's own docstring, not just by
> absence: `deliver_packet()`'s "delivered" is a DB-column flip only, no real social-platform API
> integration exists anywhere in the codebase. (`packets.py:209-247`, full grep) — Real, confirmed
> — matches ADR exactly.
>
> **#22** — None of the 10 real "passed" pieces has ever advanced past packet `status='ready'` —
> zero `delivered_at` values anywhere; `acp_shared.usage_log` (the delivery-accounting table)
> **doesn't even exist** in this database. (live query) — Real, confirmed.

And from the same doc's status table:

> **T11 Publish | Missing | Confirmed by the code's own docstring — DB marker only, no
> social-platform integration (#21, #22)**

---

## 3. Code confirmation — T11 absent, verified this session

### `deliver_packet()` — DB flag flip only

`services/acp_produce/packets.py:208-250`. Its own docstring says outright:

> "AA-367: the `ready` -> `delivered` transition. Today this is ONLY a `packets.status`/
> `delivered_at` marker — there is no real send-to-tenant action, because AA-365 (Gate C / trust
> ramp / veto window review UI) does not exist yet."

The function does exactly two things: (1) calls `write_usage_log()` (see below), (2)
`UPDATE acp_deliver.packets SET status='delivered', delivered_at=now()`. No HTTP call, no
external SDK, no channel dispatch. This is the **N7/N8 admin/flywheel pipeline** — a structurally
separate track from the T-series (see §5 below for why it isn't even the right object for a
T-series T11).

### `acp_shared.usage_log` — no such table exists

Grepped every migration and every `.py` reference to "usage_log". There is **no
`acp_shared.usage_log` table anywhere**. What exists instead, confusingly reusing the same name:

- `usage_log` — a **JSONB column** on `acp_contract.tour_atoms` (migration 079) and again on
  `acp_shared.tenant_atom_state` (migration 098) — an atom-level cited-count array, not a
  delivery-accounting table.
- `write_usage_log()` (`services/acp_produce/atom_usage.py`) writes into that JSONB column via
  `UPDATE ... SET usage_log = usage_log || $2::jsonb`, not into any separate ledger table.

So AA-439's finding #22 is precise: there is no dedicated delivery/publish accounting table under
that name — only an atom-usage-count column that happens to share the name.

### T9/T10 pipeline stop point — the real "input" object for a T-series T11

Read `services/acp_content_writing/service.py` and `api/routers/v1_content_writing.py`
(AA-450/AA-452). Confirmed:

- The router exposes exactly **two** endpoints: `POST /v1/content-writing/{request_id}/write` and
  `GET /v1/content-writing/pieces/{piece_id}`. Nothing else — no publish/deliver/schedule route.
- `write_and_check()` does write → T10 gate-check → up to 1 retry → persist → **return**. That's
  the entire function. Nothing downstream reads the resulting row.
- The persisted row is `acp_shared.content_piece` (migration 115): `status CHECK IN ('approved',
  'held')` — **only two states exist, neither of which is "published" or "delivered."** No
  `delivered_at`, no `published_at`, no channel-dispatch column at all. Migration 115's own
  comment confirms this was a deliberate scope cut: "T10 (a real, separate future gate) is out of
  scope here" — read in context, the schema was built with zero forward-reserved room for
  publish/delivery state.

**This is the real T11 input object**: a `content_piece` row with `status='approved'`
(`piece_id`, `tenant_id`, `content_text`, `gate_ledger`), joined back (per migration 115's
no-denormalization convention, same as `angle_gate_option`) to its parent `angle_gate_request` for
`channel`/`cta`/`goal`. **Not** `acp_deliver.packets`/`pieces` — that's the older N7/N8 object
model, keyed off `acp_shared.acp_runs` (admin runs), which migration 115's own comment explicitly
says is "wrong for a tenant-self-service request."

---

## 4. Notion — ADR-2026-038 fetched successfully (not skipped)

Page: **"🔴 [21/08/2026] Content Pipeline Redesign — Admin/Tenant Split + A/T Numbering (NGUỒN MỚI
NHẤT)"** — confirmed via `notion-search` + `notion-fetch`, status ACCEPTED, this is the canonical
source (supersedes memory.md HOT for pipeline architecture where they conflict).

**§3/§4 PRD table, T11 row (verbatim, translated):**

| Code | Stage name | Input | Processing | Output | Old-code mapping |
|---|---|---|---|---|---|
| **T11** | Publish/Distribute | Content pass T10 | Export to channel | Published social content | = N8, **still doesn't exist** |

**§0.2 — the load-bearing principle for T11's approval design:**

> "AA does NOT gate/approve tenant content at any step in the T0-T11 chain. AA only controls via
> two layers: (1) rate limit/quota set at tenant creation (limits volume, not content approval),
> and (2) A4 Cross-Tenant Oversight — post-hoc monitoring with intervention capability
> (flag/suspend/force-unpublish), **not a pre-publish gate**."

This directly reversed Gate B (T7) and Marketplace from admin-approval to tenant self-service
(§0.2 itself), and reversed T8's veto-window design to full tenant self-approval (§10.3: "Tenant
tự duyệt hoàn toàn — không còn Trang/AA duyệt hộ trước publish" — "tenant approves entirely
themselves — no more AA approving on their behalf before publish"). **T11 was never carved out as
an exception to this principle anywhere in the doc** — it's listed under the same T0-T11 chain
§0.2 explicitly covers.

**§7 — channel/social-content spec, but mapped to T8+T9, not T11:**

> "9-step Jira PR-6 workflow + `writing_formulars.xlsx` (8 goals × formula) +
> `Channel_Output_Structures.xlsx` (7 channels × structure/style/avoid) map into **T8 + T9**."
> "Matches S4.2 Social Media Content Engine (D5-D7) design already in archived ACP PRD v1.3 —
> revive + reintegrate into the atom-based architecture (atom is now tenant truth, not platform
> truth)."

So even the ADR's own channel-structure research doc (`Channel Output Structures.xlsx`) is scoped
to T9 (how to *write* for a channel), not T11 (how to *push* into that channel).

**§11.2 roadmap, T11 row (end-of-session status, 21/08/2026):**

> Backend: ❌ Chưa (not yet) | Frontend: ❌ Chưa | Việc còn lại: **"Chưa scope kỹ"** (not yet
> scoped in detail)

**Explicit conclusion from the ADR's own authors: T11 has never been designed, only named and
slotted into the T0-T11 sequence.** This AA-455 STEP0 task is the first real scoping attempt.

---

## 5. Real platform/CMS integrations — what exists vs. what doesn't

Searched the whole repo for WordPress/CMS mentions and for social-platform API clients (Facebook
Graph API, TikTok API, Instagram API, Buffer, Hootsuite, Zapier, SendGrid/SES/Mailchimp).

### The 8 real tenant channels (confirmed, `admin.py:1119` / `tenants/page.tsx:721`, AA-449 fix)

```
blog, facebook, tiktok, email, linkedin, instagram, landing_page, ads
```

### What has real, working integration code

**Only `blog` — via a WordPress REST API adapter — and it is structurally disconnected from the
T-series pipeline:**

- `services/acp_s4_blog/cms/wordpress.py::WordPressAdapter` — real, working code. Uses WordPress
  REST API v2 (`/wp-json/wp/v2/posts`), Application Password Basic-auth, real `aiohttp` POST call.
  **But it always creates the post as `status: "draft"`** — its own docstring: "Posts always
  created as 'draft' — human publishes manually (PRD v1.0 Q6, Q10)." Even this one real
  integration was never designed for true auto-publish.
- `services/acp_s4_blog/cms/publisher.py::publish_draft_to_cms()` — the orchestrator: fetches CMS
  creds from Secrets Manager, reads a draft, calls the adapter, updates
  `acp_shared.acp_cms_publish_queue` + `acp_silver_s4.blog_drafts.cms_publish_status`.
- **Gating**: `api/routers/v1_s4_blog.py` (`/v1/acp/s4/blog/*`) is **100% `_get_admin`-gated** —
  no tenant caller exists.
- **Schema mismatch**: reads/writes `acp_silver_s4.blog_drafts` and
  `acp_shared.acp_cms_publish_queue` (migration 039, 21/05/2026, ticket AA-100 — predates the
  T-series entirely). Neither table has any relationship to `acp_shared.content_piece` (migration
  115). Wiring this to T9/T10 output would mean building a new bridge, not just removing an admin
  gate.
- One relevant design precedent worth keeping: `acp_cms_publish_queue.cms_type` already has
  `CHECK (cms_type IN ('wordpress','webflow','ghost'))` and a per-tenant `cms_secret_key` pointer
  into Secrets Manager — i.e., per-tenant CMS credentials were already anticipated architecturally,
  just never wired to a tenant-facing flow.

### What has zero integration code anywhere

- **facebook, tiktok, instagram, linkedin** — grepped for Graph API / TikTok API / Instagram API
  domains and SDK patterns: zero hits anywhere in the repo.
- **email** — grepped for SendGrid/Mailchimp/SES client usage: zero hits.
- **ads** — no Meta Ads / Google Ads API client anywhere.
- **landing_page** — ambiguous target (AA's own site vs. tenant's own site); no code either way.
- `services/acp_s4_social/` (angles/writer/output) — confirmed by AA-439 finding #12/#13 and
  re-confirmed this session: **no `publish`/`post_to`/`send_to` function exists in this module at
  all**, and no `requests`/`httpx`/`aiohttp` external call either — it stops at generating text,
  same as SKILL_v2.md's own scope.

**Net: the only real, working "publish" integration in the entire codebase is one WordPress
adapter, for one channel, gated to admin-only, wired to a pre-T-series schema, and even it stops
at draft-not-live.** For every other channel (7 of 8), "export to channel" per the ADR's T11 row
has zero prior art to build from — it would be new integration work from scratch, not a
reconnection job.

---

## 6. Proposed route name

Following the existing `/portal/t{n}-*` convention (`t0-brand`, `t1-rewrite`, `t4-pool`,
`t6-atoms`, `t7-planning`, `t8-angle-gate` — the last one already covers both T8 and T9/T10 in one
continuous wizard, per AA-450's mid-build decision):

**`/portal/t11-publish`**

Whether it's a genuinely separate route or gets folded into the end of the `t8-angle-gate` wizard
(mirroring how T9/T10 got folded into T8's page) is a real open design question — not decided
here, flagged for the build task.

---

## 7/8. Proposed architecture — no gate, auto-publish; usage_log/delivered_at schema sketch

**Not a real migration. Sketch only, for Nghiep to react to before a build task is scoped.**

### Gate design: no AA approval gate, per §0.2

Per ADR-2026-038 §0.2 (quoted in full in §4 above) — AA does not gate tenant content anywhere in
T0-T11, only via (1) tenant-creation-time rate limit/quota and (2) A4 post-hoc oversight with
intervention capability. T11 was never listed as an exception. **Conclusion: T11 should
auto-publish the instant the tenant clicks the button on an `approved` `content_piece` row — no
staff review step, no veto window.**

One thing this is **not** in conflict with: the Trust Ramp / Gate C mechanism (`trust_ramp.py`,
kept per ADR §0.5) is explicitly scoped to **T8** (angle *selection*, a new-tenant safety ramp —
"giống thời gian giữ tiền của merchant mới ở cổng thanh toán, không phải kiểm duyệt" / "like a
new merchant's payment-gateway holding period, not content moderation"), not to T11 publish
itself. Nothing in the ADR suggests extending trust-ramp logic to the publish step — flagging this
only because it would be an easy, wrong inference to carry T8's ramp mechanism forward to T11.

### Reachable failure mode worth flagging to Nghiep before build

§0.2's model assumes A4 can `force-unpublish` after the fact. **A4 (Cross-Tenant Oversight) itself
doesn't exist yet** — confirmed Missing per AA-439's own T0-T11 status table and ADR §11.2/§11
roadmap (only a `/admin/a4-oversight` page shell exists, per AA-437). Building T11 as
"auto-publish, AA polices after the fact" before A4's intervention capability is real means there
is, for a real window of time, **no way for AA to pull down a live-published tenant piece** if
something goes wrong (a grounding-check false negative, a brand-rule violation T10's gates missed,
etc.). Not a blocker per the ADR's stated design — just a sequencing risk worth naming explicitly
rather than discovering live.

### Proposed schema sketch (not a real migration)

Two credible shapes, presented as options rather than a decision:

**Option A — extend `acp_shared.content_piece` in place** (fewer moving parts, matches migration
115's "no denormalization, join back to parent" convention):

```sql
-- ALTER acp_shared.content_piece (sketch, NOT a real migration):
ALTER TABLE acp_shared.content_piece
    ADD COLUMN published_at   TIMESTAMPTZ,
    ADD COLUMN publish_target JSONB;  -- e.g. {"channel": "blog", "external_id": "...", "external_url": "..."}
```

Simple, but conflates "was this piece good enough" (T10's job) with "was this piece sent
anywhere" (T11's job) on one row — a piece could be `approved` and never published, or published
and later force-unpublished by A4, and both states need to be representable without re-overloading
`status`.

**Option B — a dedicated `acp_shared.publish_log` table** (mirrors the real
`acp_cms_publish_queue` precedent from migration 039, but scoped to `content_piece` instead of the
old `blog_drafts`):

```sql
-- CREATE acp_shared.publish_log (sketch, NOT a real migration):
CREATE TABLE acp_shared.publish_log (
    publish_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    piece_id        UUID NOT NULL REFERENCES acp_shared.content_piece(piece_id),
    tenant_id       UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    channel         TEXT NOT NULL,          -- one of the 8 real channels
    status          TEXT NOT NULL CHECK (status IN ('published', 'unpublished', 'failed')),
    external_id     TEXT,                    -- e.g. WP post_id, FB post id
    external_url    TEXT,
    published_at    TIMESTAMPTZ,
    unpublished_at  TIMESTAMPTZ,             -- set by A4 force-unpublish
    unpublished_by  TEXT,                    -- staff user id, distinguishes A4 action from tenant action
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Keeps T10's approval state (`content_piece.status`) and T11's delivery state (`publish_log`) as
two separate concerns — closer to how `acp_cms_publish_queue` already models it, and gives A4's
future `force-unpublish` a real row to act on without mutating `content_piece` itself.
**Recommendation (not a decision): Option B**, mainly because it keeps A4's future
force-unpublish auditable (who unpublished what, when) without touching T9/T10's own row — but
this is Nghiep's call, not settled here.

Neither option resolves the deeper open question from §5: **what actually happens on
`channel != 'blog'`** — there is no adapter to call for facebook/tiktok/instagram/linkedin/email/
ads/landing_page. Any schema is postable regardless of whether the channel-side integration
exists; the integration work itself is the larger unscoped item, not the schema.

---

## Summary for Nghiep

- T11 has **no design source anywhere** — not in Ms. Thư's SKILL_v2.md (stops at "write content"),
  not in the current codebase (`deliver_packet()` is a DB-flag flip for the *wrong* pipeline
  object, N7/N8's `packets`, not T9/T10's `content_piece`), and the ADR that named it
  (ADR-2026-038) explicitly says T11 is "chưa scope kỹ" — this task is the first real scoping pass.
- The one real external-publish integration that exists (WordPress, `acp_s4_blog/cms/`) is
  admin-only, wired to a pre-T-series schema, and even it only pushes drafts (a human still clicks
  publish inside WordPress). 7 of 8 real tenant channels have zero integration code anywhere.
- Architecturally, ADR §0.2 is unambiguous: T11 should be tenant-self-service, auto-publish, no AA
  gate — consistent with how T7/T8 were already reversed from admin-gated to self-service. The
  real open risk is sequencing: A4 (the post-hoc safety net §0.2 relies on) doesn't exist yet.
- Recommended next step before a Linear T11 build issue gets written: a decision from Nghiep on
  (a) whether T11 ships blog-only first (reusing/rewiring the one real WordPress adapter) with
  other channels deferred, or waits for real integration work across all 8 channels, and (b)
  Option A vs. B above for the delivery-state schema.
