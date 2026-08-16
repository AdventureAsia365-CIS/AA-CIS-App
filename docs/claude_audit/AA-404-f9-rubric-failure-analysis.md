# AA-404 — F9 failure pattern analysis (quantitative), prep for Ms. Thư rubric discussion

Task: `docs/claude_tasks/AA-404-01-f9-failure-pattern-analysis.md`. Analysis only, no code
changes. Full dataset pulled fresh from `acp_deliver.pieces` via S3-mediated ECS Exec
(**123 real pieces, 12 N7 runs, 15/08–16/08/2026** — not the 69-piece/6-run sample the
earlier `AA-404-F9-deep-dive.md` used, and not reused numbers from any prior report).
**117 pieces used the production judge (Nova Pro); 6 used GPT-4.1** (AA-351-06's
controlled test, same day) — kept separate throughout so GPT-4.1's 0-failure run doesn't
quietly dilute the Nova Pro numbers Ms. Thư's conversation is actually about.

## Top-line number

**F9 fails 112/117 real pieces under the production judge — 95.7%.** Only 5 of those 112
ever got fixed by a repair round (2.7% repair-round success rate for F9, vs. 20.5% for
every other gate combined). This one number is why AA-404/AA-382/AA-351 all exist as
separate investigations — three different technical fixes (repair-prompt context, judge
model swap, and now this rubric-focused read) have all been tried against a rate that
hasn't meaningfully moved.

## (a) Failure-code frequency table

Two countings, both real, both useful for different questions. **"Final state"** = the
code(s) recorded in each piece's last judge call (what actually blocked it in the end).
**"Every round"** = every time a code appeared across ALL repair-round re-judgments of
the same piece (shows what the judge kept re-raising, not just the final verdict) — this
is the number that matters for the AA-382 convergence question specifically.

| failure_code | Final state (n=117 pieces) | | | Every round (n=183 F9 rounds) | | | Rubric origin |
|---|---:|---:|---:|---:|---:|---:|---|
| | **total** | blog | fb/tt | **total** | blog | fb/tt | |
| `GENERIC_AI_WORDING` | 95 | 24 | 71 | 154 | 18 | 136 | original (blog) |
| `SUMMARY_OFF_BRAND` | 76 | 20 | 56 | 130 | 13 | 117 | original (blog) |
| `BODY_EXPERIENCE_DETAILS_TOO_GENERIC` | 38 | 38 | – | 29 | 29 | – | original (blog) |
| `BODY_DAY_FLOW_STRUCTURE_WEAK` | 23 | 23 | – | 16 | 16 | – | original (blog) |
| `BODY_SUMMARY_LINE_INCOMPLETE` | 21 | 21 | – | 7 | 7 | – | original (blog) |
| `BODY_OPENING_TITLE_WEAK` | 15 | 15 | – | 9 | 9 | – | original (blog) |
| `CTA_MISSING_OR_WEAK` | 7 | – | 7 | 15 | – | 15 | **new (social, AA-372)** |
| `DFS_INTENT_UNDERUSED` | 10 | 10 | – | 4 | 4 | – | original (blog) |
| `HOOK_WEAK` | 6 | – | 6 | 5 | – | 5 | **new (social, AA-372)** |
| `KEYWORD_STUFFING_RISK` | 5 | 5 | – | 2 | 2 | – | original (blog) |
| `FACT_CHECK_MANUAL_CHECK` | 0 | 0 | 0 | 1 | 1 | 0 | original (both) |
| `PRODUCT_TRUTH_RISK` | 0 | 0 | 0 | 0 | 0 | 0 | original (blog) |

**Top 2 by a wide margin, both counting methods, both rubrics**: `GENERIC_AI_WORDING`
and `SUMMARY_OFF_BRAND` — together 171/213 (80%) of all final-state code-occurrences,
and 284/374 (76%) of every-round occurrences. Both codes are shared vocabulary between
blog and social. Everything below focuses on these two.

## (b) Real flagged_phrases — 12 examples, with an actual opinion on each

Pulled from the most recent runs (16/08, post every fix shipped so far), across all 3
channels. `flagged_phrases` is the judge's own mandatory verbatim quote (AA-404 fix #3
forces this — confirmed working: every quote below is a real exact substring of the
piece's `body_tagged`, not paraphrased).

**GENERIC_AI_WORDING — my read: roughly half of these look like real problems, half look
like the rubric's own stated "GOOD" example being flagged anyway:**

