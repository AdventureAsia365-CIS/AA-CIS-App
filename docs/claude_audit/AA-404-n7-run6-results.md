# AA-404 — Digest verify + N7 run #6 results

**Scope: verify + trigger + real-data analysis only. No code changed this session.** Task:
`docs/claude_tasks/AA-404-06-digest-verify-retrigger-n7.md`. Read first (no re-investigation):
`docs/claude_audit/AA-404-N0-N8-defense-layer-audit.md`, `docs/implementation-notes/AA-404-F9-deep-dive.md`,
`docs/implementation-notes/AA-404-writer-side-brand-wire.md` (PR #161), PR #162/#163 bodies.

## Step 1 — Digest verify: MATCH, no force-deploy needed

- `main` has all 4 PRs merged (`git log`/`gh pr list`): #160 (`ea81a67`), #161 (`b412171`),
  #162 (`0cb593a`), #163 (`e271ef5`, the last merge, 2026-08-16T02:03:17Z).
- Last "Deploy Dev" GH Actions run (triggered by `e271ef5`'s push to `main`): **success**
  (`databaseId` 31920980765/31920980696, 02:03:19Z).
- ECR `:latest` digest: `sha256:0721d7693dc0ec506bb38852a52890c2c9cf40c661af97e883b3218ce27562d8`
  (tag `dev-e271ef53c0ce8a7fe02c8f1ed4a014b311fb26ad` — matches PR #163's merge commit sha
  directly, not inferred).
- ECS running task (`aa-cis-dev-api:96`, task `c919e4603df14f32a94f2d8d70be35e3` at verify time)
  container digest: **same** `sha256:0721d769...`. Task started 2026-08-16T02:06:55Z, ~90s after
  the image was pushed (02:05:33Z) — consistent with a clean auto-rollout, not a stale image.
- **Digests matched on first check.** No `--force-new-deployment` was needed — ADR-2026-037's
  "verify persist on real data" spirit satisfied by confirming the digest match directly rather
  than trusting "PR merged" as sufficient, per the task's own explicit instruction.

## Step 2 — N7 run #6: triggered, completed with a real infra incident along the way

### Run identity and a deviation from the task's literal instruction, stated up front

The task asked to reuse "cùng slot/tenant đã dùng ở 5 lần chạy trước." Querying
`acp_shared.acp_v2_runs` directly (not inferring from docs) found **the exact same `(tenant_id,
year, month, week)` tuples used by all prior runs are exhausted** — `acp_v2_runs` has a
`UNIQUE(tenant_id, year, month, week)` constraint (migration 103) and `_deterministic_slot_id()`
hashes on all 4 fields, so re-submitting an already-used tuple either resumes/no-ops an existing
row rather than producing fresh data. Only Q3 2026 (Jul/Aug/Sep) has an **approved** Gate-B
quarter plan for `aa_internal` (`acp_shared.quarter_plan`, 1 row, `quarter=3`) — Gate B explicitly
requires human (Ms. Thu) approval, never auto, so a new quarter was not an option this session.
Within Q3, `week=1` had already run for all 3 months (Jul/Aug/Sep). Picked the next unused
combination in the same approved quarter, same tenant: **year=2026, month=9 (Sept), week=2**
— confirmed via `_deterministic_slot_id()` to be genuinely new, not a replay (`due_slot_count: 3`,
matching the same 3-slot shape the original `week=2` run had).

Tenant is unchanged (`aa_internal`, `00000000-0000-0000-0000-000000000001`) in all 7 runs to date.

The 6-run baseline this report's "lần 5" refers to is **the 2 runs already in the DB from before
this session, both under the exact same code state** (post-PR #158 — F9 judge-side brand rubric
wire — pre-PR #161/#162/#163): `56f6f1fe` (Sep, week=1, 12 pieces) and `b4cc97ee` (Jul, week=1,
12 pieces). This matches the F9 deep-dive doc's own count ("69 piece / 6 lần chạy" = 12+9+12+12+12+12)
and the task's "so sánh với lần thứ 5" framing more precisely than picking just one of the two —
both are shown separately in the table below, not averaged.

| # | run_id | (y,m,w) | pieces | code state |
|---|---|---|---:|---|
| 1 | `de8337ba` | 2026-08, w1 | 12 | pre-AA-404 |
| 2 | `e64befb4` | 2026-08, w2 | 9 | pre-AA-404 |
| 3 | `170a0825` | 2026-08, w3 | 12 | pre-AA-404 |
| 4 | `4d20b52b` | 2026-08, w4 | 12 | post-#153 (F3/F8 writer prompt) |
| 5a | `56f6f1fe` | 2026-09, w1 | 12 | post-#158 (F9 judge-side brand wire) |
| 5b | `b4cc97ee` | 2026-07, w1 | 12 | post-#158 (same as 5a) |
| **6** | **`d0722ae3`** | **2026-09, w2** | **9** | **post-#161/#162/#163 (writer-side wire + F5 + batch2)** |

### Real infra incident during run #6 — orphaned slot, twice, recovered both times

Not an AA-404 code issue, but real and worth a Linear ticket. **The ECS task running the N7
`BackgroundTask` failed its ALB health check twice while run #6 was in flight, and ECS killed +
replaced the task both times, each time abandoning whichever slot was mid-repair:**

- 02:19:53Z — task `c919e4603df14f32a94f2d8d70be35e3` marked unhealthy (`Request timed out`),
  replaced. `slot_ad075f6bdb60f7b76f9a` (the 3rd/last slot) was orphaned with 0 pieces persisted
  — its repair loop was mid-round when the container was SIGKILL'd (exit code 137).
- Recovered by re-POSTing the identical trigger body — `create_weekly_produce_run()`'s
  `ON CONFLICT DO NOTHING` + reselect makes this a safe resume: same `run_id` returned,
  `due_slot_count: 1` (only the still-`due` slot, the 2 already-`produced` slots were untouched).
- 02:44:12Z — the **replacement** task (`cd032f9ed3054b308c355c7c783b038d`) **also** failed the
  same ALB health check mid-slot and was replaced again, this time after 2 of the slot's 3 pieces
  had already been persisted. The 3rd task (`29420da6...`) picked up cleanly; the run reached
  `status=completed` at 02:45:02Z without a 3rd manual retrigger.
- `curl http://localhost:8000/health` **inside** the container returned `200 OK` throughout —
  the app process itself was never down; only the ALB-facing health check was timing out.
- Plausible mechanism (not proven this session, flagging for someone to look at): `generate()`
  is documented as **synchronous** (`CLAUDE.md`'s own note — "asyncio deadlock fix, Python
  3.12"), and `E5` repair calls the same synchronous Bedrock client. If a repair round's blocking
  call ties up the single event loop for long enough back-to-back rounds, incoming ALB health
  probes queue behind it and time out — which would explain why this only surfaces during a real
  N7 run's repair-heavy stretches and never during idle serving.
- **Net effect on data integrity: none** — every piece that got orphaned was regenerated from
  scratch on resume (not resumed mid-repair), so run #6's final 9/9 pieces are real, complete
  gate-ledger results, not partial state. But this cost ~15 extra minutes of wall clock and 2
  manual interventions this session; an unattended weekly cron run would have needed the same
  recovery and nobody watching.

## Step 3 — Gate ledger comparison, all 7 runs (real `gate_ledger` pulled from `acp_deliver.pieces`, not `held_reason` summaries alone)

Numbers are **final-state fail counts** — count of pieces whose FINAL (post-repair-budget)
`gate_ledger` entry for that gate is `passed: false`, regardless of which gate a piece's DB
`held_reason` names as "the" blocker. `first-fail` = the earliest-order gate still failing in
that final ledger (this reproduces `held_reason`'s gate exactly in all 7 runs — cross-checked,
not assumed).

| Run | n | passed | pass% | F1 first-fail | F3 final-fail | F4 final-fail | **F5 final-fail (NEW)** | F8 final-fail | F9-blog final-fail | F9-social final-fail |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 `de8337ba` | 12 | 0 | 0% | 2 | 4 | 2 | — | 4 | 4 | 8 |
| 2 `e64befb4` | 9 | 0 | 0% | 1 | 3 | 2 | — | 2 | 3 | 6 |
| 3 `170a0825` | 12 | 0 | 0% | 0 | 3 | 2 | — | 5 | 4 | 8 |
| 4 `4d20b52b` | 12 | 0 | 0% | 0 | 1 | 4 | — | 4 | 4 | 8 |
| 5a `56f6f1fe` | 12 | 2 | 17% | 2 | 0 | 0 | — | 0 | 4 | 6 |
| 5b `b4cc97ee` | 12 | 2 | 17% | 2 | 0 | 0 | — | 3 | 3 | 7 |
| **6 `d0722ae3`** | **9** | **0** | **0%** | **4** | **0** | **0** | **2** | **1** | **3** | **6** |

(F3/F4 denominators are blog-only pieces per run — 4 for the 12-piece runs, 3 for the 9-piece
runs; F9-blog same; F9-social is facebook+tiktok — 8 for 12-piece runs, 6 for 9-piece runs; F8
applies to all channels.)

## Step 4 — Per-gate verdict

### F1_grounding — **xấu đi (regressed), and the mechanism is identifiable, not a mystery**

4/9 (44%) first-fail on F1 in run 6 vs 2/12 (17%) in both run-5 baselines — the sharpest swing in
the table, and the one directly answering the task's "gần pass hơn hay vẫn cùng loại lỗi" question
for F9 turns out to matter more for F1. Real `repair_log` trace for
`d0722ae3:slot_140a1837492c88d70624:blog` (`initial_failing_gate_count=1`, i.e. **F1 was NOT
failing on the first draft**):

```
round 1: gate_targeted=F9_brand_seo_audit   -> failed
round 2: gate_targeted=F9_brand_seo_audit   -> failed
round 3: gate_targeted=F5_atom_density      -> failed
loop summary: never_repaired_gates=['F1_grounding','F5_atom_density','F9_brand_seo_audit'],
              outcome=held
held_reason: F1_grounding: sentence states ['400'] not present in its cited id(s)...
```

F1 was never even the round's *target* — it appeared for the first time in the FINAL gate check,
after 2 rounds of F9 repair and 1 round of F5 repair rewrote prose, and the piece's repair budget
(3, sized off the *original* 1-gate failure count) ran out before F1 could get a dedicated round.
The second F1-final piece (`slot_ad075f6bdb60f7b76f9a:blog`) shows the identical shape: F1 passed
on round 2, then a round-3 F5 repair reintroduced a *different* uncited number, and rounds 4-5
(both F1-targeted) failed to fully resolve it before budget ran out.

**This is not a new problem — it's the exact gap AA-404's own STEP-0-mở-rộng doc already named and
explicitly deferred, now hit by real data for the first time:**

> "F1_grounding's exposure ('new prose written blind, no atom list to check new content against')
> is NOT given its own invariant field here... deferred rather than guessed at ahead of real data...
> If real data ever shows an F1 regression, `atom_text_by_id` is already in scope at the
> `pipeline.py` closure call site and would extend this the same way `required_h2s` did."
> — `docs/implementation-notes/AA-404.md`, "STEP 0 (mở rộng)" §Tradeoffs

F5 is a new gate (PR #162, merged after that doc was written) and was never folded into
`PieceInvariants` either — so today, **neither F1 nor F5 has a repair-time safety net**, and F5's
own remediation ("add a specific, verifiable detail") is a plausible, observed-in-this-run trigger
for exactly the kind of blind, ungrounded new-prose-writing F1 is supposed to catch. Sample size
is small (2 real occurrences) but the mechanism is traceable end-to-end in real logs, not
speculative.

### F5_atom_density (NEW gate) — **hoạt động đúng thiết kế, không quá nghiêm/quá lỏng — nhưng repair path chưa được bảo vệ**

Fired as a real final-state failure on 2/9 pieces (22%), never as the sole/first blocker (always
co-occurring with F1 or F9 by the time the piece held). Both real violations are concrete,
addressable, and match the gate's stated purpose exactly — not a false positive, not a design
threshold problem:

```
"words 600-900: zero atom/fact citations in this stretch — that's where AI-voice lives
(CONTEXT.md §1.6.1); add a specific, verifiable detail or cut it. First 80 chars: 'Yeongdo
Island; the lit shoreline runs from Haeundae in the east to the containe'"

"words 0-300: zero atom/fact citations in this stretch...First 80 chars: '## Bike In South
Korea: what it's actually like Most travellers have no idea Sou'"
```

Both are genuinely under-cited stretches (an opening paragraph, a scene-setting transition) — this
is precisely the `BODY_EXPERIENCE_DETAILS_TOO_GENERIC` shape the F9 deep-dive identified as blog's
#1 individual failure code (22/109 occurrences) and predicted a cheap deterministic gate would
catch before ever reaching a Bedrock judge call. **Verdict: F5's detection logic is calibrated
correctly on this first real sample — the strictness question the task asked about isn't the
live issue.** The live issue is what happens AFTER F5 fires: its repair round writes new prose to
close the citation gap, and (per the F1 section above) that prose isn't checked against real atom
text before being accepted — so F5's own fix path is the same "write blind" gap that's now shown
up as an F1 regression twice in a 9-piece sample.

### F9 (blog + social) — **không đổi (flat), same non-convergent shape as every prior run**

F9-blog final-fail: 3/9 (33%) in run 6 vs 4/12 (33%) / 3/12 (25%) in the two run-5 baselines —
statistically flat given N=9. F9-social: 6/9 (67%) vs 6/12 (50%) / 7/12 (58%) — also flat, arguably
nominally worse but within noise at this sample size. Real flagged-phrase quotes from run 6 show
the identical "moving target" pattern the F9 deep-dive already documented — different specific
phrase flagged each round, several read as competently-written, concrete prose, not templated
filler:

```
round 1: "GENERIC_AI_WORDING -- The phrase 'see almost no foreign foot traffic' is a generic
statement that could apply to many trails around the world."
round 2: "GENERIC_AI_WORDING -- The phrase 'The Sanmani Trail runs through mountain ranges,
coastal ridgelines, and river valleys' is flagged...lacks specific, verifiable details."
round 3: "GENERIC_AI_WORDING -- The phrase 'the trail's backbone' and 'threading off it' are
metaphorical and add a layer of abstraction that is not strictly necessary."
```

**PR #161's writer-side brand rubric wire (E2-E5 now see the real tenant rubric, not just the F9
judge) did not measurably move F9's real-data fail rate in this single 9-piece sample.** That's
not proof the fix is wrong — the F9 deep-dive's own root-cause finding (judge subjectivity /
"moving target" vocabulary, `GENERIC_AI_WORDING` re-litigated fresh each round with no memory of
prior complaints) was always flagged as the dominant, harder-to-fix layer underneath the
judge/writer-target-mismatch layer PR #161 closed. This run is consistent with that: closing the
target-mismatch gap was necessary but was never claimed to be sufficient on its own.

### F8_framework — **cải thiện nhẹ, but N too small to be confident**

1/9 (11%) final-fail in run 6, vs 0/12 (0%) in run 5a and 3/12 (25%) in run 5b. Sitting between
the two baselines — not a regression, plausibly a small real improvement from PR #163's hub/PAS +
TikTok guidance, but one real occurrence either way flips this reading; not enough signal to
credit the fix confidently from this run alone.

### F3_structural_variance / F4_brief_compliance — **giữ nguyên cải thiện đã có, không đổi**

Both stayed at 0 final-fails in run 6, same as both run-5 baselines (down from real problems in
runs 1-4, pre-PR#153/#154). Consistent, not new news from this run — the piece-invariants fix
(PR #154) continues to hold for these two gates specifically.

## Step 5 — Overall read for the 17/08 demo

**Not "cải thiện đáng kể."** Raw pass rate went from 2/12 (17%) in the most recent pre-this-session
baseline to 0/9 (0%) in run 6 — worse in absolute terms, though on a small-N sample and against a
strictly harder bar (F5 is a brand-new hurdle every piece must now also clear). The one clear,
traceable regression (F1_grounding, first-fail 17%→44%) has an identified, evidenced mechanism —
new gates' (F5, and F9 as before it) repair rounds write new prose with no grounding check — not a
new mystery. F9 (the dominant blocker in every run so far, 45%+ of held pieces across the whole
AA-404 window) did not move. F5 itself is validated as correctly-calibrated, real, deterministic
signal — the win here is diagnostic clarity, not yet a pass-rate win.

**Recommendation for 17/08:** don't present run 6 as "the fixes worked" — the honest framing is
"batch 2 didn't regress F9 (the real 17/08 topic) and surfaced a concrete, fixable new gap (F5/F9
repair rounds need the same grounding-awareness `PieceInvariants` already gives F3/F8)." The
highest-leverage next step, directly evidenced by this run and cheap given `PieceInvariants`
already exists as the mechanism (PR #154): extend it to carry `atom_text_by_id` into every repair
round regardless of which gate triggered it, exactly as STEP-0-mở-rộng's own deferred-not-forgotten
note anticipated. Separately, the ECS health-check incident (Step 2) deserves its own Linear ticket
— it's an operational risk to any future unattended N7 run, independent of AA-404's content work.

## Not done (per task scope)

- No repair/retry outside the natural pipeline was run.
- No threshold/code change made to F5 or anything else.
- Linear not updated — left for Claude Chat per task instruction.
