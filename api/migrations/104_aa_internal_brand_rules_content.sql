-- Migration 104: aa_internal real brand-rules content + cleanup of 6 mis-attached demo rows
-- (AA-404 F9 fix #1 — final wiring step)
--
-- Context: F9's judge (gate_brand_seo_audit()/gate_brand_seo_audit_social(), gates.py) has
-- always run on the hardcoded, generic AA_BRAND_IDENTITY_PROMPT constant, never the real
-- shared.tenant_brand_rules table -- confirmed in AA-404's F9 STEP 0/persona-row investigation
-- (docs/implementation-notes/AA-404.md) that aa_internal's row set there was unusable as-is:
-- 6 of 7 rows are confirmed test/demo data for OTHER (fictional B2B demo) tenants --
-- WildKind Travel, Terra Family Expeditions (x2 versions), Trail Pulse, Atlas & Hearth --
-- mistakenly created against aa_internal's tenant_id (same brand_name values as 4 separate,
-- real rows in shared.tenants for those tenants' own demo accounts), complete with Sigiriya/
-- Sri Lanka example content that has zero overlap with aa_internal's real catalog (South
-- Korea/Sapa/etc). The 7th row (brand_name='default', id 262dea1c-3910-4d69-ac60-97644a9ac76f)
-- is the one real Adventure Asia identity row -- core_idea already read "Discreet executive
-- adventure for senior professionals," matching AA_BRAND_IDENTITY_PROMPT's own stated
-- identity -- but its system_prompt/style_guide/forbidden_words/good_examples were all empty.
--
-- Content below was drafted (docs/implementation-notes' earlier session), reviewed and
-- approved by Nghiep (one round -- good_example #4 "different register of engagement" was
-- dropped for being a borderline judge call, not confidently a false positive), and is
-- applied here verbatim, unedited from the approved draft.
--
-- Two independent operations, same migration (mirrors migration 096's own precedent for
-- "changes that only make sense applied together"):
--   1. Archive + DELETE the 6 mis-attached demo rows -- narrow, explicit match on
--      tenant_id + brand_name IN (...), never a bare "everything except default" delete, so a
--      future 8th mis-attached row with a different brand_name wouldn't be silently caught by
--      this same clause if this migration were ever re-read as a template.
--   2. UPDATE the real 'default' row's 4 content columns.
--
-- Backup: archived into a same-migration-created table (shared.tenant_brand_rules_deleted_aa404,
-- full row snapshot + deleted_at) rather than only relying on migration idempotency/git history
-- -- Nghiep asked for a way to cross-reference the exact deleted content later without needing
-- to reconstruct it from this file's own INSERT VALUES (which only proves what SHOULD have
-- existed, not what the live row actually contained at delete time -- e.g. version bumps
-- between when this file's author read the data and when the migration ran).

BEGIN;

-- ---------------------------------------------------------------- Part 1: archive + delete
CREATE TABLE IF NOT EXISTS shared.tenant_brand_rules_deleted_aa404 (
    LIKE shared.tenant_brand_rules INCLUDING ALL
);
ALTER TABLE shared.tenant_brand_rules_deleted_aa404
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NOT NULL DEFAULT now();

INSERT INTO shared.tenant_brand_rules_deleted_aa404
SELECT tbr.*, now()
FROM shared.tenant_brand_rules tbr
WHERE tbr.tenant_id = (SELECT tenant_id FROM shared.tenants WHERE slug = 'aa_internal')
  AND tbr.brand_name IN (
      'WildKind Travel', 'Terra Family Expeditions', 'Trail Pulse', 'Atlas & Hearth'
  )
  AND NOT EXISTS (
      SELECT 1 FROM shared.tenant_brand_rules_deleted_aa404 d WHERE d.id = tbr.id
  );

DELETE FROM shared.tenant_brand_rules
WHERE tenant_id = (SELECT tenant_id FROM shared.tenants WHERE slug = 'aa_internal')
  AND brand_name IN (
      'WildKind Travel', 'Terra Family Expeditions', 'Trail Pulse', 'Atlas & Hearth'
  );

-- ---------------------------------------------------------------- Part 2: real content
UPDATE shared.tenant_brand_rules
SET
    system_prompt = 'You are writing for Adventure Asia, a discreet executive adventure travel brand.

Core idea: Discreet Executive Adventure — considered, private journeys for travellers who have
already seen the obvious destinations and want depth, precision, and quiet quality instead of
spectacle.

Target market: US, UK, AUS. Senior professionals, 40-60, $250k+ income.

Customer mindset: They are well-travelled and hard to impress with generic superlatives. They
notice when writing is templated. They want specific, verifiable detail — a real place, a real
fact, a real number — not a mood board of adjectives. Refinement is assumed; it never needs to
be stated.

Tone of voice: calm, assured, well-travelled, selective, precise, private, curated, composed,
human, premium, controlled.

CTA: "Design This Journey" — never "Book Now" or any urgency-driven phrase.

Writing style: State facts plainly and let specificity carry the premium feel. Name the place,
the era, the distance, the craft. Write the way a well-travelled colleague would recommend a
trip they actually know, not the way a brochure sells one. A sentence built from a concrete,
verifiable detail is on-brand even when its register is quiet or understated — do not mistake
calm, unhurried writing for genericness just because it lacks superlatives.',

    style_guide = 'Voice attributes, what each means in a real sentence:
- CALM — unhurried pacing, no urgency. Do not write "don''t miss out," "limited availability,"
  "book now," or anything that manufactures scarcity.
- ASSURED — state facts plainly and confidently. Do not hedge and do not lean on superlatives
  to prove a place is worth visiting — let the detail do that work.
- WELL-TRAVELLED — write like someone who has actually been many places and is not easily
  impressed. Reference a specific, verifiable detail instead of expressing generic awe.
- SELECTIVE — implies the trip was chosen and edited, not mass-produced. Avoid "one of the
  best," "so much to see."
- PRECISE — name the place, the era, the distance, the number. "Royal burial mounds from the
  Silla Kingdom" is precise; "rich culture" and "stunning views" are not.
- PRIVATE — speak to one reader, not a crowd. Avoid "everyone," "all ages," "the whole family
  will love."
- CURATED — implies deliberate selection. Avoid "diverse," "endless," "a treasure-trove of."
- COMPOSED — measured rhythm, not breathless. No exclamation points, no stacked adjective
  chains ("vibrant, dynamic, unforgettable" is itself a generic-AI tell).
- HUMAN — reads like someone actually noticed this place, not a template with the destination
  swapped in. If the sentence still makes sense with a different country''s name dropped in, it
  fails this bar.
- PREMIUM — implied by expertise and restraint, never stated outright. Do not write "luxury" or
  "world-class" — let specificity carry the premium feel.
- CONTROLLED — restraint over enthusiasm. A fact stated plainly reads as more premium than the
  same fact stated with exclamation.

Sales-pushy language to avoid: "book now," "don''t miss out," "limited spots," "act fast,"
"hurry," "last chance."

STRUCTURAL patterns to avoid (Ms. Thu''s original spec):
- "Balanced triads" — three adjectives/clauses stacked for rhythm, not meaning (e.g. "bold,
  vibrant, and unforgettable").
- Restating a conclusion ("In conclusion," "Ultimately, this journey...").
- "Whether you''re X or Y" audience-hedging — Adventure Asia writes to ONE reader.

BAD examples (illustrative, not from any real tenant''s content):
1. "Discover a breathtaking, unforgettable journey through South Korea''s vibrant culture and
   stunning landscapes — an experience like no other, waiting to be explored." — empty
   superlatives, no concrete detail, could be pasted onto any country.
2. "This trip is bold, vibrant, and endlessly exciting — a hidden gem you won''t want to miss.
   Book now and embark on the adventure of a lifetime!" — balanced triad + urgency + forbidden
   CTA + "hidden gem" in one sentence.
3. "Every step of this journey reveals something new, blending timeless tradition with modern
   energy in a way that leaves a lasting impression on every traveller." — hard case: contains
   NO forbidden word, but is still textbook GENERIC_AI_WORDING — vague, pastable onto any
   destination, nothing verifiable. This is the pattern the judge most needs to recognize,
   since a word-blocklist alone will miss it.',

    forbidden_words = '["deals","cheap","book now","instant booking","stunning","breathtaking",
"unforgettable","hidden gem","hidden gems","bucket list","world-class","iconic","epic","fun",
"exciting","amazing","discover","explore","package","dream trip","once in a lifetime","vibrant",
"immersive experience","immersive experiences","immerse yourself","seamless journey",
"treasure-trove","glittering","diverse wonders","nestled","tapestry","must-visit","must-see",
"embark on","awaits you","look no further","delve","don''t miss out","limited spots",
"act fast","hurry","last chance","in conclusion"]'::jsonb,

    good_examples = '1. "A bullet train departing Seoul southward delivers you to Gyeongju — ancient capital of the
Silla Kingdom — in under two hours, arriving at a city where royal burial mounds still rise
from the centre of residential streets."

2. "Most travellers have no idea South Korea has one of Asia''s most refined long-distance
cycling networks — colour-coded, riverside, and built for serious riders."

3. "Damyang''s bamboo groves line the path at mid-distance — a distinct microclimate, noticeably
cooler, where the canopy filters light to a grey-green cast."',

    updated_at = now()
WHERE tenant_id = (SELECT tenant_id FROM shared.tenants WHERE slug = 'aa_internal')
  AND brand_name = 'default'
  AND is_active = true;

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES ('104', now(),
    'AA-404 F9 fix #1: aa_internal real shared.tenant_brand_rules content on the ''default'' '
    'row (system_prompt/style_guide/forbidden_words/good_examples, Nghiep-approved) + archived '
    '+ removed the 6 mis-attached demo-tenant rows (WildKind/Terra x2/Trail Pulse/Atlas & Hearth)')
ON CONFLICT (version) DO NOTHING;

COMMIT;