1. *"Seongsan Ilchulbong didn't form from a conventional eruption — it rose from the sea
   floor through a hydrovolcanic explosion, leaving a tuff cone at Jeju's eastern tip that
   UNESCO recognised as a World Heritage site"* (facebook) — **I disagree with this flag.**
   This is a near-exact structural match to `GENERIC_AI_WORDING_ANCHOR`'s own hard-coded
   GOOD example (Gyeongju bullet train: place name + real geological/historical fact +
   verifiable detail). If this fails, the anchor example in the prompt isn't actually
   calibrating the judge.
2. *"The Olle Trail's coastal stages bring you within reach of it on foot, which is a
   different encounter than arriving by road."* (facebook) — **disagree.** Named real
   trail, concrete contrast, no superlative padding.
3. *"There is a quiet satisfaction in earning that approach."* (facebook) — **agree, this
   one is a fair flag.** No concrete anchor, could be pasted onto literally any
   physically-earned travel moment. This is the templated-filler shape the rubric wants
   caught.
4. *"These aren't stops on a loop — they're the reason to design a journey around this
   country specifically."* (tiktok) — **borderline, lean disagree.** Reflective, no hard
   fact, but it's making a real structural claim about the itinerary (not swappable to
   any destination without editing "this country").
5. *"South Korea rewards the traveller who arrives with a specific itinerary rather than a
   general curiosity — Dorasan exists, the palaces exist, the cable car exists, but none of
   them connect themselves."* (tiktok) — **disagree.** Names 3 real, specific attractions;
   makes a genuinely non-generic argument about trip planning.
6. *"Drive to Seongsan Ilchulbong Peak, a UNESCO World Heritage S"* (blog) — **not a rubric
   question at all — see the code bug below.** This "phrase" is literally a truncated,
   broken H2 heading; the judge is correctly flagging genuinely malformed content.

**SUMMARY_OFF_BRAND — the judge's own `notes` field undercuts several of its own flags:**

7. *"Seoul at dusk has its own logic."* (tiktok) — judge's own notes on this piece: *"the
   language, while evocative, leans towards a more poetic [style]..."* — **I disagree with
   this flag, and so, functionally, does the judge's own stated reasoning.** The original
   spec (`CONTEXT.md` §1.6.1, quoted below) defines the brand-reject target as "loud/
   salesy/brochure-like — AI defaults ARE brochure voice." A quiet 6-word declarative
   sentence is the structural opposite of brochure voice.
8. *"That grounding carries weight."* (tiktok) — same piece, same judge reasoning. **Disagree**, same basis.
9. *"The pace here is deliberate"* (facebook) — **disagree.** Short, restrained, on-brand
   for a "calm, unhurried" voice per the brand rubric itself.
10. *"no mass-transit crowds at the tumuli of Daereungwon, no queues at the stone
    observatory of Cheomseongdae"* (facebook) — **disagree.** Two named real landmarks,
    specific claim (no crowds/queues) — this is evidence-bearing prose, not generic.
11. *"delivers you to Gyeongju"* (facebook) — flagged as a 4-word fragment with no
    surrounding context in the quote itself. **Can't fully evaluate** — too short a
    fragment to judge register on its own, which is itself a minor evidence-quality
    complaint (the rubric requires a quote but not a *complete-thought* quote).
12. *"Two or three days. Tailored carefully. That's not transit. That's a journey."*
    (tiktok) — **agree, fair flag.** This is closer to templated ad-copy cadence
    (short-punchy-contrast pattern), the one example in this set I'd call genuinely
    brochure-like.

**My honest tally on this sample: 8/12 look like defensible false positives (the judge
flagging exactly the kind of specific/quiet/on-brand prose the spec says NOT to flag),
2/12 are unrelated to rubric calibration (a real code bug, see below), 2/12 are fair
catches.** This is a 12-item read, not a statistically rigorous sample — but it's
consistent with the volume: 95.7% fail rate is not plausible if 2/3 of real flags were
this defensible.

## Separate finding, NOT a rubric question — a real code bug

**12/41 blog pieces (29%) have literally truncated H2 headings in the actual piece body**,
independent of any judge, cut off mid-word at a hard 59-60 character limit. Confirmed by
reading the real `body_tagged`:

```
## Drive to Seongsan Ilchulbong Peak, a UNESCO World Heritage S

Hallim Park on Jeju's northwest coast contains Sangyong Cave...
```

