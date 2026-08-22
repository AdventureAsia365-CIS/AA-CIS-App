# AA-439-06 — Audit T7→T8 (Content Planning → Angle Gate)

Audit only, no code changed. Branch `feature/aa-439-tenant-tier-audit`. Continues from AA-440
(T7 business-logic reuse already audited there, not repeated) and AA-439-03 (confirmed T6 has no
T7 handoff button yet). Every claim below is `path:line` or a real live query (S3-mediated ECS
exec, 22/08 18:57 UTC).

**Headline: there is no T7→T8 handoff in the code today, because T8 as the ADR describes it
(generate 3 angles → recommend → human picks) is not part of the N7/N8 pipeline at all — it's a
complete, working, real implementation that lives entirely in the legacy, sidebar-unlinked ACP
v1 "S4 Social" module, admin-gated, and has never been used even once (0 rows, ever). The
"trust ramp" (Gate C) is real code but has also never actually been exercised — zero ramp
transitions logged, ever, in this database.**

---

## 1. Does anything trigger T8 after T7? Confirmed: no — the two pipelines were never connected

Grepped every file under `api/routers/` and `services/` for `angle` — the ADR's T8 vocabulary
appears **only** in three places, none of which touch the N7/N8 (`services/acp_produce/`)
pipeline at all:

1. `services/content_generation/graph.py` / `judge_node.py` — "angle" used as plain prose
   ("this brand's distinct angle") inside the admin S1-Rewrite brand-differentiation prompt —
   unrelated to T8, a different feature entirely (A1 tier, already audited AA-438).
2. `api/routers/admin.py` — `assigned_angle` (migration 098, AA-309/N1) — a single fixed
   "anti-cannibalization narrative lens" (one of 7 values: culinary_people, physical_terrain,
   etc.) assigned **once per tenant at onboarding**, to keep multiple tenants selling the same
   trips from generating near-duplicate content. **A completely different concept from T8's
   "3 angles per content piece"** — same English word, unrelated mechanism. Not to be confused.
3. **`services/acp_s4_social/`** — the real match (§2 below).

**Grepped `services/acp_produce/` specifically (the module AA-440 confirmed is furthest along
toward T7-T10) for `angle` — zero hits.** Its real pipeline stage that runs right before
drafting is `build_outline(brief)` (`services/acp_produce/pipeline.py:133,361-365`) — a
**structural** outline (H2 sections), not a **strategic-angle** choice; a genuinely different
step, not a renamed version of T8. **Conclusion: T7 (Quarter Plan → Slot Grid, N6) hands off
directly to N7's `build_outline`/drafting stage — there is no angle-generation step anywhere in
that chain, and nothing calls into the module that does have one (§2).** This isn't "the trigger
hasn't been wired yet" — the two pipelines were built independently and have zero shared code
path.

## 2. The real angle-generation implementation — complete, working, but in the wrong pipeline

`services/acp_s4_social/angles.py::generate_angles(brief, llm_client, mode)` (full read, 104
lines) — its own docstring: *"Ports Ms. Thư's `generate_angles()` logic from
`content_agent.py`."* This is the exact "sinh 3 angle" step ADR mục 4 describes:
```python
def generate_angles(brief: ContentBrief, llm_client, mode: str = "auto") -> list[dict]:
    """mode: 'auto' returns [best_angle], 'guided' returns all 3."""
```
`_ANGLE_SYSTEM` prompt: *"generate 3 distinct angles... strategically different — not just
variations."* Each angle: `name`, `why_it_works`, `length_signal`, `style_signal`.

