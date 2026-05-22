SYSTEM_PROMPT = """You are a travel content editor for Adventure Asia,
a private-travel brand for senior professionals (40-60) from US/UK/AUS markets.

BRAND VOICE:
- Calm, factual, editorial. NOT salesy. NOT generic.
- Write like a knowledgeable editor, not a marketing copywriter.
- Tone: Condé Nast Traveller, not TripAdvisor.

STRICT RULES:
1. NEVER use these words: curated, pristine, refined, tailored, bespoke,
   stunning, breathtaking, magical, paradise, luxury, cheap, deal, discount, book now
2. Tour name (aa_name): Rewrite into Adventure Asia brand voice — evocative but specific.
   Good: "South Korea: Temple, Trail & Peninsula — 12 Days"
   Good: "Sri Lanka by Rail and Rickshaw — 10 Days"
   Forbidden in name: "Exploring", "Discover", "Amazing", "Epic", generic verbs.
   The rewritten name must still clearly identify the destination and format.
3. Subtitle: must include concrete specifics (route, duration, or defining characteristic) — NOT vague descriptors
4. Highlights: each must name a specific place, altitude, or activity — never generic ("see beautiful views")
5. Itineraries: rewrite each day in the client's brand voice using the style guide.
   Preserve all factual details (day numbers, named places, activities).
   Do not invent days or activities not present in the source.
6. Do not make factual claims you cannot verify from the source data
7. seo_meta must NOT contain budget travel language: "hostel", "budget", "public transport",
   "cheap", "backpacker", "dorm". The AA audience is $250k+ — write accordingly.

Output ONLY valid JSON. No preamble, no markdown, no explanation.
"""


_SUBTITLE_INSTRUCTIONS = {
    "standard": "concrete subtitle: route, duration, and 1-2 key landmarks or experiences",
    "seo":      "SEO-optimised: lead with primary keyword (country + activity type), include duration — e.g. 'South Korea Cycling Tour: 9 Days, Seoul to East Sea'",
    "concise":  "concise value proposition — max 12 words, lead with country and defining activity",
}


def build_rewrite_prompt(tour: dict, seo: dict, few_shots: list[dict] = None,
                         subtitle_focus: str = "standard") -> str:
    few_shot_text = ""
    if few_shots:
        examples = "\n\n".join([
            f"EXAMPLE {i+1}:\nINPUT: {f['input']}\nOUTPUT: {f['output']}"
            for i, f in enumerate(few_shots[:3])
        ])
        few_shot_text = f"\n\nEXAMPLES FOR REFERENCE:\n{examples}\n"

    seo_keywords = seo.get("keywords", {}).get("top_keywords", [])
    paa          = seo.get("people_also_ask", [])

    itineraries_raw = tour.get('itineraries') or tour.get('itinerary') or ""

    return f"""Rewrite the following tour content for Adventure Asia brand.
{few_shot_text}
TOUR DATA:
- Name: {tour.get('name')}
- Country: {tour.get('country')}
- Duration: {tour.get('duration')}
- Summary: {tour.get('summary')}
- Description: {tour.get('description')}
- Highlights: {tour.get('highlights')}
- Itineraries: {itineraries_raw}
- Inclusions: {tour.get('inclusions')}
- Exclusions: {tour.get('exclusions')}

SEO CONTEXT:
- Target keywords: {', '.join(seo_keywords[:5])}
- People also ask: {'; '.join(paa[:3])}

OUTPUT JSON FORMAT:
{{
  "name": "Rewrite in AA brand voice — evocative + specific. See STRICT RULES 2.",
  "subtitle": "{_SUBTITLE_INSTRUCTIONS.get(subtitle_focus, _SUBTITLE_INSTRUCTIONS['standard'])}",
  "summary": "Factual editorial prose, specific to this tour. No generic openers. No sentence limit.",
  "highlights": [
    "Specific activity at Named Location (include altitude if trekking)",
    "Specific activity at Named Location",
    "Add as many highlights as the source supports — minimum 3, no maximum"
  ],
  "itineraries": "Rewrite in brand voice. Keep facts: day numbers, places, activities. Do not add or remove days.",
  "seo_title": "SEO title — MUST be under 70 chars",
  "seo_meta": "SEO meta description — MUST be under 170 chars, opens with a concrete editorial sentence",
  "trip_type": "cultural|adventure|wellness|culinary|wildlife|trekking|festival|river_journey"
}}"""
