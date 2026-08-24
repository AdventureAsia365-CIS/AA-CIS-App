# AA-450-00 — STEP0 Investigate: T9 Content Writing (viết mới)

Investigate-only, không sửa code. Local checkout was 8 commits behind `origin/main` at session
start (missing AA-447/448/449 merges) — pulled to `8661849` before reading anything, so every
finding below reflects real merged main, not a stale worktree. `docs/claude_audit/
AA-447-01-sync-audit-matrix.md`, which this task's prompt names as a source, **does not exist on
main** — its commit (`20fd6a3`) lives only on the never-merged branch `feature/aa-447-sync-audit-
matrix`; read via `git show` and cited below as "AA-447-01 (unmerged branch)", not silently
treated as merged.

**Headline: SKILL_v2.md's own workflow numbering resolves the T9/T10 boundary question directly —
step 9 = write, step 10 = a separate internal quality/editor pass — and the one prior real
implementation of this exact skill (`acp_s4_social`, pre-ADR §0.5, not reusable but readable)
already built exactly that as two separate functions/LLM calls. The bigger, unexpected finding:
CTA — a required anchor field for writing, by both `SKILL_v2.md` and the old writer's own
`ContentBrief` — has no home anywhere in the T7→T8 chain as actually built. `Slot.cta_target`
exists (T7, computed by N6) but T8 never reads it; `angle_gate_request` has no `cta` column. T9
cannot write real content without deciding where CTA comes from — this is the one blocking open
question, not a minor detail.**

---

## 1. `SKILL_v2.md` — the writing + internal quality-pass steps

Full file read (365 lines): `docs/AI-gent-for automation works/stage4.2_ Social-media
contents_v2/SKILL_v2.md`.

### 1a. The 11-step Human-In-The-Loop Workflow (§"Human-In-The-Loop Workflow", lines 210-226)

```
1. Collect brand, audience, title/topic/content seed, and channel.
2. Show the 9-goal list.
3. Human selects a goal.
4. Ask for CTA.
5. Apply the internal writing method mapped to the selected goal.
6. Create 3 content angles shaped by brand, audience, channel, goal, and CTA.
7. Recommend the strongest angle.
8. Wait for human choice.
9. Write final content only after the human chooses an angle.
10. Run quality/editor pass internally.
11. Save final content if using `content_agent.py`.
```

