# AA-512 FE wireframe — AngleGateTab.tsx changes (written before touching the .tsx, per build-prompt rule)

## Scope of the change

Only the **Subject-driven path** (`req.subject_id` set — the only live path today, per STEP0 §1)
changes visually. The legacy atom-picker path (`req.subject_id` null) is untouched — same
1·Atom → 2·Goal → 3·Angle → 4·Channel → 5·Write flow it has today, since it can never resolve a
subject/channel/score to show and measurable ranking can't run for it (STEP0 §2's channel-timing
reason). This keeps the change additive, no regression risk for the dead-but-present path.

## New Stepper (Subject-driven only): 1 Goal · 2 Angle · 3 Write

`currentStep()` gains a Subject-driven branch:
```
if (req.subject_id) {
  if (req.status === "pending_goal") return 1;      // Goal
  if (pending_choice/reusable)       return 2;      // Angle
  return 3;                                          // approved -> Write (channel already known)
}
```
`STEP_LABELS` becomes conditional: `subjectDriven ? [[1,"Goal"],[2,"Angle"],[3,"Write"]] :
[[1,"Atom"],[2,"Goal"],[3,"Angle"],[4,"Channel"],[5,"Write"]]`.

## New fixed header card (Subject-driven only, replaces the "1 · Atom" card)

Shown whenever `req.subject_id` is set, in every step — a small, non-editable info strip above
the step card (not a numbered step of its own, matches how the Write card's meta row already
shows Angle/Goal/Channel as a fixed summary once decided):

```
┌────────────────────────────────────────────────────────────┐
│  Writing for: Facebook            Score 3  (Segment/Route)  │
│  Ha Long Bay — sunrise kayaking                              │
└────────────────────────────────────────────────────────────┘
```
- Left: Channel display name (from `CHANNEL_STYLES_BY_KEY`-equivalent lookup already client-side,
  or just title-cased `req.channel`) — no picker, no click target (matches Linear: "không sửa
  được ở đây, không có bước chọn Channel").
- Right: `req.subject_score` (nullable — omit the whole "Score" chip if null, e.g. a
  pre-AA-511-Slate subject_id somehow with no score).
- Below: `req.subject_place` + (` — ` + `req.subject_action` if a Segment pick) or
  `req.subject_hub_name` (if a Route pick) — whichever the backend actually returns non-null.
  Falls back to nothing rendered (not an empty dash) if both are null (e.g. the Segment/Route was
  rebuilt away since the Subject was picked — matches `fetch_slate()`'s own documented
  stale-but-harmless LEFT JOIN behaviour).

States:
- **Loading**: card doesn't render at all until `req` resolves (matches existing pattern — no
  new loading state, `atomsLoading`/the existing per-request fetches already gate this).
- **Error**: none specific to this card — a failed `fetch_request()` already surfaces through the
  existing top-level `error` banner.
- **Empty** (subject_place/action/hub_name/score all null): renders channel name only, no second
  line, no crash.
- **Success**: full 2-line card as above.

## Angle cards (step "2/3 · Angle" — both Subject-driven and legacy, whenever ranking data exists)

Each of the 3 existing cards (name / why_it_works / formula_fit / best_final_style) gains ONE
badge row under the existing text, only rendered when the angle has ranking data
(`a.answers_count !== null` — i.e. `channel` was known at generation time, so ranking actually
ran; the legacy atom-picker path's angles have this null and the row is simply omitted, no
regression):

```
┌──────────────────────────────────────────────────┐
│ Sunrise Over the Bay                 [Recommended]│
│ Why it works: ...                                  │
│ Formula fit: ...                                   │
│ Best final style: ...                              │
│ ──────────────────────────────────────────────     │
│ ✓ answers 2/4 PAA questions   ⚠ 1 avoid-list hit   │
└──────────────────────────────────────────────────┘
```
- "answers X/Y PAA questions" — X = `a.answers.length`, Y = total real PAA pool size for this
  request (`req.dfs_paa_snapshot.people_also_ask.length`, 0 if no snapshot — badge reads
  "no PAA data" instead of "0/0" when Y is 0, so it doesn't look like a failure).
  Green/neutral tone.
- "N avoid-list hit(s)" — N = `a.violations.length`. Green/neutral when N=0 ("0 avoid-list
  violations"), amber/warning tone when N>0 (a real fixable-looking count, but this ticket does
  NOT auto-fix or block on it — matches ADR 0004's own "not a taste call but still just a
  ranking input", no new gate).
- Hovering (title attr) either badge lists the actual matched question text / violated phrase —
  cheap, no extra fetch, data already on the object.
- `recommended` (the pill already shown) now reflects the SERVER's measurable pick (post-AA-512),
  not the LLM's own opinion — no visual change needed, same badge, different backing logic.

No new loading/error/empty state beyond what's listed — this is a read-only annotation on data
the existing fetch already returns once the backend change ships.
