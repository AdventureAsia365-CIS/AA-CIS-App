import re

import structlog

logger = structlog.get_logger()

# AA-353: line-anchored so a day-count number mentioned mid-line never matches — e.g. "Easy Day 82
# km Tarmac Road" as a day's OWN title text must not be misread as a "Day 82" marker (AA-346's own
# regression case). Only a line that STARTS with "Day <n>" (optionally "Day #3", "Day3", etc.) counts.
_DAY_MARKER_RE = re.compile(r"^\s*day\s*#?\s*(\d{1,3})\b[:\-–—]?\s*", re.IGNORECASE)


def _estimate_day_count(duration_hint: str) -> int:
    """First integer found in a free-text duration string ("12 Days", "7D/6N") — 0 if none."""
    if not duration_hint:
        return 0
    m = re.search(r"(\d{1,3})", str(duration_hint))
    return int(m.group(1)) if m else 0


def parse_source_day_word_counts(itineraries_raw: str, duration_hint: str = "") -> dict:
    """AA-353: per-day word count (+ text) of the SOURCE itinerary, computed in code (not by the
    LLM — unlike AA-352's itinerary_day, this is a prompt INPUT needed before the model call, not
    an extraction target, so delegating to the model isn't an option here).

    Loose, line-anchored "Day N" boundary parser. Falls back to an even split of the total word
    count across an estimated day count (from ``duration_hint``) when fewer than 2 day-markers are
    found — logged, never silent, since a fallback means every day gets the SAME target ratio
    range, defeating the point of this feature for that one tour. In the fallback case, day_text
    maps every day to the full (unsegmented) source, since no per-day boundary could be found.

    Returns {"day_word_counts": {day_num: word_count}, "day_text": {day_num: text},
    "used_fallback": bool}.
    """
    text = itineraries_raw or ""
    lines = text.splitlines()
    matches = []  # (day_num, line_idx)
    for idx, line in enumerate(lines):
        m = _DAY_MARKER_RE.match(line.strip())
        if m:
            matches.append((int(m.group(1)), idx))

    if len(matches) < 2:
        total_words = len(text.split())
        est_days = _estimate_day_count(duration_hint) or 1
        per_day = max(1, round(total_words / est_days))
        logger.warning("itinerary_day_parse_fallback", markers_found=len(matches),
                        estimated_days=est_days, total_words=total_words)
        return {
            "day_word_counts": {d: per_day for d in range(1, est_days + 1)},
            "day_text": {d: text for d in range(1, est_days + 1)},
            "used_fallback": True,
        }

    day_word_counts = {}
    day_text = {}
    for i, (day_num, line_idx) in enumerate(matches):
        end = matches[i + 1][1] if i + 1 < len(matches) else len(lines)
        segment_lines = list(lines[line_idx:end])
        # strip the "Day N —" marker prefix off the first line so it isn't double-counted
        segment_lines[0] = _DAY_MARKER_RE.sub("", segment_lines[0].strip(), count=1)
        segment_text = " ".join(segment_lines).strip()
        day_word_counts[day_num] = max(len(segment_text.split()), 1)
        day_text[day_num] = segment_text
    return {"day_word_counts": day_word_counts, "day_text": day_text, "used_fallback": False}


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
5. Itineraries: rewrite each day in the client's brand voice using the style guide, as the
   structured "itineraries" array described in OUTPUT JSON FORMAT below — one object per source
   day, in day order. Do not merge, split, invent, or drop days.
   Each day title MUST name the place and/or the primary activity of that day.
   GOOD: "Trekking to Sapa Valley Villages"
   GOOD: "Mae Taeng Valley Cycling: Waterfalls, Farmland & Temple"
   FORBIDDEN generic titles: "Exploration", "Free Day", "Arrival Day", "Departure",
   "Transfer" as the whole title — these name no place or activity and trip
   ITINERARY_DAY_TITLE_GENERIC.
   Preserve all factual details (day numbers, named places, activities).
   Do not invent days or activities not present in the source.
   NEVER invent meal names (breakfast, lunch, dinner) or clock-times
   (e.g. "7:00 AM departure") unless they appear explicitly in the source
   itinerary — fabricating them is a PRODUCT_TRUTH_RISK. Describe activities
   by their sequence within the day, not by manufactured times or meals.
   LENGTH PER DAY: see PER-DAY SOURCE LENGTH below. Write each day's body in proportion to
   THAT day's own source length — a day with a lot of source detail should read fuller than a
   simple transit/rest day. Do NOT normalize every day to the same length regardless of source;
   that is the single most common mistake on this task.
