# AA-513 STEP0 — investigation record (2026-09-02)

## §1. T9 prompt/context structure (`services/acp_content_writing/prompts.py`/`service.py`)

**Real remaining gap is narrower than Linear's own text implies** — AA-511's own Gap A fix
(PR #274, already merged, migration 134) already built MOST of what AA-513 asks for:

- `service.py::_fetch_route_text()` **already exists** and, for a Route/Blog pick
  (`req["route_segment_ids"]` set), already resolves EVERY Segment's live representative atom
  and joins their text (`"\n\n".join(texts)`) in the Route's own day order
  (`route_segment_ids` = `route.ordered_segment_ids`, copied at pick time — AA-510's own field,
  confirmed by reading migration 131/134, not guessed). `start_write()` already calls this
  instead of the single-atom fetch whenever `route_segment_ids` is set. **This already satisfies
  Việc 1** ("đưa cả ordered_segment_ids vào context theo đúng thứ tự Route") — no code change
  needed there.
- **What's genuinely still missing (Việc 2 — confirmed by reading, not guessed):**
  `context["atom_id"]` (passed to `build_user_prompt()`'s single `atom_id` param, which
  `_BLOG_FORMAT_INSTRUCTIONS.format(atom_id=...)` uses for the ENTIRE piece's citation tag) is
  still just `req["atom_id"]` — the ONE representative atom `pick_subject()` resolved for the
  FIRST segment. Every fact from every OTHER segment in the joined seed still gets told to cite
  that SAME single id. The model is never told there are multiple distinct sources with their
  own ids — this is the real, confirmed gap.

## §2. F5 tag+strip mechanism — already multi-id-agnostic where it matters, confirmed by reading

- `TAG_RE = re.compile(r"\[(?:R|F):([^\]]+)\]")` and `_STRIP_TAG_RE` — both GENERIC patterns,
  already match ANY id inside the brackets, not one hardcoded literal. **`strip_citation_tags()`/
  `deep_strip_citation_tags()` already correctly strip multiple different ids with zero code
  change needed.**
- `gate_atom_density()` (F5) — checks only "does each 300-word window contain >=1 tag of any
  kind", never checks WHICH id. **Already multi-id-agnostic, no change needed.**
- `gate_grounding()` (F1) — checks `find_novel_numeric_claims(sent, [atom_text])` against the
  FULL joined `atom_text` (all segments' text, since that's what `_fetch_route_text()` already
  produces) — **already correctly checks a sentence from ANY segment against the whole Route's
  fact pool, not just one atom.** No change needed.
- `gate_banned_patterns()` (F2) — same `atom_text` (joined), same reasoning, no change needed.
- The module's own docstring at `TAG_RE` says *"T9 has exactly one atom per piece"* — this
  comment is now STALE for the Route case (confirmed a real, if harmless, doc-drift — the code
  itself already works for a joined multi-atom `atom_text`, the comment just wasn't updated when
  AA-511 Gap A shipped). Corrected as part of this build (comment-only fix, no behavior change).

**Real, confirmed, NOT-in-scope observation** (ADR 0009's "claim support" gate — a cited
sentence must share a distinctive word with what it cites, i.e. validate the SPECIFIC id used,
not just presence) was never ported to AA-CIS at all (AA-450/452 sessions' own scope, not this
one) — neither Linear's AA-513 text nor AA-514's text asks for it. Flagged, not built — would be
a real follow-up if per-segment tag ACCURACY (not just presence) ever needs verifying.

## §3. ADR 0009 (Ms. Thư repo) — confirms AA-CIS's `[R:id]`/`[F:id]` subset port is deliberate

Origin ports 3 tags: `[A:…]` Atom, `[T:…]` trip fact, `[F:…]` Facts Entry (`[S:…]` stance
explicitly NOT ported even there). AA-CIS's own AA-450/452 sessions already made a SEPARATE,
already-settled scoping decision to only port 2 of these (`R`≈Atom, `F`≈Facts Entry) — not
something AA-513 re-opens. Confirms the tag SHAPE is settled; what's missing is only "the model
knows which of several real ids to use for which segment", per §1.

## §4. `subject.route_id`/`ordered_segment_ids` — confirmed field names, no guessing

`acp_shared.subject.route_id` (migration 131/133) → `acp_contract.route.ordered_segment_ids`
(migration 131, `JSONB NOT NULL`) → copied verbatim into `angle_gate_request.route_segment_ids`
(migration 134) at `pick_subject()` time. `start_write()` already reads
`req["route_segment_ids"]` (via `angle_gate_service.fetch_request()`) — confirmed the exact
field, not assumed.

## Net STEP0 conclusion — real remaining build scope for AA-513

1. `service.py::_fetch_route_text()` → extend to also return each segment's own `atom_id`
   alongside its text (not just the joined string) — needed so the prompt can label each
   segment with the RIGHT id.
2. `context` gains `route_segments: list[tuple[atom_id, text]] | None` (None for every non-Route
   request — unchanged legacy behavior). `atom_text`/`context["atom_id"]` (used by the GATES,
   `gate_grounding`/`gate_banned_patterns`) stay EXACTLY as they are today (joined plain text,
   first segment's id) — deliberately NOT touched, to avoid 2 real risks confirmed by reading:
   (a) embedding id-labels into the gate corpus text would let `find_novel_numeric_claims()`
   pick up stray digits from an atom_id string (e.g. `atom_00af646e46`) as false "supporting
   numbers", silently weakening F1; (b) the gates already work correctly today, unchanged.
3. `prompts.py::build_user_prompt()` gains `route_segments: list[tuple[str, str]] | None = None`
   — when given (len > 1), the CONTENT SEED section is rendered as labeled moments
   (`[Moment id=<atom_id>]\n<text>`, blank-line separated) instead of the flat single-atom
   string, and `_BLOG_FORMAT_INSTRUCTIONS` gains a route-aware variant explaining "each moment
   above has its own id — tag a fact with THAT SAME moment's id, never a different moment's".
   `route_segments=None` (every existing caller) is BYTE-IDENTICAL to current behavior — the
   only way to reach the new branch is a real Route/Blog pick.
4. `generate.py::write_content()`/`rewrite_with_feedback()` — thread `route_segments` through to
   `build_user_prompt()`, default `None`.
5. Comment-only fix: `TAG_RE`'s "exactly one atom per piece" docstring line, now stale for Route.
6. No change to `quality_gates.py` itself (§2 confirmed already correct).
