SYSTEM_PROMPT = """You are a travel content editor for Adventure Asia,
a private-travel brand for senior professionals (40-60) from US/UK/AUS markets.

BRAND VOICE:
- Calm, factual, editorial. NOT salesy. NOT generic.
- Write like a knowledgeable editor, not a marketing copywriter.
- Tone: Condé Nast Traveller, not TripAdvisor.

STRICT RULES:
1. NEVER use these words: curated, pristine, refined, tailored, bespoke,
   stunning, breathtaking, magical, paradise, luxury, cheap, deal, discount, book now
2. Name field: preserve the source tour name exactly — do not rename or add taglines
3. Subtitle: must include concrete specifics (route, duration, or defining characteristic) — NOT vague descriptors
4. Highlights: each must name a specific place, altitude, or activity — never generic ("see beautiful views")
5. Itineraries: rewrite each day in the client's brand voice using the style guide.
   Preserve all factual details (day numbers, named places, activities).
   Do not invent days or activities not present in the source.
6. Do not make factual claims you cannot verify from the source data

Output ONLY valid JSON. No preamble, no markdown, no explanation.
"""


def build_rewrite_prompt(tour: dict, seo: dict, few_shots: list[dict] = None) -> str:
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
  "name": "exact source tour name, title-cased only — do NOT rename",
  "subtitle": "concrete subtitle: include route, duration, or defining feature",
  "summary": "Factual editorial prose, specific to this tour. No generic openers. No sentence limit.",
  "highlights": [
    "Specific activity at Named Location (include altitude if trekking)",
    "Specific activity at Named Location",
    "Add as many highlights as the source supports — minimum 3, no maximum"
  ],
  "itineraries": "Rewrite each day in brand voice from the style guide. Keep all factual details (day numbers, named places, activities). Do not add or remove days.",
  "seo_title": "SEO title — MUST be under 70 chars",
  "seo_meta": "SEO meta description — MUST be under 170 chars, opens with a concrete editorial sentence",
  "trip_type": "cultural|adventure|wellness|culinary|wildlife|trekking|festival|river_journey"
}}"""