`services/acp_s4_social/handler.py` (full read, 241 lines) wires this into **exactly the
"dual-mode" ADR mục 5 describes**:
- **AUTO**: `run_auto()` — generates all 3 internally, silently takes `all_angles[0]` (the
  LLM's own top-ranked pick), writes, quality-checks, saves. **No human involved at all.**
- **GUIDED**: `run_guided_angles()` (step 1, returns all 3 for a human to pick from) +
  `run_guided_write()` (step 2, writes with whichever angle the human selected).

**Steps 1-3 of the ADR's list ("goal list → brand audience → formula theo goal") are also real,
just not stored as `writing_formulars.xlsx`** — that exact filename does not exist anywhere in
this repo or (checked, best-effort `aws s3 ls --recursive` on the bronze bucket) in S3. Its
functional equivalent is `services/acp_s4_social/formula.py` (full read, 155 lines): a
hardcoded `GOALS` dict (9 goals: Promotion, Lead generation, Conversion, Introduction/Awareness,
Trust-building, Engagement, Event announcement, Product/service explanation, Partner/supplier
communication), each mapped to 1-2 copywriting formulas (`aida`, `pas`, `fab`, `slap`, etc.) with
real markdown reference files (`services/acp_s4_social/references/*.md` — confirmed all 14
formula files + `SKILL.md`/`CONTEXT.md` exist on disk). Docstring: *"Sourced from Ms. Thư's
content_agent.py SKILL.md + references/."* **"Brand audience" (ADR step 2) = `ContentBrief
.brand`/`.audience` fields**, fed into `_angles_prompt()` alongside the goal/channel/topic.
**All 6 of the ADR's numbered T8 steps have real, working code — the whole sequence exists,
just as a spreadsheet-free Python port, and just in the legacy module, not the current one.**

## 3. Where this is exposed — confirmed admin-only, matching the ADR's "chặt nhất hệ thống" claim exactly

`api/routers/v1_s4_social.py` — every single route (`POST /generate` — auto mode,
`POST /angles` — guided step 1, `POST /write` — guided step 2, `GET /{social_id}`,
`POST /{social_id}/retry-angle`, `PATCH /{social_id}/hitl` — Gate 3-social approve/reject) uses
`_auth=Depends(_get_admin)` — **zero tenant-JWT path anywhere in this router**, confirmed by
reading every route decorator. This is, as the ADR says, the tightest admin-only surface in the
system — not one route in this module has ever had a tenant-facing equivalent built.

## 4. `trust_ramp.py` — read in full (not just the excerpt AA-440 quoted)

`services/acp_produce/trust_ramp.py` (full read, 169 lines).

**Transition conditions, precisely** — `suggest_ramp_transition(current_mode, engagement_ok,
weeks_active)`:
```python
def suggest_ramp_transition(current_mode: str, engagement_ok: bool, weeks_active: int) -> str:
    ix = RAMP.index(current_mode) if current_mode in RAMP else 0
    if engagement_ok and weeks_active >= 2 and ix < len(RAMP) - 1:
        return RAMP[ix + 1]
    return current_mode
```
Advance one rung when **both** `weeks_active >= 2` (a real elapsed-time gate) **and**
`engagement_ok` (an externally-computed boolean — this function never computes it itself,
just accepts it as a parameter). **This function is a pure suggestion — it never touches the
DB and never mutates state.**

**Real, important finding this task's full read caught: `suggest_ramp_transition()` has ZERO
callers anywhere in the codebase** (grepped every file) — it's exported (`__all__`) but never
invoked. **The only function that actually changes a packet's ramp state is
`confirm_ramp_transition()`**, and its only caller is `admin_produce.py`'s
`POST /packets/{id}/gate-c/approve` — a **manual, staff-picked** `mode` (the caller passes
whatever `mode` they want directly; nothing in this call path reads or requires a prior
`suggest_ramp_transition()` recommendation). **So "the ramp" is not currently an automatic,
metrics-driven progression at all — it's three fixed labels a staff member can set by hand, with
the suggestion logic that would justify an advancement sitting completely unused.**

**BOFU/pricing hard floor** (unconditional, independent of ramp level): a packet with any
BOFU-funnel-stage piece can never reach `veto_window_auto`, checked via a live join
(`pieces.slot_id → acp_v2_slots.payload->>'funnel_stage'`) before every transition attempt —
confirmed real, `trust_ramp.py:142-144`.

**Every transition attempt — blocked or not — is logged** to `acp_shared.audit_log`
(`action='publish_mode_transition'`) via `_log_transition()`, `trust_ramp.py:84-107`.

**Live query: `acp_shared.audit_log` has ZERO rows with `action='publish_mode_transition'`.**
**`confirm_ramp_transition()` has never been called, successfully or otherwise, in this
database.** All 4 real packets (§6) sit at `publish_mode='propose_only'` — the starting state,
never advanced. **No tenant has ever reached, or even attempted to reach,
`approve_to_publish` or `veto_window_auto`.**

## 5. Does ADR §0.2's "no gate" principle mean every tenant should start at `veto_window_auto`? Two views, not decided here

**View A — apply §0.2 literally, skip the ramp entirely.** ADR §0.2's stated principle ("AA
không gác cổng nội dung tenant ở bất kỳ bước nào") makes no exception for new tenants; if T1-T7
already ship without pre-publish approval, a content-production stage (T8-T10) gating on trust
level is inconsistent with that principle. The ramp's own metric-driven half
(`suggest_ramp_transition`) is unused dead code today (§4) — nothing is actually being learned
about a tenant's trustworthiness that would justify the delay in the first place.

**View B — the ramp is a legitimate, separate safety mechanism, not a content gate.**
`trust_ramp.py`'s own module docstring frames `veto_window_auto` as "a tenant publishing on
their own with AA retaining only a **veto window**" (AA-440's own framing, re-confirmed here) —
structurally closer to §0.2's own "A4 Cross-Tenant Oversight: hậu-kiểm, có khả năng can thiệp"
language than to a pre-publish approval gate. Read this way, `propose_only`/`approve_to_publish`
aren't "AA gating tenant content" so much as a **new-tenant onboarding ramp** — no different in
kind from e.g. a payment processor's new-merchant hold period — and the BOFU/pricing hard floor
(§4) is arguably closer to a genuine, permanent guardrail (booking/pricing claims) than a trust
question at all.

**Both views are presented as read from the code and the ADR's own words — this task does not
choose between them.** One fact relevant to whichever way it's decided: since the ramp has
*never once* been advanced in this database (§4), choosing View A (skip it) would not actually
be reversing any real, lived tenant experience — no tenant has ever benefited from or been
constrained by a `propose_only`→`approve_to_publish` transition; the mechanism is currently
inert either way.

## 6. Real DB state (task step 6)

Live query, 22/08 18:57 UTC:

```
acp_deliver.packets: 4 total, ALL tenant_id = aa_internal (00000000-...-000000000001),
                      ALL publish_mode = 'propose_only', ALL status = 'ready'
                      (weeks: 2026 Jul-w1, Aug-w3, Sep-w1, Oct-w2 — confirms AA-440's
                      earlier count, no B2B tenant packet exists)

acp_deliver.pieces: held=125, passed=10  (135 total — matches AA-438-04's earlier count)

acp_shared.audit_log WHERE action='publish_mode_transition': 0 rows — confirmed §4

acp_silver_s4.social_content (the table the legacy angle-gate endpoints write to): 0 rows,
  0 distinct modes/statuses — the entire angle-generation flow (§2-3) has NEVER been
  exercised in this environment, not even once, despite being fully coded and reachable.

acp_shared.quarter_plan_version: 9 rows, all approval_status='approved' (unchanged from
  AA-440's earlier count — re-confirmed fresh, not stale)
```

**No tenant, real or test, has ever gone through T8 in any form** — neither via the
legacy admin-only angle-gate (0 `social_content` rows) nor via any ramp-gated N7/N8 packet
progression beyond the starting state (0 ramp transitions logged).

---

## Summary

| Question | Answer |
|---|---|
| Does T7 (Quarter Plan/N6) trigger T8 (angle-gate)? | **No — the two pipelines are not connected in code at all**, confirmed by a full grep, not just "not wired up yet" |
| Does T8's "3 angles, dual-mode" logic exist as real code? | **Yes, complete and working** — `services/acp_s4_social/angles.py` + `handler.py`, ported from Ms. Thư's reference |
| `writing_formulars.xlsx`? | **Does not exist** — its role is filled by a hardcoded `GOALS` dict + real markdown formula references (`acp_s4_social/formula.py` + `references/*.md`) |
| Where is this exposed? | `api/routers/v1_s4_social.py` — **100% admin-only**, zero tenant-JWT path, matches ADR's "tightest admin gate" claim exactly |
| Real usage of the angle-gate flow? | **Zero** — `acp_silver_s4.social_content` has 0 rows, ever |
| Trust ramp transition conditions | `weeks_active >= 2 AND engagement_ok` — but this logic (`suggest_ramp_transition`) has **zero callers**, dead code |
| Who actually moves the ramp? | Only a staff member, via a manual admin-secret-gated endpoint choosing the `mode` directly — no automatic progression exists |
| Any tenant ever reached a higher ramp state? | **No — zero ramp transitions logged, ever**; all 4 real packets sit at the starting state |
| Should every tenant start at `veto_window_auto` per §0.2? | Two views presented (§5), not decided — but the ramp being currently inert either way is a relevant, confirmed fact |

## Open items — explicitly out of scope / unconfirmed

- Whether/how to port `acp_s4_social`'s angle-generation code into the N7/N8 pipeline, or build
  T8 fresh — not designed here, flagged as the concrete next decision alongside AA-440's
  Gate-B-removal and `fetch_atoms_by_trip()` fixes.
- Whether `engagement_ok` (the metric `suggest_ramp_transition` would need) is computed
  anywhere else in the codebase under a different name — not chased down, since the function
  itself has no callers regardless.
- The `acp_deliver.pieces` held=125/passed=10 ratio — noted as real context, not investigated
  further here (a content-quality question for N7, tangential to the T7→T8 handoff this task
  was scoped to).