6. Do not make factual claims you cannot verify from the source data
7. seo_meta must NOT contain budget travel language: "hostel", "budget", "public transport",
   "cheap", "backpacker", "dorm". The AA audience is $250k+ — write accordingly.
8. SEO META LENGTH: seo_meta MUST be 140–155 characters — count carefully, NEVER under 140.
   It must be one complete sentence ending in a period. If a draft is under 140, expand it
   with concrete, relevant detail (place, activity, audience) — do NOT pad with filler words.

Output ONLY valid JSON. No preamble, no markdown, no explanation.
"""


_SUBTITLE_INSTRUCTIONS = {
    "standard": "concrete subtitle: route, duration, and 1-2 key landmarks or experiences",
    "seo":      (
        "SEO-optimised: lead with primary keyword (country + activity type),"
        " include duration — e.g. 'South Korea Cycling Tour: 9 Days, Seoul to East Sea'"
    ),
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
    # AA-314: tour['highlights'] is a list (parsed by the caller) — join it the same
    # way seo_keywords/paa below turn a list into readable prompt text, instead of
    # interpolating the list's Python repr straight into the prompt.
    highlights_raw = tour.get('highlights') or []
    highlights_text = ', '.join(highlights_raw) if isinstance(highlights_raw, list) else highlights_raw

    # AA-353: per-day source word counts, computed in code — see parse_source_day_word_counts
    # docstring for why this can't be an LLM extraction step the way AA-352's itinerary_day is.
    _day_counts = parse_source_day_word_counts(itineraries_raw, tour.get('duration'))
    _fallback_note = (
        " (source had no clear per-day markers — estimated evenly; treat as a rough guide)"
        if _day_counts["used_fallback"] else ""
    )
    per_day_length_text = "\n".join(
        f"Day {d}: {w} words" for d, w in sorted(_day_counts["day_word_counts"].items())
    ) + _fallback_note

    return f"""Rewrite the following tour content for Adventure Asia brand.
{few_shot_text}
TOUR DATA:
- Name: {tour.get('name')}
- Country: {tour.get('country')}
- Duration: {tour.get('duration')}
- Summary: {tour.get('summary')}
- Description: {tour.get('description')}
- Highlights: {highlights_text}
- Itineraries: {itineraries_raw}
- Inclusions: {tour.get('inclusions')}
- Exclusions: {tour.get('exclusions')}

PER-DAY SOURCE LENGTH (word count of the source above, one per day — use as the basis for each
day's target length per rule 5; aim roughly 0.7x-1.3x of that day's number, not a fixed length
applied to every day):
{per_day_length_text}

SEO CONTEXT:
- Target keywords: {', '.join(seo_keywords[:5])}
- People also ask: {'; '.join(paa[:3])}

CRITICAL LENGTH REQUIREMENT — seo_meta: aim 145–152 characters, hard band 140–155, a complete
sentence ending with a period. Under 140 is rejected. Count characters before finalizing.

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
  "itineraries": [
    {{"day": 1, "title": "Names the place/activity, never generic (see rule 5)",
      "body": "This day's prose, brand voice, length per PER-DAY SOURCE LENGTH above (rule 5)."}},
    "... one object per source day, in day order, matching PER-DAY SOURCE LENGTH above exactly —
    do not add, merge, or drop days"
  ],
  "seo_title": "SEO title — MUST be under 60 chars",
  "seo_meta": "SEO meta description — MUST be 140-155 characters (NEVER under 140), a complete
    sentence ending in a period, opening with a concrete editorial clause. GOOD example (148 chars):
    'This private Sri Lanka journey covers Sigiriya, Kandy and Yala with unhurried pacing, expert
    local guides and comfortable transfers throughout the route.'",
  "trip_type": "cultural|adventure|wellness|culinary|wildlife|trekking|festival|river_journey"
}}"""
