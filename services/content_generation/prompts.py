SYSTEM_PROMPT = """You are an expert travel content writer for Adventure Asia, 
a luxury travel brand targeting senior professionals (40-60) from US/UK/AUS markets.
Brand voice: Calm, refined, curated. NOT salesy.
Use words: Designed/Curated/Refined/Tailored/Journey
Avoid words: Deals/Cheap/Book Now/Instant booking

Output ONLY valid JSON. No preamble, no markdown.
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

    return f"""Rewrite the following tour content for Adventure Asia brand.
{few_shot_text}
TOUR DATA:
- Name: {tour.get('name')}
- Country: {tour.get('country')}
- Duration: {tour.get('duration')}
- Summary: {tour.get('summary')}
- Description: {tour.get('description')}
- Highlights: {tour.get('highlights')}
- Inclusions: {tour.get('inclusions')}
- Exclusions: {tour.get('exclusions')}

SEO CONTEXT:
- Target keywords: {', '.join(seo_keywords[:5])}
- People also ask: {'; '.join(paa[:3])}

OUTPUT JSON FORMAT:
{{
  "name": "refined tour name",
  "subtitle": "one line brand subtitle",
  "summary": "2-3 sentence refined summary",
  "highlights": ["highlight 1", "highlight 2", "highlight 3"],
  "seo_title": "SEO optimized title under 60 chars",
  "seo_meta": "SEO meta description under 160 chars",
  "trip_type": "cultural|adventure|wellness|culinary|wildlife"
}}"""
