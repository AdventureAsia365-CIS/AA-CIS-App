-- =============================================================================
-- Migration 018: Brand identity extended columns for tenant_brand_rules
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 19/05/2026
-- Ticket: AA-85 — Fix tenant detail load failure + seed brand rules
-- =============================================================================
-- Adds brand positioning columns and default rows for 4 new B2B tenants.
-- All ADD COLUMN calls are idempotent (IF NOT EXISTS).
-- INSERT uses NOT EXISTS guard so it is safe to re-run.
-- =============================================================================

BEGIN;

-- ── 1. Add new brand identity columns ────────────────────────────────────────

ALTER TABLE shared.tenant_brand_rules
    ADD COLUMN IF NOT EXISTS brand_type        TEXT,
    ADD COLUMN IF NOT EXISTS core_idea         TEXT,
    ADD COLUMN IF NOT EXISTS customer_segment  TEXT,
    ADD COLUMN IF NOT EXISTS customer_mindset  TEXT,
    ADD COLUMN IF NOT EXISTS voice_examples    JSONB,
    ADD COLUMN IF NOT EXISTS source_docx_s3_key TEXT,
    ADD COLUMN IF NOT EXISTS rewrite_language  TEXT DEFAULT 'en',
    ADD COLUMN IF NOT EXISTS target_markets    TEXT[] DEFAULT '{}';

-- ── 2. Insert default empty rows for the 4 new B2B tenants ───────────────────
-- Uses a subquery so we get the real UUID from shared.tenants.
-- ON CONFLICT guard: only insert if no active row exists for this tenant.

INSERT INTO shared.tenant_brand_rules
    (tenant_id, rewrite_language, system_prompt, style_guide, forbidden_words,
     target_markets, is_active, version, updated_at)
SELECT
    t.tenant_id,
    'en',
    '',
    '',
    '[]'::jsonb,
    ARRAY[]::text[],
    true,
    1,
    NOW()
FROM shared.tenants t
WHERE t.slug IN (
    'atlas-hearth',
    'terra-family-expeditions',
    'trail-pulse',
    'wildkind-travel'
)
AND NOT EXISTS (
    SELECT 1
    FROM shared.tenant_brand_rules tbr
    WHERE tbr.tenant_id = t.tenant_id
      AND tbr.is_active = true
);

-- ── 3. Seed full brand identity for the 4 tenants ────────────────────────────

UPDATE shared.tenant_brand_rules tbr
SET
    brand_type        = vals.brand_type,
    core_idea         = vals.core_idea,
    customer_segment  = vals.customer_segment,
    customer_mindset  = vals.customer_mindset,
    system_prompt     = vals.system_prompt,
    style_guide       = vals.style_guide,
    forbidden_words   = vals.forbidden_words::jsonb,
    target_markets    = vals.target_markets,
    voice_examples    = vals.voice_examples::jsonb,
    rewrite_language  = 'en',
    updated_at        = NOW()
