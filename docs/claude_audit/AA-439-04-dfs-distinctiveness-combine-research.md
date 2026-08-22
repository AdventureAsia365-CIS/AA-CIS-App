# AA-439-04 — Research only: does `aa-marketing-v2` ever combine DFS + distinctiveness?

**Pure reading task, per instructions — no design proposed, no code written, no formula
recommended below.** Goal: confirm whether the original design (`aa-marketing-v2`, chị Thư's
spec) ever describes combining atom `distinctiveness` (competitor-overlap scoring, confirmed in
AA-439-03) with DataForSEO (DFS) relevance/volume data into one score or two parallel axes — so
any future design either builds on that precedent or is knowingly a new decision, not a
rediscovery.

**Answer, upfront: no combined score or formula exists anywhere in the folder.** One real,
precise point of contact between the two concepts was found (§4) — quoted verbatim below — but
it is not a score; it's two separate labels handed to an LLM in the same prompt context for a
different purpose (brief-writing gap analysis, not atom prioritization). Everything else is
listed in §6 as raw material only.

---

## 1. Full file listing — `docs/AI-gent-for automation works/aa-marketing-v2/`

```
.env.example
CONTEXT.md                          (320 lines — read fully, incl. at AA-439-03)
README.md                           (193 lines — read fully, incl. at AA-439-03)
requirements.txt
run.py                              (299 lines — read fully, this task)
aamc/__init__.py
aamc/agents/adapter.md              (1 line  — read fully, this task)
aamc/agents/brief_analyst.md        (1 line  — read fully, this task)
aamc/agents/decomposer.md           (7 lines — read fully, this task)
aamc/agents/extractor.md            (1 line  — read fully, this task)
aamc/agents/judge.md                (1 line  — read fully, this task)
aamc/agents/planner.md              (1 line  — read fully, this task)
aamc/agents/repairer.md             (1 line  — read fully, this task)
aamc/agents/summarizer.md           (1 line  — read fully, this task)
aamc/agents/writer.md               (9 lines — read fully, this task)
aamc/config.py                      (113 lines — grepped, relevant lines read)
aamc/corpus.py                      (278 lines — read fully at AA-439-03; re-checked here)
aamc/dataforseo.py                  (152 lines — read fully, this task)
aamc/delivery.py                    (218 lines — grepped, no relevant hits beyond keyword list)
aamc/gates.py                       (316 lines — grepped, no relevant hits)
aamc/generation.py                  (240 lines — grepped, no relevant hits)
aamc/intake.py                      (251 lines — grepped, one hit, quoted §6)
aamc/learning.py                    (119 lines — grepped, no relevant hits)
aamc/llm.py                         (152 lines — grepped, no relevant hits)
aamc/models.py                      (417 lines — relevant class defs read fully, quoted §6)
aamc/planning.py                    (343 lines — D3 pre-rank section read fully, quoted §5)
aamc/research.py                    (194 lines — read fully, this task — contains the §4 finding)
aamc/storage.py                     (78 lines — grepped, no relevant hits)
sample_data/brand.md
sample_data/intake_form.json
sample_data/trips.xlsx  (+ its Zone.Identifier ADS file)
tests/__init__.py
tests/smoke_det.py                  (186 lines — grepped, one hit, quoted §6)
```

Files read fully at AA-439-03 (not re-read line-by-line here, only re-verified against fresh
greps): `CONTEXT.md`, `README.md`, `aamc/corpus.py`. **Every other file above was newly read (in
full, if small; via full-file grep + targeted reads of every hit, if large) as part of this
task.** No file in the folder was skipped.

---

## 2. Grep results — every hit, across the whole folder, for every requested keyword

Ran across all `.py`/`.md` files in the folder (case-insensitive where noted):

**`dataforseo` / `\bdfs\b`** — 24 hits total, spanning `run.py`, `README.md` (7 hits),
`aamc/models.py` (2, the `confidence: Literal["dfs","heuristic"]` fields), `CONTEXT.md` (6),
`aamc/config.py` (3), `aamc/dataforseo.py` (5, the module itself), `aamc/research.py` (3),
`tests/smoke_det.py` (1). All either (a) the DFS client module itself, (b) the `confidence`
field marking a record as DFS-sourced vs. heuristic, or (c) prose describing DFS's role in
keyword/SERP research. None combine DFS with `distinctiveness` in a formula.

**`search_volume`** — 5 hits: `CONTEXT.md` (1, prose), `aamc/dataforseo.py` (3, the actual
function + its internal field access), `aamc/research.py` (1, calling it). All keyword-level,
never atom-level.

**`distinctiveness`** — 19 hits, fully listed and already covered by AA-439-03 for the
`corpus.py`/`CONTEXT.md` ones. **New this task**: `aamc/planning.py` (5 hits, the D3 pre-rank
formula, quoted §5), `aamc/research.py` (1 hit — the §4 finding), `aamc/intake.py` (1 hit,
quoted §6), `tests/smoke_det.py` (1 hit, a test fixture constructing an `Atom` with a
`distinctiveness` value — no formula, just test data), `run.py` (3 hits, CLI print statements
only — `print(f"   [{a.distinctiveness}] {a.text[:90]}")` and two prose comments, no logic).

