# AA-439-07 — `acp_s4_social` vs. the original 9-step workflow: precise comparison

Reading/comparison task, no code changed, no design decision made. Branch
`feature/aa-439-tenant-tier-audit`. Every claim below is `path:line` (code) or a direct quote
(source docs) — nothing paraphrased where the original wording matters.

**Headline: Nghiep's 9-step workflow traces to a real, findable source — but not the one this
task pointed at first. It's `SKILL_v2.md`'s "Human-In-The-Loop Workflow" section (11 steps,
v2), not `aa-marketing-v2` and not the `writing formulars.xlsx` file alone. `services
/acp_s4_social/` matches most of that source closely and faithfully — but has one field the
source never asked for ("length_signal"), is missing the source's explicit CTA-collection step,
and doesn't literally have "formula fit" anywhere, in the source OR the code. The trust-ramp
question (Part A, step 4) has a firm, corrected answer: it IS chị Thư's original design (§4
below) — a live grep this task ran, that no prior task had actually run, found it directly.**

---

## PART A — Reading the source material first

### A1. Exact folder names, confirmed

`ls "docs/AI-gent-for automation works/"` — the formulas folder is **`fomulas`** (missing the
"r", confirmed — Nghiep's guess was right). Its contents:
```
fomulas/Channel Output Structures.xlsx
fomulas/writing formulars.xlsx
```
Dumped both with `openpyxl` (real spreadsheet content, not guessed) — full contents in A2/A3.

**A discovery beyond what the task named**: two more folders in the same parent directory turned
out to be the actual, direct, primary source for `acp_s4_social` — closer than `aa-marketing-v2`
itself:
```
stage4.2_ Social-media contents/       (v1: content_agent.py, SKILL.md, CONTEXT.md, references/)
stage4.2_ Social-media contents_v2/    (v2: content_agent.py, content_agent_v2.py,
                                         SKILL.md + SKILL_v2.md, CONTEXT.md + CONTEXT_v2.md,
                                         references/)
```
Both were read in full this task (SKILL.md/CONTEXT.md pairs, ~150-370 lines each) since they are
unambiguously the primary source (`services/acp_s4_social/angles.py`'s own docstring: *"Ports
Ms. Thư's `generate_angles()` logic from `content_agent.py`"* — this folder literally contains
that exact file). Flagging this explicitly since the task named `fomulas` and `aa-marketing-v2`
only — these two `stage4.2_*` folders turned out to matter more for this specific question.

### A2. `writing formulars.xlsx` — full contents (8 goals, not 9)

Real spreadsheet rows (`Name | description | logic | Marketing term`):

| Name | Marketing term |
|---|---|
| Promotion | AIDA |
| Lead Generation | AIDA or PAS |
| Conversion | SLAP |
| Introduction / Awareness | Hook-Insight-CTA or 5W1H |
| Trust-building | FAB |
| Engagement / Conversation | BAB |
| Event Announcement | 5W1H + AIDA |
| Product or Service Explanation | FAB |

**8 rows — no "Partner / supplier communication" goal in this file at all.** (§B notes where
the current code's 9th goal actually comes from.)

### A3. `Channel Output Structures.xlsx` — full contents

7 channels (`LinkedIn, Facebook, Instagram, TikTok, Email/Newsletter, Landing Page/Sales Page,
Ads`), each with `description | structure | style | avoid` columns — e.g. LinkedIn's `avoid`
column literally lists *"hidden gem," "bucket list," "once-in-a-lifetime," or "paradise
awaits"* as clichés to reject. **This is a separate dataset from the channel×goal→formula
lookup** (`_FORMULA_MAP` in the current code) — it describes per-channel *structure/style/avoid*
rules independent of goal. Confirmed: `services/acp_s4_social/` has **no equivalent of this
table** anywhere — grepped for "hidden gem"/"bucket list"/channel-specific avoid-lists in the
current module, no hits. The ported `formula.py` only carries the channel×goal→formula mapping,
not this per-channel structural/style/avoid guidance. (`aa-marketing-v2`'s `SKILL.md`-equivalent
*does* fold similar channel rules into its own "Channel Rules" section — see §A5 — so this isn't
entirely lost, just not ported into the current app's code.)

### A4. Where Nghiep's exact 9-step list actually comes from

Not `aa-marketing-v2`, not the xlsx files directly — **`SKILL_v2.md`'s "## Human-In-The-Loop
Workflow"** (`stage4.2_ Social-media contents_v2/SKILL_v2.md:210-226`), quoted in full:
```
Follow this workflow for substantial content:

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
**This is an 11-step list, not 9** — Nghiep's version is this same sequence with steps 3
("Human selects a goal") and 4 ("Ask for CTA") folded away/omitted, and step 11 ("Save") dropped
as an implementation detail rather than a strategy step. Every other step lines up almost
verbatim (§B has the precise line-by-line mapping). **Confirmed: Nghiep's list is a real,
findable, near-verbatim paraphrase of this exact source section — not a misremembering, and not
independently invented — just condensed, with the CTA-collection step genuinely dropped from
the summary** (worth knowing, since that step is real and the current code does enforce it — see
§B).

The **exact source of the required angle fields** is the same document, a few lines down —
`SKILL_v2.md:228-252`, "## Angle Selection Output," quoted in full:
```md
Here are 3 angles:

1. {Angle name}
Why it works: {short business reason}
Best final style: {short / detailed / persuasive / founder-led / visual / conversion-led}

2. {Angle name}
Why it works: {short business reason}
Best final style: {short / detailed / persuasive / founder-led / visual / conversion-led}
...
Recommended: {angle number}, because {short reason}.
Please choose 1, 2, or 3.
```
**The source format has exactly 3 fields per angle: Name, Why it works, Best final style — not
4, and "formula fit" does not appear anywhere in this document, or in v1's `SKILL.md`, or
anywhere else grepped in either `stage4.2_*` folder.** §C works through what this means for
Nghiep's requested 4-field format precisely.

### A5. Channel rules — confirmed present, matching aa-marketing-v2's shape

`SKILL_v2.md:256+` ("## Channel Rules") has the same per-channel best-formula guidance
`aa-marketing-v2`'s `README.md`/`CONTEXT.md` describe in prose (§ already covered AA-439-04) —
consistent across all three sources, not contradictory.

### A6. Trust ramp / veto window — corrected finding, confirmed by a grep no prior task actually ran

**AA-439-06 left this as an open question** ("is trust_ramp chị Thư's idea or AA-365's own
invention?"). **This task ran the actual grep AA-439-06 didn't** (`trust|ramp|veto|graduate
|probation` across `aa-marketing-v2` specifically) and found a firm, direct answer:

`aa-marketing-v2/CONTEXT.md:255`:
> **G3 `publish_gates(mode)`** · trust ramp: propose-only (wk 1–2) → approve-to-publish →
> veto-window auto-publish; BOFU/pricing may stay approval-forever. Mode transitions suggested
> by engagement metrics, agency-confirmed.

`aa-marketing-v2/aamc/delivery.py:157-174` (the real reference implementation, full function):
```python
RAMP = ["propose_only", "approve_to_publish", "veto_window_auto"]

def publish_gates(ws: Workspace, engagement_ok: bool, weeks_active: int) -> dict[str, str]:
    """Trust ramp: transitions SUGGESTED by metrics, agency-confirmed —
    never silently switched. BOFU/pricing may stay approval-forever."""
    ...
    ix = RAMP.index(current) if current in RAMP else 0
    suggestion = current
    if engagement_ok and weeks_active >= 2 and ix < len(RAMP) - 1:
        suggestion = RAMP[ix + 1]
    return {"current": current, "suggested": suggestion, ...}
```
**This is functionally identical, line for line, to `services/acp_produce/trust_ramp.py
::suggest_ramp_transition()`** (already quoted in full in AA-439-06) — same `RAMP` list, same
`weeks_active >= 2 AND engagement_ok` condition, same "suggest, never silently switch" framing,
even the same BOFU/pricing-stays-approval-forever carve-out and the 48-hour veto window
(`config.VETO_WINDOW_HOURS = 48`, `aamc/config.py:75`) and the "≥3 same-pattern vetoes →
generalization ask" (`VETO_PATTERN_THRESHOLD = 3`, `aamc/config.py:76`).

**Corrected conclusion: the trust ramp IS chị Thư's original design, faithfully and precisely
ported (AA-365) — not a separate, later invention.** This resolves AA-439-06's open question
directly. What AA-439-06 already found still stands and isn't contradicted by this: the
*automatic suggestion half* (`suggest_ramp_transition`) has zero real callers in the current app,
and zero ramp transitions have ever been logged — that's a fact about how the port is *used*
today, not about whether the *design* traces to chị Thư. It does.

Separately, confirmed by the same grep: **no mention of "trust ramp"/"veto"/progression-over-
time exists anywhere in either `stage4.2_*` folder** (the angle-generation source) — the trust
ramp and the angle-generation workflow are two unrelated pieces of chị Thư's overall design,
ported into two different current-app modules (`trust_ramp.py` for delivery/publish-mode;
`acp_s4_social/` for angle-generation) that, per AA-439-06, have never been connected to each
other in the current codebase either.

---

## PART B — Line-by-line comparison: `acp_s4_social` vs. the 11-step source workflow

| # | Source step (`SKILL_v2.md:214-224`) | Real code (`path:line`) | Match? |
|---|---|---|---|
| 1 | Collect brand, audience, title/topic/content seed, and channel | `ContentBrief` (`brief.py:30-43`): `brand, audience, channel, goal, topic, tone, cta` are all dataclass fields; `validate_anchors()` (`:48-65`) requires **all of them** non-empty, not just seed+channel | **Partial** — see note below |
| 2 | Show the 9-goal list | `formula.py:72-118`'s `GOALS` dict, 9 entries, keys `"1"`-`"9"` | **Match — and confirms the code is a v2 port, not v1** (§B1) |
| 3 | Human selects a goal | No dedicated "list goals" endpoint found in `v1_s4_social.py` — the caller must already know/pass a `goal`/`goal_key` string in the request body; there's no server-side "here are your 9 options, pick one" round trip | **Not implemented as its own step** — folded into "the caller already knows the goal" |
| 4 | Ask for CTA | `ContentBrief.cta` is a **required** anchor (`brief.py:37,63-64`) — enforced, but there's no distinct "ask for CTA" round trip either; same as goal, the caller must supply it upfront | **Enforced as a required field, but not a distinct interactive step** — and completely absent from Nghiep's own 9-step summary too (§A4) |
| 5 | Apply the internal writing method mapped to the selected goal | `_load_formula()` (`handler.py:35-43`) → `get_goal_primary_formula(goal_key)` / `load_goal_references(goal_key)` (`formula.py:141-154`) | **Match** |
| 6 | Create 3 content angles shaped by brand, audience, channel, goal, and CTA | `generate_angles()` (`angles.py:52-104`), prompt built by `_angles_prompt()` (`:31-49`) — explicitly includes brand, audience, channel, goal, topic, tone, CTA, must_include, must_avoid, destination, tour_name | **Match, and the code's prompt is richer than the source's minimal 5-field description** |
| 7 | Recommend the strongest angle | `mode="auto"` returns `angles[:1]` (`angles.py:101-102`); guided mode's `all_angles[0]` is treated as "best" (`handler.py:78-81`) — in both cases, the LLM's own first-ranked angle is trusted as "the recommendation," matching the source's "recommend" framing | **Match** |
| 8 | Wait for human choice | `run_guided_angles()` (`handler.py:160-167`) returns all 3 to the caller and stops — `run_guided_write()` is a **separate** function/call, only invoked once a `selected_angle` is supplied (`handler.py:170-198`, `v1_s4_social.py:213-214` 422s if missing) | **Match** — the "wait" is structural (two separate API calls), not a sleep/poll |
| 9 | Write final content only after the human chooses an angle | `write_content(brief, selected_angle, formula_text, llm_client)` (`handler.py:198`, guided path) — confirmed never called before angle selection in the guided path | **Match** |
| 10 | Run quality/editor pass internally | `quality_pass()` (`handler.py:93,199`) + a second `evaluate_quality()` scoring pass (`handler.py:97-109,203-215`) — **two** internal quality passes, not one | **Match, and exceeds the source (2 passes vs. 1 described)** |
| 11 | Save final content if using `content_agent.py` | `save_to_db()` (`handler.py:123-133,217-225`) — writes to `acp_silver_s4.social_content` (confirmed live-empty, AA-439-06) | **Match** |

### B1. Step 2's 9-goal list — confirms the port is from v2, not v1

`writing formulars.xlsx` (§A2) and v1's `content_agent.py` have only **8** goals (no "Partner /
supplier communication"). `content_agent_v2.py` (`stage4.2_..._v2/content_agent_v2.py:37-85`)
has all **9**, in the same order, with the same names, including `"Partner / supplier
communication"` as goal 9 — **an exact match to `services/acp_s4_social/formula.py`'s `GOALS`
dict** (already quoted in AA-439-06, same 9 names, same order, same numeric keys). **The
current port is sourced from v2, confirmed precisely by this goal-count/goal-9 match** — worth
knowing since the current code's own docstrings never specify v1 vs. v2, just "content_agent.py."

### B2. Step 1 / Nghiep's "fixed brand audience automatically" — real discrepancy, precisely characterized

`ContentBrief.validate_anchors()` (`brief.py:48-65`) treats `brand` and `audience` as **required,
validated inputs** — exactly like `channel`, `goal`, `topic`, `tone`, `cta`. **There is no
hardcoded/default brand or audience value anywhere in `brief.py`, `angles.py`, `handler.py`, or
`formula.py`** — grepped for a literal "Adventure Asia" default or similar, none found in this
module. **Confirmed: nothing "automatically applies" a fixed brand/audience in the module
itself** — whatever calls this module must supply both values every time, the same as every
other field.

**But this task also confirmed something Nghiep's framing may be implicitly right about in
practice**: no live caller of `/generate`/`/angles`/`/write` exists anywhere in the current
codebase at all (re-confirmed, see §B3) — so there is no real, observed calling convention to
check whether some upstream caller *does* pass a fixed "Adventure Asia" brand/audience by
default. **This can't be settled from code alone**: the module's own validation logic requires
brand+audience as real inputs, but since nothing calls it, there's no evidence either way about
whether a future caller would (or should) hardcode them. Reported as found, not resolved.

### B3. Real usage confirmed: literally nothing calls these endpoints — not even the legacy FE page

AA-439-06 already found `acp_silver_s4.social_content` has 0 rows, ever. **This task went one
level deeper and checked the code, not just the data**: grepped the entire `frontend/` tree for
any caller of `/generate`, `/angles`, or `/write` under this router's prefix
(`/v1/acp/s4/social`, `v1_s4_social.py:33`) — **zero matches, anywhere.**

The one FE page that does exist and does reference "s4-social" —
`frontend/app/admin/pipeline/s4-social/page.tsx` (613 lines, checked) — **does not call any of
these three endpoints either.** It calls `GET /api/admin/acp/runs`, `GET /api/admin/acp/s4/social
?run_id=...`, and `POST /api/admin/acp/s4/social/batch-review` — a **downstream review/approval
UI** (Gate 3-social HITL, matches the `hitl_gate_3_social_status` column seen in AA-439-06) for
content that would already have to exist, not the angle-generation/selection flow itself. **This
is exactly the "recommend → người chọn" mechanism the task's step 3 asked about — and it is
confirmed to be a *different* mechanism than the angle-selection dual-mode**: this page reviews
already-written posts after the fact (post-production HITL gate); it has no angle-selection UI
of its own. Grepped `api/main.py` (the only place that references `v1_s4_social` outside the
router file itself) — it only **mounts** the router (registers it with the FastAPI app), it
never calls into it.

**Net: the angle-generation/selection API is not just unused — no caller for it exists anywhere
in this codebase, frontend or backend.** Porting this into N7/N8 would mean building the entire
calling chain (a real UI trigger, or a real pipeline-stage caller) from scratch either way — the
part that's genuinely reusable as-is is the angle-generation/formula business logic itself
(`angles.py`, `formula.py`, the sequencing in `handler.py`), not any existing integration.

### B4. Angle output fields — precise 3-way comparison

| Field | Source (`SKILL_v2.md:228-252`) | Current code (`angles.py:19-28`, `_ANGLE_SYSTEM`) | Nghiep's ask |
|---|---|---|---|
| Name | ✅ `{Angle name}` | ✅ `"name"` | ✅ |
| Why it works | ✅ `Why it works: {short business reason}` | ✅ `"why_it_works"` | ✅ |
| Best final style | ✅ `Best final style: {short / detailed / persuasive / founder-led / visual / conversion-led}` — a fixed 6-option enum | 🟡 `"style_signal"` — same *intent*, different name and different example vocabulary (`"conversational"`, `"expert authority"`, `"narrative story"` shown in the current prompt, not the source's 6-item enum) | ✅ (named exactly as source) |
| formula fit | **Not found anywhere** — not in `SKILL_v2.md`, not in v1's `SKILL.md`, not grepped anywhere in either `stage4.2_*` folder | **Not present** — no field named or resembling "formula fit" in `_ANGLE_SYSTEM` or the `Atom`-equivalent angle dict | Requested, but **new** — not recoverable from any source read this task |
| (extra, code-only) | — | `"length_signal"` (e.g. "150 words, 3 paragraphs") — **not in the source's angle format at all** | Not requested |

**Conclusion on fields: 2 of Nghiep's 4 requested fields match the source and the code exactly
(Name, Why it works). "Best final style" is real in the source but the current code renamed/
drifted it to `style_signal` with different example values. "Formula fit" exists in neither the
source nor the code — it would be a genuinely new field, not a recovery of something dropped.**
The code also carries one field (`length_signal`) that isn't in the source's angle-output
contract at all — not wrong, just an addition made during the port that this task's reading
didn't find a documented source for either.

---

## PART C — Verdict: matches mostly, with precise, itemized gaps — not a clean "yes" or "no"

Per the task's own framing, this is **not** a full match and **not** a non-match — it's a
**close, largely faithful port with specific, nameable gaps**:

**What matches cleanly (steps 5, 6, 7, 8, 9, 10, 11 — 7 of 11 source steps):** the
formula-selection, 3-angle generation, dual-mode recommend/select/write sequencing, and the
double quality pass are all real, working, and structurally faithful to the source. The 9-goal
list itself is an exact match (§B1) — to v2 specifically.

**What's missing or folded away (steps 3, 4):** there's no dedicated "show the human the goal
list, capture their pick" round trip, and no dedicated "ask for CTA" round trip — both are
implicit, required-field validations instead of interactive steps. Not wrong, but not literally
present as separate steps either.

**What's a real content discrepancy, not just structural (step 1 / Nghiep's step 3):**
brand+audience are validated, caller-supplied inputs in the code — nothing in the module
"automatically applies" a fixed value. Whether that's actually true in practice can't be checked
because nothing calls this module at all (§B3).

**What's an outright gap versus Nghiep's specific ask (angle fields):** "formula fit" is not
recoverable from any source document read this task, in either folder — it would need to be a
new decision, not a restoration. "Best final style" is real in the source but has drifted in the
current code's naming.

**What's structurally the biggest fact for the reuse-vs-rewrite decision, beyond field-matching**:
this entire module — endpoints, business logic, everything — has **zero real callers anywhere in
the current codebase**, frontend or backend (§B3). Whatever gets decided, the calling chain into
N7/N8 (or wherever T8 ends up) has to be built new either way; only the angle-generation/formula
logic itself is a genuine "port, don't rewrite" candidate.

This task does not decide reuse-vs-rewrite — per its own instruction — this table is the
evidence for that decision, not the decision itself.

---

## Open items — explicitly out of scope

- Whether `content_agent_v2.py`'s CLI flow (not re-read function-by-function, only grepped for
  the workflow/goal-count facts needed here) has any further discrepancies against
  `services/acp_s4_social/` beyond what's tabulated in §B.
- `stage4.2_..._v2/out_put/*.md` sample outputs — not read; they're example generated posts, not
  spec material relevant to this comparison.
- Designing the actual formula-fit field, or deciding whether to keep/rename `length_signal` —
  explicitly not this task's job.