Traced to one line: `services/acp_produce/research.py:281`
```python
required_h2s += [a["text"][:60] for a in atoms[:3]]
```
`compile_brief()` (C3) hard-truncates an atom's raw text to exactly 60 characters with no
word-boundary awareness to build `Brief.required_h2s` — the writer (E1/E2) then renders
these fragments verbatim as literal markdown H2 headings. All 12 truncated headings this
dataset caught are exactly 59-60 characters. This is very likely inflating both
`BODY_OPENING_TITLE_WEAK` (a broken heading obviously scores as "weak") and
`GENERIC_AI_WORDING` (broken/incomplete prose reads as low-quality) — but it is a
one-line code bug, not a judge-calibration question. **Flagging for Nghiep to fix
separately — not fixed here, out of this task's docs-only scope.**

## Separate finding — F9 now duplicates a gate that already exists, and disagrees with it

The F9 deep-dive (17/08) recommended building a deterministic atom-density gate instead
of asking F9's LLM judgment to catch the same thing — **this was done** (`F5_atom_density`,
merged 16/08 00:35, commit `0ea2c5d`). But F9's rubric/prompt was never updated after:

**Every one of the 16 blog pieces produced by runs AFTER F5 existed still got
`BODY_EXPERIENCE_DETAILS_TOO_GENERIC` from F9 — 16/16, 100%, regardless of what F5 said.**
9 of those 16 had `F5_atom_density: passed=true` (the deterministic check found adequate
atom citation density) and F9 flagged the same piece as too-generic-on-detail anyway.
F9 and F5 are structurally supposed to measure the same thing (per the original spec —
see below) and they disagree in the majority of cases where they could be compared. This
is a clean, quantified case for either dropping `BODY_EXPERIENCE_DETAILS_TOO_GENERIC`
from F9 now that F5 exists, or clarifying that it means something narrower than raw atom
density — a good concrete example to bring to the rubric conversation.

## (c) Original (Ms. Thư) vs. new rubric — hypothesis confirmed, not by inference

Found the actual pre-port source: `docs/AI-gent-for automation works/aa-marketing-v2/
CONTEXT.md` (the aamc prototype spec) and its `judge.md` agent instruction — this is
Ms. Thư's original design, not a paraphrase.

**Blog F9 is Ms. Thư's rubric, essentially unchanged in substance.** `CONTEXT.md` line 249
(verbatim): *"F9 brand_seo_audit (LLM rubric from compiled brand pack; review order:
product truth → brand fit → trip type → highlights → readability → SEO → publish
readiness; score fields brand_fit / human_read / seo_fit / trip_type_accuracy /
publish_readiness ∈ {1,0}; ... failure codes incl. PRODUCT_TRUTH_RISK, SUMMARY_OFF_BRAND,
HIGHLIGHTS_TOO_GENERIC, ITINERARY_STRUCTURE_WEAK, SEO_TITLE_WEAK, META_INCOMPLETE_SENTENCE,
DFS_INTENT_UNDERUSED, KEYWORD_STUFFING_RISK, GENERIC_AI_WORDING, FACT_CHECK_MANUAL_CHECK"*
— identical 10 codes (4 renamed, `BRAND_SEO_FAILURE_CODES` in `gates.py`, purely to fix an
unrelated string-collision bug with S1's vocabulary — AA-396's own comment says so), same
5 score fields, same review order, nearly word-for-word in the current prompt.

**Social F9 (`SOCIAL_SEO_FAILURE_CODES`, `_SOCIAL_RUBRIC_FIELDS`) does not exist anywhere
in the original spec** — no per-channel breakdown, no facebook/tiktok-specific fields, at
all. Confirmed as a later engineering addition: `gates.py`'s own code comment dates it to
06/08/2026 (AA-372), explicitly acknowledging it was built without real failure data —
*"2-3 criteria per channel, because no real FB/TikTok piece has run through F8/F9 yet to
know what it actually needs... extend from real failures, don't guess the full blog-shaped
rubric ahead of data."* **The hypothesis is confirmed, not just plausible**: the rubric
Ms. Thư never wrote is the one that's now failing hardest (see channel table below).

One more original-spec detail worth surfacing directly: `judge.md`'s instruction is
*"When uncertain, output 0 and the failure code FACT_CHECK_MANUAL_CHECK."* — the
uncertain-fails default is Ms. Thư's own instruction, not an engineering addition. Whether
that was meant to apply to every subjective score field or only factual claims (the one
case it names a specific failure code for) is exactly the kind of question this task
can surface but can't resolve — see the questions below.