This is the same 11-step source AA-439-07 already traced Nghiep's "9-step workflow" back to
(steps 1-8 = T8's scope, already built in AA-449). **Step 9 is T9's exact scope. Step 10 is a
separate step, textually and numerically, from step 9** — "write" and "run quality/editor pass"
are two different verbs on two different step numbers, not one combined instruction. Step 11
("save") has no dedicated persistence design anywhere yet (see §7 below — a real schema gap).

### 1b. Step 9 input — confirmed against §"Required Human Inputs" + §"Content Seed Handling"

The skill's own required inputs before "substantial content" is written (lines 19-30): brand/
business context, target audience, title/topic/content seed, channel, goal (from the 9-goal
list — 8 in this codebase's Bang 1, T8-confirmed), **CTA** ("ask for the specific CTA before
generating angles"), and — after the angle step — the selected angle. Optional: tone, must-
include/avoid, proof, preferred length.

Mapped against what T8 (AA-449) actually persists in `acp_shared.angle_gate_request`/
`angle_gate_option` (migration 113, read in full):

| SKILL_v2.md input | T8 real source | Confirmed reachable by T9? |
|---|---|---|
| Brand/audience | `shared.tenant_brand_rules.customer_segment/customer_mindset` via `services/acp_angle_gate/brand_audience.py::fetch_brand_audience()` | ✅ yes, same function directly reusable |
| Content seed / topic | `acp_contract.tour_atoms.text` via `atom_id` on the request | ✅ yes, same tenant-scoped fetch pattern (`service.py::_fetch_atom_for_tenant`) |
| Channel | `angle_gate_request.channel` (already stored) | ✅ yes |
| Goal | `angle_gate_request.goal` (already stored after step 2-6) | ✅ yes, `services/acp_angle_gate/goals.py::get_goal()` |
| Selected angle (4 fields) | `angle_gate_option` row where `chosen=true` | ✅ yes, `service.py::fetch_request()` already returns all options with `chosen` flagged |
| **CTA** | **nowhere** — `angle_gate_request` has no `cta` column, `generate_angles()` never takes or returns one | ❌ **missing — see §6, the open blocker** |
| Tone / must-include / must-avoid / proof | not collected anywhere in T7 or T8 | Optional per SKILL_v2.md — not blocking, but currently has no UI/field either |

### 1c. Step 9 output — draft, not gold, per the skill's own words

Nothing in SKILL_v2.md calls step 9's output "final" in the sense of ready-to-publish without
review — the very next step (10) is a mandatory quality/editor pass, and step 11 only "saves"
after that. **Reading order matters: 9 → 10 → 11 is drafted → self-edited → saved, not
drafted-and-done.** No format/length rule is stated in this section beyond "Follow channel
rules" (deferred to §"Channel Rules", see §1d) and using the internal writing method mapped from
the chosen goal (already encoded as `logic`/`marketing_term` per goal in `goals.py`, T8).

### 1d. Channel Rules (§"Channel Rules", lines 256-298) — SKILL_v2.md's own version is thinner than Bảng 2

SKILL_v2.md has its own "Channel Rules" prose section (LinkedIn/Facebook/Instagram/TikTok/
Email/Landing Page/Ads) — short "use for X, avoid Y" guidance, **no word-count numbers anywhere**.
This is NOT the same document as `Channel Output Structures.xlsx` ("Bảng 2"), which is what T8's
`channel_style.py` was actually built from (STEP0 for AA-449 already confirmed this, and AA-439-07
dumped the xlsx in full) — Bảng 2 has richer `structure`/`style`/`avoid` text per channel but
**also carries no explicit word-count numbers**. Neither of the two real source documents used so
far in this codebase specifies channel length — see §5 for where the numbers that DO exist live.

### 1e. Step 10 — the internal quality/editor pass (§"Quality Checklist", lines 329-342)

SKILL_v2.md doesn't give step 10 its own titled section, but the doc has exactly one checklist
matching "quality/editor pass" in shape and position (right before §"Avoid", after all the
writing-rule sections):

```
Before final output, check:
- Is the first line strong?
- Is the message specific?
- Is the audience clear?
- Is the CTA obvious?
- Does it sound human?
- Does it avoid generic AI-style writing?
- Does it match the requested tone and brand?
- Is proof or credibility handled honestly?
- Is the content suitable for the selected channel?
- Does the final content reflect the selected goal?
```

10 items, all yes/no, all check the ALREADY-WRITTEN content — nothing here describes a tenant-
facing approval action, a blocking state, or a second human in the loop. "Internally" (the
workflow step's own word) plus this checklist's phrasing together read as: **the LLM re-reads its
own output against these 10 criteria and fixes what it can, in one more pass — not a gate a human
or a second system approves/rejects.**

---

## 2. Old code — what's referenceable vs. not

Per ADR §0.5 (T8's precedent, confirmed again this session — no import from `services.acp_s4_
social` exists anywhere in `services/acp_angle_gate/` or `api/routers/v1_angle_gate.py`), T9 is
also **written fresh, not ported**. But `services/acp_s4_social/` contains the one prior real
implementation of this exact SKILL_v2.md workflow, including steps 9 and 10 specifically —
genuinely worth reading as reference, same class of value T7 got from `aa-marketing-v2`'s
`quarter.py`/`allocator.py`.

### 2a. `services/acp_s4_social/writer.py` — step 9's prior implementation

`write_content(brief, angle, formula_text, llm_client)` — one LLM call. Confirms the shape T9
needs: a system prompt built from brand voice rules + a user prompt assembling brief fields
(brand/audience/channel/goal/topic/tone/CTA/destination/tour/must-include/must-avoid) + the
selected angle's `name`/`why_it_works`. **Real, usable reference for structure — not reusable
as-is**: it's keyed to the OLD `ContentBrief` dataclass (`services/acp_s4_social/brief.py`,
requires `cta` as a validated non-empty anchor field — `validate_anchors()` fails without it,
confirming the CTA gap in §1b/§6 isn't just a SKILL_v2.md nicety, the one real prior writer
literally can't run without it) and its own `_CHANNEL_RULES` dict, not T8's `channel_style.py`.

**`_CHANNEL_RULES` (writer.py:12-59) — the one place real word-count/format numbers exist in this
codebase for this content type** (confirmed absent from both SKILL_v2.md's Channel Rules and
Bảng 2/`channel_style.py`, §1d):

| Channel | Length | Format notes |
|---|---|---|
| facebook | 150-300 words | 2-3 emoji max, short paragraphs, strong first line |
| linkedin | 200-400 words | no emoji, hook first line, one data point, soft CTA |
| tiktok | 80-150 words | hook in first sentence, 5-10 hashtags in a separate section |
| instagram | 100-200 words | skimmable, 5-15 hashtags in a separate section |
| email | subject ≤50 chars + 200-400 words body | personalised opener, one CTA |
| newsletter | 400-600 words | subheadings, "key takeaway" |
| landing_page | headline + subhead + 300-500 words + CTA block | H2 structure, proof element required |
| ads | headline 25-40 words + body 90-125 words | multiple variants (primary + 2) |

`channel_style.py` covers `landing_page`/`ads`/`email` under a slightly different key set (uses
`email` not `email`+`newsletter` split, and adds `blog`) — the 6 channels present in both line up
1:1 by name.

### 2b. `services/acp_s4_social/quality.py` — step 10's prior implementation, near-verbatim match

`quality_pass(content, brief, llm_client)` — **a second, separate LLM call** (own docstring: "AA-
145-C... Active editor pass — LLM revises content against 10-point checklist"). Its own system
prompt's checklist (lines 24-33) is **the same 10 items as SKILL_v2.md's Quality Checklist**,
same order, same wording almost verbatim — direct confirmation that a real prior build read this
exact section and turned it into exactly one more LLM call. Returns `{revised_content, warnings,
passed}` — the LLM revises inline and reports what it changed/flagged, no external approval step,
no blocking state beyond a boolean `passed` the caller can choose to act on.

**Together, 2a+2b are the strongest available evidence for the T9/T10 boundary** (§4): one real
prior implementation of this precise 11-step skill split step 9 and step 10 into two separate
functions/LLM calls, neither of which is a tenant-facing gate.

### 2c. `services/content_generation/graph.py` — confirmed infrastructure only, not content-writing logic to reuse

Already the "exclusive LLM layer" T7/T8 use (`LLMClient`, `LLMRequest`) — `generate_node()`
(line 283) is S1's tour-rewrite generator (`aa_name`/`aa_subtitle`/itinerary rewriting), a
different content type entirely (structured tour fields, not a single marketing piece). Its
value for T9 is the **pattern** (system+user prompt assembly, `client.generate()`, strip-fences →
`json.loads` → `json_repair` salvage on parse failure) — already the exact pattern
`services/acp_angle_gate/generate.py` copied for T8 — not any business logic. No content-writing
logic here is specific to social/marketing copy; nothing to port.

### 2d. `services/acp_produce/generation.py` (E2, admin N7 pipeline) — a different job shape, not T9's model

AA-439-08 already found this real and Sonnet-backed. Read again in full this session: `generate_
draft()` batches 2-3 **H2 sections** of a long-form blog piece, inserts headings from code,
tags every factual claim `[R:atom_id]`, uses `shared.llm_client.bedrock_satellite.invoke_claude`
directly (not `LLMClient`) locked to account `acc3`/model `sonnet` by an explicit AA-334 decision
("Palmyra must never appear... not a proposal, CHỐT"). **This is a multi-section long-form
writer for the ADMIN blog pipeline, structurally unlike T9's job** (T9 writes ONE short single-
channel piece per chosen angle, the same shape `acp_s4_social/writer.py` had, not a multi-H2
outline). Confirms §6's answer: T9 should follow T8's LLM-layer precedent
(`shared.llm_client.client.LLMClient`), not this module's path — same reasoning `generate.py`'s
own docstring already used to keep T8 off this path (quoted directly in §6).

### 2e. `services/acp_produce/gates.py` (F1-F9, admin N7 T10) — relevant only to the T9/T10-boundary open question, not directly reusable

9 gates (`gate_grounding`, `gate_atom_density`, `gate_banned_patterns`, `gate_structural_
variance`, `gate_brief_compliance`, `gate_route_to_sellable`, `gate_faq_dedup`, `gate_framework`
[LLM judge], `gate_brand_seo_audit`/`_social` [LLM judge]) — ported from `aa-marketing-v2`, real,
confirmed still actively holding pieces on real reasons (AA-439-08's live query: F8=24, F2=3,
F3=5, F9=2, F1=1 held pieces). This is a genuinely bigger, blocking, multi-gate system with its
own `held_reason`/`repair_count` state machine on `acp_deliver.pieces` — the admin/N7 tier's
answer to "T10." Whether the NEW tenant-tier T10 should look anything like this is exactly §4's
open question, not decided here.

---

## 3. T8's real schema and services — confirmed, and what T9 should read directly

`api/migrations/113_acp_shared_angle_gate.sql`, read in full:

```
acp_shared.angle_gate_request: request_id, tenant_id, atom_id, trip_id, channel, goal,
  status ('pending_goal'|'pending_choice'|'approved'), created_at, updated_at
acp_shared.angle_gate_option: option_id, request_id, idx (0-2), name, why_it_works,
  formula_fit, best_final_style, recommended (bool), chosen (bool)
```

No `cta`, no `body`/`content` column on either table (confirmed by reading every line of the
migration — see §6/§7).

**T9 should call `services/acp_angle_gate/service.py::fetch_request(tenant_id, request_id, pool)`
directly, not build a new read path.** It already returns exactly what T9 needs in one call:
`atom_id`, `trip_id`, `channel`, `goal`, `status`, and the full `angles` list with `chosen`
flagged — the same function T8's own `GET /v1/angle-gate/requests/{id}` endpoint already calls.
This is the same precedent T8 itself set for atom/goal/channel-style lookups (`_fetch_atom_for_
tenant`, `get_goal`, `get_channel_style`, `fetch_brand_audience` — all direct function reuse, no
new views) — **not** the Marketplace-view precedent (that view exists specifically to roll up
T4×T6 for a *human-facing* summary page, a different need than one service reading one specific
request it already has the id for). T9 only needs `status == "approved"` as a precondition
(refuse to write if a request hasn't reached that state yet) — no new API surface needed for this
read; only a new endpoint to *trigger the write* itself.

---

## 4. T9/T10 boundary — answered, with the caveat that it's a reading, not a locked decision

**Answer: step 9 (write) and step 10 (internal quality/editor pass) are two distinct steps in
SKILL_v2.md's own numbering (§1a), and the one real prior implementation of this skill
(`acp_s4_social`, §2a/2b) built them as two separate functions/LLM calls — not one combined self-
correction call inside a single LLM invocation.** This directly answers the "is step 10 folded
into T9, or a separate stage" half of the question: **folded is wrong** — even the reference
implementation treats them as sequential, separate calls.

The harder half — **is T10 a tenant-facing gate, or purely internal** — is not settled by any
single document, but the evidence lines up one way:

- SKILL_v2.md's own text for step 10 says "internally," and its Quality Checklist (§1e) is
  entirely about the CONTENT's own qualities, never about a human approving/rejecting anything.
- The one real implementation (`quality.py`, §2b) is exactly that: one more LLM call, no
  external approval step, `passed` is informational, not blocking.
- ADR §0.2, already quoted in `AA-439-00-SUMMARY` and re-confirmed in `AA-447-01` (unmerged
  branch, still the most complete ADR excerpt anywhere in this codebase): **"AA does not gate
  tenant content at any step in the T0-T11 chain. AA only controls via two layers: (1) rate
  limit/quota... (2) A4 Cross-Tenant Oversight — post-hoc monitoring... not a pre-publish gate."**
  This directly argues AGAINST T10 being a heavier, blocking gate like admin N7's F1-F9 stack
  (§2e) — that stack's `held`/`held_reason` state is precisely the kind of pre-publish gate §0.2
  says AA doesn't apply to tenants.
- Countervailing consideration, not dismissed: F1-F9 exists and is real, actively catching things
  (fabricated numeric claims, banned patterns, brand/SEO issues) that a tenant publishing under
  their own brand might still want caught even without AA "gating" them — a lighter, informational
  version of some of F1-F9's checks (not the blocking `held` state) is a plausible middle ground
  nothing in this session's reading rules out.

**Best-supported reading: T10 = a single internal LLM revise-pass, matching SKILL_v2.md +
`quality.py` almost exactly — non-blocking, auto-applies fixes it can, surfaces `warnings` for
anything it can't.** This is a reading from documents and one prior implementation, not a
confirmed product decision — **flagged as Open Question #1 below**, not silently assumed.

---

## 5. Route / naming proposal

Confirmed convention (`frontend/app/(tenant)/portal/`, `Sidebar.tsx` — read via CLAUDE.md's own
live route list, current as of AA-449): `/portal/t0-brand`, `/portal/t1-rewrite`, `/portal/
t4-pool`, `/portal/t6-atoms`, `/portal/t7-planning` (AA-448), `/portal/t8-angle-gate` (AA-449).

**Proposed: `/portal/t9-write`.** Matches the `t{N}-{short-verb-or-noun}` pattern exactly (t7 uses
a noun, t8 uses a compound noun, t1/t9 use a verb — both patterns already coexist, `t9-write` is
consistent with either). Sidebar placement: immediately after "Angle Gate" (T8) — same placement
instruction AA-449 itself was given relative to T7 ("nav+breadcrumb entries added right after T7
'Content Planning', per the build task's own placement instruction").

**Endpoint proposal** (mirroring `v1_angle_gate.py`'s own shape exactly):

```
POST /v1/content-write/requests/{angle_gate_request_id}/write   — write step 9, one LLM call
POST /v1/content-write/requests/{angle_gate_request_id}/revise  — step 10, one more LLM call
GET  /v1/content-write/requests/{angle_gate_request_id}         — read current draft + revision
```
(Router name/prefix is a suggestion, not a locked decision — `content-write` chosen to avoid
colliding with T8's `angle-gate` prefix while making clear these operate on the same
`request_id`.) Whether write+revise should be one combined endpoint (matching T8's own
`POST .../goal` which does steps 2-6 in one call) or two separate ones (matching write vs. revise
being two genuinely separate LLM calls per §4) is itself downstream of Open Question #1.

---

## 6. LLM layer — confirmed, with the CTA gap flagged as the real blocker

**Confirmed: T9 should use `shared.llm_client.client.LLMClient` (`model_tier="sonnet"`) — the
same layer T7/T8 already use, not `bedrock_satellite.invoke_claude` (acp_produce's AA-334-locked
long-form path) and not `judge_client.py`'s Nova Pro (cross-vendor judge only).** This isn't a
new judgment call this session made — `services/acp_angle_gate/generate.py`'s own module
docstring (lines 1-18) already worked through this exact 3-way distinction for T8's angle-
generation call, and the same reasoning transfers directly to T9: T9 writes ONE short single-
channel piece (§2a/2d comparison — same job shape as the old `acp_s4_social/writer.py`, NOT
`acp_produce`'s multi-H2-section blog draft), so it's a "content-STRATEGY"-class call in that
docstring's own terms, the same class T8's angle generation and S1's `generate_node()` both are.

**Token limit**: T8 used `max_tokens=2048` for 3 short angle objects. T9 writes one piece up to
~600 words (newsletter's ceiling, per the old `_CHANNEL_RULES`, §2a) ≈ ~800 output tokens — 2048
would still cover it with margin, but should be set per-channel rather than reused verbatim
(ads/tiktok need far less, landing_page/newsletter need more) — a real but small implementation
decision, not a blocker.

**System prompt**: yes, channel-specific — but the source for that prompt content is itself an
open question (Bảng 2 via `channel_style.py` has structure/style/avoid text with no numbers; the
old `_CHANNEL_RULES` has numbers with no Bảng-2-level structure detail; see Open Question #3).

**Cost**: no documented ceiling or concern anywhere in this codebase for a single-piece write
call at this size — T8's real angle-gen call (3 structured JSON objects, `max_tokens=2048`) cost
$0.0202 on the acc3 satellite path (AA-449 live-verify); a single ~600-word piece is the same
order of magnitude, not flagged as a cost risk by any document read this session.

**The real gap, not an LLM-layer question**: `SKILL_v2.md` requires CTA as an input to step 9
(§1b), and the one real prior writer (`acp_s4_social/brief.py::ContentBrief.validate_anchors()`)
treats a missing CTA as a hard validation failure — it will not write without one. Tracing where
CTA could come from in the current, real T7→T8 chain: **`services/acp_planning/models.py::Slot`
already has a `cta_target: Optional[str]` field (line 153), populated by N6's real allocator** —
but AA-449's own implementation notes already flagged, independently of this task, that `T8's own
API (create_request(atom_id, channel)) takes both as free-standing inputs, it does not require or
reference a real slot_id from T7's SlotGrid` — i.e. **the Slot→request wiring that would carry
`cta_target` through from T7 into T8 (and now T9) was never built, a known gap, not new to this
session.** Right now, an `angle_gate_request` has no `slot_id` FK and no `cta` column at all — T9
literally cannot answer "what is the CTA for this piece" from any table it can read. This is Open
Question #2 below, and it's a blocker, not a nice-to-have — the one real prior writer wouldn't run
without it, and neither should T9's.

---

## 7. Confirmed gap not asked for by name but load-bearing for T9's design: no output-persistence table exists

Neither `angle_gate_request` nor `angle_gate_option` (migration 113, read in full, §3) has a
column for written content. `acp_deliver.pieces` (migration 094, read in full) is schema-shaped
close to what T9/T10 would need (`body_tagged TEXT`, `status` enum, room for a gate/warning
ledger via a JSONB column, tenant-scoped with RLS) — **but it's keyed to `run_id REFERENCES
acp_shared.acp_runs`, the ADMIN N7 pipeline's run concept, not `angle_gate_request`.** Reusing
`pieces` as-is would mean fabricating a fake `acp_runs` row per tenant request, a real mismatch,
not a clean fit. **A new table (e.g. `acp_shared.content_piece`, keyed by `request_id` FK into
`angle_gate_request`, matching the `angle_gate_option`-is-a-child-of-`angle_gate_request`
precedent already set) is the more likely shape** — flagged as a build-time schema decision, not
made here.

---

## Open questions — for Nghiep/Ms. Thư, not decided in this task

1. **T10's real shape.** Best-supported reading (§4): a single internal, non-blocking LLM revise-
   pass matching SKILL_v2.md + the old `quality.py` almost exactly (writer's own self-edit,
   `warnings` surfaced but nothing held). Alternative not ruled out by any document: a lighter,
   informational version of some of admin N7's F1-F9 checks (§2e) — still non-blocking per ADR
   §0.2, but broader than a single self-revise call. Confirm before building T9's second call.
2. **Where does CTA come from?** (§6, the actual blocker.) Three concrete options, none chosen
   here: (a) retroactively wire `Slot.cta_target` through — add `slot_id` to `angle_gate_request`,
   require T8 requests to originate from a real T7 slot (bigger, cross-cutting fix touching T7/T8
   both); (b) collect CTA as a new tenant input at T9's own write step (deviates from SKILL_v2.md's
   step-4 placement, but self-contained to T9); (c) derive a default CTA per goal (e.g. from
   `goals.py`'s existing per-goal `description`/`logic` text) with no tenant input at all (fastest,
   but every goal's CTA becomes generic/identical, which the old `_writer_system()`'s "never
   generic" brand voice rule would itself flag).
3. **Which channel-length source governs T9?** Bảng 2 (`channel_style.py`, T8's real source) has
   no word-count numbers; the old `acp_s4_social/_CHANNEL_RULES` (§2a) does, but is a DIFFERENT,
   not-reused-per-ADR document. Confirm whether the old numbers are still the right target, or
   whether Ms. Thư has an updated set (same caveat AA-449 already flagged for the missing "blog"
   row in Bảng 2 — a real, not-yet-filled gap in the source document itself).
4. **Endpoint shape** (§5): one combined write+revise call (mirrors T8's own `.../goal` endpoint
   doing 5 workflow steps in one round trip) vs. two separate calls (mirrors `writer.py`+
   `quality.py` being two separate functions in the one real prior implementation). Downstream of
   Question #1.
5. **Output persistence** (§7): new `acp_shared.content_piece`-shaped table keyed by
   `angle_gate_request_id`, vs. some other design — not decided here, flagged so the build task
   doesn't discover this cold.

**Not re-litigated here, explicitly out of scope**: T11 (Publish) remains confirmed absent
org-wide (AA-439-08, re-confirmed by AA-447-01's unmerged-branch matrix) — whatever T9/T10
produce, there is still no real hand-off past "shown to the tenant as their final piece" until
T11 is designed, a separate, later task.