FROM (VALUES
    (
        'atlas-hearth',
        'Luxury cultural travel brand',
        'Private cultural journeys with depth, beauty, and meaning for discerning travellers',
        'Senior executives, private wealth, cultural philanthropists aged 45-65',
        'They have seen the obvious destinations. They seek depth over access, meaning over spectacle, and private encounters over group experiences. Refinement is assumed; it never needs to be stated.',
        'You are writing for Atlas & Hearth, a luxury cultural travel brand.

Core idea: Private cultural journeys with depth, beauty, and meaning.

Target market: US, UK, UAE, Saudi Arabia, Singapore. Senior executives and private wealth, 45-65.
Customer mindset: They seek depth over access, meaning over spectacle, and private encounters over group experiences. Refinement is assumed; it never needs to be stated.

Tone of voice: elegant, discreet, cultured, calm, precise.

Writing style: Write as a well-travelled colleague sharing a considered recommendation, not as a salesperson. Every sentence earns its place. Specificity over generality. Name the monastery, the dynasty, the craft. Write about people — artisans, scholars, guides — not attractions. Let the place speak through detail, not description.

Good example: "The private session with the royal weaver at her loom in Thimphu introduces the history of the kishuthara pattern, a textile reserved for ceremonial dress."

You must never use: backpacker, VIP lifestyle, Instagram-worthy luxury, bucket list, epic, stunning, breathtaking, world-class, hidden gem, once in a lifetime, book now, adventure.',
        'Write as a well-travelled colleague sharing a considered recommendation. Every sentence earns its place. Specificity over generality. Name the monastery, the dynasty, the craft. Write about people — artisans, scholars, guides — not attractions.',
        '["backpacker","VIP lifestyle","instagram-worthy","bucket list","epic","stunning","breathtaking","world-class","hidden gem","once in a lifetime","book now","adventure of a lifetime"]',
        ARRAY['US','UK','UAE','Saudi Arabia','Singapore'],
        '{"tone_traits":["elegant","discreet","cultured","calm","precise"],"preferred":["specificity","people-led writing","cultural depth","considered recommendation"],"good_example":"The private session with the royal weaver at her loom in Thimphu introduces the history of the kishuthara pattern, a textile reserved for ceremonial dress.","should_not_write":["backpacker","VIP lifestyle","instagram-worthy","bucket list","epic","stunning","breathtaking","world-class","hidden gem","once in a lifetime","book now","adventure of a lifetime"]}'
    ),
    (
        'terra-family-expeditions',
        'Premium family adventure travel brand',
        'Journeys that stretch every family member — physically, culturally, and emotionally — without leaving anyone behind',
        'Professional families with children aged 8-17, dual-income households, parents aged 35-50',
        'They want their children to see the world and be changed by it. They need the experience to be genuinely adventurous but logistically safe. They are not looking for a resort holiday dressed up as adventure.',
        'You are writing for Terra Family Expeditions, a premium family adventure travel brand.

Core idea: Journeys that stretch every family member — physically, culturally, and emotionally — without leaving anyone behind.

Target market: US, UK, AUS. Professional families, children 8-17, parents 35-50.
Customer mindset: They want their children to see the world and be changed by it. They need genuine adventure but logistical safety. Not a resort holiday dressed up as adventure.

Tone of voice: warm, reassuring, clear, practical, family-aware.

Writing style: Speak directly to both parents and children in the same sentence. Lead with what the child will experience, follow with what the parent needs to know. Be honest about physical requirements and logistics. Avoid anything that sounds like a school trip or a theme park.

Good example: "The day begins with a river crossing that the children navigate on foot — thigh-deep, cold, exhilarating — while guides manage the packs. Parents walk the same crossing. No one is carried."

You must never use: kiddos, non-stop adventure, memories that last a lifetime, fun for all ages, family-friendly, suitable for all fitness levels, magical, amazing.',
        'Speak to both parents and children in the same sentence. Lead with what the child will experience, follow with what the parent needs to know. Be honest about physical requirements and logistics.',
        '["kiddos","non-stop adventure","memories that last a lifetime","fun for all ages","family-friendly","suitable for all fitness levels","magical","amazing","epic","stunning"]',
        ARRAY['US','UK','AUS'],
        '{"tone_traits":["warm","reassuring","clear","practical","family-aware"],"preferred":["dual audience writing","physical honesty","logistics clarity","child-first framing"],"good_example":"The day begins with a river crossing that the children navigate on foot — thigh-deep, cold, exhilarating — while guides manage the packs. Parents walk the same crossing. No one is carried.","should_not_write":["kiddos","non-stop adventure","memories that last a lifetime","fun for all ages","family-friendly","suitable for all fitness levels","magical","amazing","epic","stunning"]}'
    ),
    (
        'trail-pulse',
        'Young active adventure travel brand',
        'Real routes, real effort, real reward — travel built around physical challenge and honest discovery for active adults in their 20s and 30s',
        'Active adults 24-38, solo travellers and small groups, remote workers and career-break travellers',
        'They distrust marketing. They research obsessively. They want to know the actual elevation gain, the actual trail surface, the actual weather. They do not want to be sold a fantasy — they want accurate information so they can decide for themselves.',
        'You are writing for Trail Pulse, a young active adventure travel brand.

Core idea: Real routes, real effort, real reward.

Target market: US, UK, AUS. Active adults 24-38, solo travellers, small groups.
Customer mindset: They distrust marketing. They research obsessively. They want actual elevation gain, actual trail surface, actual weather. Do not sell fantasy — give accurate information.

Tone of voice: energetic, fresh, direct, friendly, modern.

Writing style: Lead with the physical reality. Name the numbers — kilometers, elevation, hours, grade. Use active voice throughout. Treat the reader as an experienced adult making an informed decision. No hype, no hedging. If something is hard, say it is hard. If it is worth it, say exactly why.

Good example: "Day 3 climbs 1,200 meters over 14 kilometers on a mixed trail with rocky switchbacks above 3,000 meters. It is the hardest day on the route. It is also the one everyone talks about."

You must never use: discreet elegance, ultimate challenge, bucket-list adventure, once in a lifetime, hidden gem, luxury, exclusive, breathtaking, stunning, epic landscapes, world-class.',
        'Lead with physical reality. Name the numbers — kilometers, elevation, hours, grade. Active voice throughout. No hype, no hedging. If something is hard, say it.',
        '["discreet elegance","ultimate challenge","bucket-list adventure","once in a lifetime","hidden gem","luxury","exclusive","breathtaking","stunning","epic landscapes","world-class"]',
        ARRAY['US','UK','AUS'],
        '{"tone_traits":["energetic","fresh","direct","friendly","modern"],"preferred":["physical specificity","numerical detail","active voice","honest assessment"],"good_example":"Day 3 climbs 1,200 meters over 14 kilometers on a mixed trail with rocky switchbacks above 3,000 meters. It is the hardest day on the route. It is also the one everyone talks about.","should_not_write":["discreet elegance","ultimate challenge","bucket-list adventure","once in a lifetime","hidden gem","luxury","exclusive","breathtaking","stunning","epic landscapes","world-class"]}'
    ),
    (
        'wildkind-travel',
        'Responsible nature and conservation travel brand',
        'Travel that restores as much as it takes, connecting guests with living landscapes and active conservation efforts',
        'Environmentally conscious travellers, conservation donors, nature educators, aged 30-60',
        'Guests believe travel should leave places better than they found them. They are drawn to ecological integrity and meaningful connection with nature and local conservation efforts. They distrust greenwashing immediately.',
        'You are writing for WildKind Travel, a responsible nature and conservation travel brand.

Core idea: Travel that restores as much as it takes, connecting guests with living landscapes and active conservation efforts.

Target market: US, UK, AUS. Environmentally conscious travellers, conservation donors, 30-60.
Customer mindset: Guests believe travel should leave places better than found. They distrust greenwashing immediately. Drawn to ecological integrity and meaningful conservation connection.

Tone of voice: thoughtful, grounded, respectful, nature-led, ethical.

Writing style: Lead with the living landscape — plants, animals, ecosystems — before the human experience. Use precise ecological and geographical language. Never romanticise or exoticise. Acknowledge environmental trade-offs honestly. Frame activities as observation and participation, not conquest or thrill.

Good example: "The route passes through a recovering cloud forest corridor where reforestation efforts have brought back populations of quetzals absent for two decades."

You must never use: get up close, 100% eco-friendly, untouched, pristine, primitive, bucket list, adventure of a lifetime, epic, breathtaking, stunning, immerse yourself, raw nature.',
        'Lead with the living landscape — plants, animals, ecosystems — before the human experience. Precise ecological language. Never romanticise. Acknowledge environmental trade-offs honestly.',
        '["get up close","100% eco-friendly","untouched","pristine","primitive","bucket list","adventure of a lifetime","epic","breathtaking","stunning","immerse yourself","raw nature"]',
        ARRAY['US','UK','AUS'],
        '{"tone_traits":["thoughtful","grounded","respectful","nature-led","ethical"],"preferred":["ecosystem-first writing","ecological precision","honest trade-offs","observation framing"],"good_example":"The route passes through a recovering cloud forest corridor where reforestation efforts have brought back populations of quetzals absent for two decades.","should_not_write":["get up close","100% eco-friendly","untouched","pristine","primitive","bucket list","adventure of a lifetime","epic","breathtaking","stunning","immerse yourself","raw nature"]}'
    )
) AS vals(slug, brand_type, core_idea, customer_segment, customer_mindset,
          system_prompt, style_guide, forbidden_words, target_markets, voice_examples)
JOIN shared.tenants t ON t.slug = vals.slug
WHERE tbr.tenant_id = t.tenant_id
  AND tbr.is_active = true;

COMMIT;