**`relevance`** — zero hits anywhere in the folder.
**`priority_score`** — zero hits anywhere in the folder.
**`combined`** — zero hits anywhere in the folder.
**`keyword` (broad)** — many hits, all confined to Module C (research/briefs) and the
`KeywordRecord`/`SERPProfile` models — never joined to an `Atom` field.

---

## 3. `CONTEXT.md` §5 Module C — read in full (not just the previously-quoted lines)

The complete Module C block (already excerpted in AA-439-03; reproduced here in full per this
task's step 6):

> **C1 `keyword_research(scope) -> KeywordSet`** · DET — DataForSEO search_volume + keyword_suggestions; cached; offline ⇒ confidence "heuristic". Location targeting = source markets (Decisions), NOT destination. Seeds: trips' DFS_QUERY + name-derived + PAA harvest.
>
> **C2 `serp_read(keyword) -> SERPProfile`** · DET — DFS serp_organic + PAA + related searches: top-10 composition, intent verdict, ranking word-count range, PAA set, competitor presence flags.
>
> **C3 `compile_brief(slot_or_topic) -> Brief`** · DET assembly + 1 LLM gap-analysis call
> Contexts for the gap call [C2]: top-3 ranking pages parsed (DFS on_page content_parsing) + our atom set for the topic. Brief fields: keyword + demand evidence (volume, intent verdict, word range), required H2s, faq_candidates (each with a REQUIRED source atom/facts id — unanswerable → dropped → unknown ledger), gap statement ("all three ranking pages miss X; atoms Y cover it"), atoms assigned per section, framework (from table by stage/format), structural-variance directives, CTA target (live URL), language.
> Law: a topic with no demand evidence needs a stated reason (campaign overlay or Decision) to exist — "content we want to write" cannot pass silently. Failure: corpus can't support required sections ⇒ topic rejected → ledger + alternative proposed.

Nothing in this module's spec text assigns a DFS-derived number to an individual atom. "Our atom
set for the topic" is consumed as-is (with whatever `distinctiveness` it already carries) —
never re-scored using `volume`/`intent_verdict`/anything else DFS produces.

---

## 4. The one real point of contact — quoted verbatim, in full context

`aamc/research.py`, function `compile_brief()` (C3), the LLM gap-analysis call:

```python
data = llm.call_json(
    ws, function="C3.compile_brief.gap", agent="brief_analyst",
    corpus={
        "top_ranking_pages": json.dumps(top_pages) or "(offline — no SERP parse)",
        "our_atoms": "\n".join(f"{a.atom_id}: {a.text} [{a.distinctiveness}]" for a in atoms),
        "our_facts": "\n".join(f"{f.entry_id}: [{f.category}] {f.claim_text}" for f in usable_facts),
    },
    task=f"Keyword: '{keyword.keyword}'. Identify what ranking pages miss that our atoms cover; "
         f"propose required H2s (4–6) and assign atom_ids per section. "
         f"Only use listed atom/fact ids.",
    output_contract=contract)
```
(`aamc/research.py:119-129`, `top_pages` sourced two lines above at `:114` from
`dataforseo.parse_top_pages(keyword.keyword, keyword.location)`, itself a DFS call.)

**What this actually is**: the ONE place in the whole codebase where DFS-sourced data
(`top_ranking_pages`, from competitor page parsing) and each atom's `distinctiveness` label
appear in the **same function call** — but:
- `distinctiveness` is passed as a plain inline text label (`[HIGH]`/`[MED]`/`[LOW]`) next to
  the atom's own text, for an **LLM to read as context**, not as a number in a formula.
- The LLM's job (per `brief_analyst.md`, quoted §6) is to find what competitor pages MISS and
  which atoms cover the gap — a qualitative judgment, not a re-score of the atom itself.
- This happens **once per brief/topic** (i.e., once per piece being written), not as a
  persistent update to the atom's own stored `distinctiveness` value — nothing here writes back
  to `Atom.distinctiveness` or creates any new atom-level field.
- No `KeywordRecord.volume` or `SERPProfile.intent_verdict` value is passed into this call
  alongside the atoms at all — only the parsed page *content* (`top_ranking_pages`) is, and
  `parse_top_pages()` itself (`dataforseo.py:143-152`) doesn't even carry volume/intent through;
  it only returns `{domain, content}` pairs.

**Conclusion: this is context-juxtaposition inside one LLM prompt, not a combined score.** It's
real, it's precise, and it's the single closest thing to what the task asked for — but it does
not constitute a "combine DFS + distinctiveness" design in any formula sense.

---

## 5. D3 quarter-plan pre-rank — the only place `distinctiveness` appears in an actual formula, and it has no DFS term

`aamc/planning.py:166-181` (already partially quoted at AA-439-03 via the CONTEXT.md prose and
the ported current-codebase equivalent; here is the **original reference code itself**, in full):

```python
# DET pre-rank: runway fit × distinctiveness × atom richness × strategic flag
...
for t in reg.trips:
    ...
    runway_fit = sum(1 for m in q_months for mk in markets
                     if rm.stage(dest, mk, m) in ("BOFU", "MOFU")) / (len(q_months) * len(markets) or 1)
    richness = min(len(atoms) / 10, 1.0)
    dist = sum({"HIGH": 1.0, "MED": 0.5, "LOW": 0.1}[a.distinctiveness] for a in atoms) / (len(atoms) or 1)
    forced = any(s in t.name.lower() or s in (t.destination or "").lower() for s in specials)
    score = runway_fit * 0.4 + richness * 0.3 + dist * 0.3 + (1.0 if forced else 0.0)
```

Four terms: `runway_fit` (booking-window timing, from the deterministic runway map — no DFS),
`richness` (raw atom count), `dist` (distinctiveness average — competitor-overlap based, no
DFS), `forced` (a 90-day special override, from agency intake text-matching — no DFS). **DFS
data never enters this formula at any point, confirmed by reading the whole function, not just
the `distinctiveness` line.** This is trip-level scoring (which trips make the quarter plan),
not atom-level scoring — a separate question from "which atoms within a chosen trip are worth
prioritizing," which is what T6 curation and the N6 allocator weight (already covered in
AA-439-03) actually need.