## (d) Fail rate by channel

| Channel | F9 fail rate (Nova Pro, n=117) | "Perfect score but still failed" |
|---|---:|---:|
| **blog** (5 score fields) | 38/39 = **97.4%** | 0 observed |
| **facebook** (3 fields) | 35/39 = **89.7%** | 0/35 — field scores correlate with status |
| **tiktok** (2 fields) | 39/39 = **100.0%** | **35/39 (90%)** — hook_strength=1, cta_clear=1, status still `flagged` |

TikTok is structurally the worst case, worse than the deep-dive's earlier read (100% fail,
was already 21/21; now 39/39 on the larger sample, same pattern). TikTok's rubric asks the
judge to score exactly 2 fields, neither of which measures "generic wording" or "brand
voice" — yet those are the actual reasons for 39/39 fails. The judge is free-associating a
verdict the fields it fills in can't explain, 90% of the time. Facebook (3 fields) doesn't
have this disconnect — its field scores track its status honestly, it's just also failing
a lot on the same 2 codes as everything else.

## (e) Questions worth asking Ms. Thư — specific, not "is the rubric okay"

1. **F9 is now double-checking something a deterministic gate already checks, and
   disagreeing with it 9/16 times.** `BODY_EXPERIENCE_DETAILS_TOO_GENERIC` was your
   original code for "lacks concrete detail" — a dedicated atom-density gate (F5) now
   exists and passed 9 of the 16 real blog pieces F9 flagged this way anyway. Was
   `BODY_EXPERIENCE_DETAILS_TOO_GENERIC` always meant to be a broader judgment than raw
   atom-citation count (so F9 disagreeing with F5 is meaningful), or should it now defer
   to F5 and stop re-litigating the same axis?
2. **Is quiet/reflective register itself something you want flagged, or only its loud/
   brochure cousin?** Your original spec (§1.6.4) defines the brand-reject target as
   *"loud/salesy/brochure-like — AI defaults ARE brochure voice."* Real examples the judge
   flagged as `GENERIC_AI_WORDING`/`SUMMARY_OFF_BRAND` this week include *"Seoul at dusk
   has its own logic."* and *"That grounding carries weight."* — the judge's own `notes`
   field calls this prose "evocative" and flags it anyway for being "poetic." Is
   restrained/philosophical register itself a violation, or is the judge over-firing on
   the opposite of what you meant by "AI voice"?
3. **Was "when uncertain, output 0" meant for every score field, or only factual claims?**
   Your original `judge.md` instruction pairs uncertainty explicitly with
   `FACT_CHECK_MANUAL_CHECK` — a specific code for product-truth uncertainty. In practice
   `status` is a free judgment call the LLM makes independent of any score field (code
   confirms `status` is never computed from the 1/0 fields, just read directly from the
   judge's own JSON) — and the real fail rate under that default is 95.7%, with only 2.7%
   of repair attempts ever fixing it. Did you intend "fail on any doubt" to compound across
   5 (blog) or even 2 (TikTok) independent subjective judgments in one pass?
4. **(bonus, TikTok-specific)** TikTok's 2 score fields (hook_strength, cta_clear) are both
   perfect (1/1) in 35 of its 39 real fails — the actual reason for failure lives entirely
   outside anything the rubric asks the judge to score. Should TikTok's field set expand to
   include what's actually driving fails (voice/genericity), or is 2 fields deliberate and
   the free-text codes are meant to carry the rest?

## Should know

- All numbers above are pulled fresh this session (`acp_deliver.pieces` + `acp_shared.
  acp_v2_runs`, ECS Exec, 17/08/2026) — not reused from `AA-404-F9-deep-dive.md`,
  `AA-382-repair-rubric-context.md`, or either AA-351 GPT-4.1 report. Those reports'
  own summarized numbers were deliberately not treated as ground truth per this task's
  scope.
- The 6-piece GPT-4.1 run (AA-351-06, same day) is excluded from every Nova Pro number
  above — mixing it in would understate the real production fail rate.
- No rubric change proposed or made. No code change made (the H2-truncation bug and the
  F5/F9 redundancy are flagged as findings, not fixed, per task scope).
- This report + `docs/claude_tasks/AA-404-01-f9-failure-pattern-analysis.md`.
