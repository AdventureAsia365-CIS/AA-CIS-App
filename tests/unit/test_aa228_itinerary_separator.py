"""AA-228: validate_node normalizes day-title separators to one canonical form
("Day N — title" + blank line between days) across model tiers, no leading blank line.
validate_node is rule-based (no LLM) so it is called directly.
"""
import re
from services.content_generation.graph import validate_node

def _state(itin):
    return {
        "generated": {
            "name": "Korea Peninsula Journey",
            "subtitle": "A refined private route, Seoul to Jeju",
            "summary": "A discreet private journey across the peninsula with unhurried pacing.",
            "highlights": ["Inwangsan ridge walk above the palace quarter"],
            "itineraries": itin,
            "seo_title": "Korea Peninsula Private Journey",
            "seo_meta": "A discreet private Korea journey from Seoul's palace quarter to Jeju's coast with unhurried pacing and expert local guides throughout.",
        },
        "tour": {"country": "South Korea", "duration": "12 days"},
        "seo": {},
    }

def _itin_out(itin):
    return validate_node(_state(itin))["generated"]["itineraries"]

# Real Haiku shape: "Day N -- title | prose ... || Day N+1 -- ..."
HAIKU = ("Day 1 -- Seoul Arrival | Arrive and settle into the city's rhythms. "
         "|| Day 2 -- Inwangsan Hike and Gyeongbokgung Palace | Begin before rush hour with a climb.")
# Real Haiku shape with days run together (no || separator):
HAIKU_RUNON = ("Day 1 -- Seoul Arrival | Touch down and hit the streets. "
               "Day 2 -- Inwangsan Hike | First light ascent of Inwangsan.")
# Sonnet/GPT shape: already "Day N — title" + newline; must pass through intact.
SONNET = ("Day 1 — Seoul Arrival and First Light\nArrive and settle in.\n\n"
          "Day 2 — Inwangsan Hike\nBegin before rush hour.")

def test_haiku_dashes_and_pipes_normalized():
    out = _itin_out(HAIKU)
    assert "--" not in out
    assert "|" not in out
    assert "Day 1 — Seoul Arrival" in out
    assert "Day 2 — Inwangsan Hike and Gyeongbokgung Palace" in out

def test_no_leading_blank_line():
    for itin in (HAIKU, HAIKU_RUNON, SONNET):
        out = _itin_out(itin)
        assert not out.startswith("\n"), f"leading newline in: {out[:20]!r}"

def test_all_day_markers_use_em_dash():
    out = _itin_out(HAIKU)
    markers = re.findall(r"Day\s+\d+\s*(.)", out)
    assert markers and all(m == "—" for m in markers), markers

def test_runon_days_get_separated():
    out = _itin_out(HAIKU_RUNON)
    # both days present as em-dash markers
    assert len(re.findall(r"Day\s+\d+\s+—", out)) == 2

def test_sonnet_passes_through_clean():
    out = _itin_out(SONNET)
    assert "Day 1 — Seoul Arrival and First Light" in out
    assert "Day 2 — Inwangsan Hike" in out
    assert not out.startswith("\n")
    assert "--" not in out and "|" not in out