---

## 6. Raw material for a future design — listed, not synthesized

Per the task's explicit instruction, these are handed over as-is, with no formula proposed:

**Distinctiveness side (already fully covered in AA-439-03, restated for completeness):**
- `score_distinctiveness(text, idx) -> "HIGH"|"MED"|"LOW"` — token-overlap (≥4-char words)
  against a `CompetitorIndex.phrases` corpus (scraped competitor page sentences, 40-220 chars
  long, up to 120 per domain). Thresholds: ≥0.6 overlap → LOW, ≥0.3 → MED, else HIGH. No
  competitor index yet → defaults to MED ("honest middle").

**DFS side — every field actually available in the reference implementation, verbatim from
`aamc/models.py`:**
```python
class KeywordRecord(BaseModel):
    keyword: str
    location: str
    volume: Optional[int] = None              # null ⇒ confidence heuristic, never fabricated
    confidence: Literal["dfs", "heuristic"] = "heuristic"
    cpc: Optional[float] = None
    retrieved_at: Optional[date] = None

class SERPProfile(BaseModel):
    keyword: str
    location: str
    intent_verdict: Literal["informational", "commercial", "transactional", "mixed", "unknown"] = "unknown"
    word_count_range: Optional[tuple[int, int]] = None
    paa_questions: list[str] = Field(default_factory=list)
    related_searches: list[str] = Field(default_factory=list)
    top10_domains: list[str] = Field(default_factory=list)
    competitor_present: bool = False
    confidence: Literal["dfs", "heuristic"] = "heuristic"
```
No `keyword_difficulty` field exists in this reference implementation (a metric DataForSEO does
offer in its real API, per the current AA-CIS-App codebase's own `dataforseo_client.py` — not
re-checked here, out of scope, flagged only as a fact worth knowing when designing).

**The `Atom` model itself has no keyword/DFS-linkage field of any kind** (`aamc/models.py:82-97`,
full field list quoted) — no `keyword_id`, no `search_volume`, no `serp_profile_id`. Any future
design that wants to join an atom to a specific keyword's DFS data would need a new field/join —
there is no existing hook to repurpose.

**`aamc/intake.py:231`** (the mirror-rendering step, A5) — the only other `distinctiveness`
reference found outside `corpus.py`/`planning.py`/`research.py`:
```python
"text": a.text[:110], "distinctiveness": a.distinctiveness,
```
— purely a display field for the "your business as we read it" mirror screen, no computation.

**`tests/smoke_det.py:120,75`** — test fixtures (`KeywordRecord(..., volume=4400,
confidence="dfs")`, `Atom(..., distinctiveness=dist)`) — confirm the two models are exercised
independently in tests too, never jointly.

---

## Summary

| Question | Answer |
|---|---|
| Does `aa-marketing-v2` combine DFS + distinctiveness into one score? | **No — confirmed, whole folder read/grepped** |
| Does it use them as two separate but linked axes anywhere? | **No formal linkage** — only the one LLM-context juxtaposition in §4, which is not a score |
| Closest point of contact | `research.py::compile_brief()`'s gap-analysis LLM call — both appear in the same prompt context, for a different (qualitative, per-brief) purpose |
| Any atom-level DFS field in the data model? | **None** — `Atom` has no keyword/DFS-linked field at all |
| Was this ever discussed as a future direction? | Not found anywhere in the folder — no "TODO," no open question in §8 (`CONTEXT.md`'s own 14 grill questions) mentions this combination |
| Conclusion for Nghiep | **This would be a genuinely new design decision**, not a recovery of an existing-but-unbuilt idea. The two "ingredients" (§6) exist and are real, but nothing in chị Thư's original spec ever names or sketches how to combine them. |
