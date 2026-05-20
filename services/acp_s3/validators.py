"""
5 deterministic validators for S3 calendar output.
All return bool. On failure the handler collects errors but does NOT block the run.
"""
import re

_COUNTRY_NAMES = {
    "afghanistan", "albania", "algeria", "andorra", "angola", "argentina",
    "armenia", "australia", "austria", "azerbaijan", "bahrain", "bangladesh",
    "belarus", "belgium", "belize", "benin", "bhutan", "bolivia", "bosnia",
    "botswana", "brazil", "brunei", "bulgaria", "burkina faso", "burundi",
    "cambodia", "cameroon", "canada", "chad", "chile", "china", "colombia",
    "congo", "costa rica", "croatia", "cuba", "cyprus", "czech republic",
    "denmark", "djibouti", "ecuador", "egypt", "el salvador", "ethiopia",
    "fiji", "finland", "france", "georgia", "germany", "ghana", "greece",
    "guatemala", "guinea", "haiti", "honduras", "hungary", "india",
    "indonesia", "iran", "iraq", "ireland", "israel", "italy", "ivory coast",
    "jamaica", "japan", "jordan", "kazakhstan", "kenya", "korea", "kuwait",
    "kyrgyzstan", "laos", "latvia", "lebanon", "liberia", "libya",
    "liechtenstein", "lithuania", "luxembourg", "madagascar", "malawi",
    "malaysia", "maldives", "mali", "malta", "mauritania", "mauritius",
    "mexico", "moldova", "monaco", "mongolia", "montenegro", "morocco",
    "mozambique", "myanmar", "namibia", "nepal", "netherlands", "new zealand",
    "nicaragua", "niger", "nigeria", "north korea", "norway", "oman",
    "pakistan", "panama", "paraguay", "peru", "philippines", "poland",
    "portugal", "qatar", "romania", "russia", "rwanda", "saudi arabia",
    "senegal", "serbia", "sierra leone", "singapore", "slovakia", "slovenia",
    "somalia", "south africa", "south korea", "spain", "sri lanka", "sudan",
    "sweden", "switzerland", "syria", "taiwan", "tajikistan", "tanzania",
    "thailand", "togo", "tunisia", "turkey", "turkmenistan", "uganda",
    "ukraine", "united arab emirates", "united kingdom", "united states",
    "uruguay", "uzbekistan", "venezuela", "vietnam", "yemen", "zambia",
    "zimbabwe",
}


def check_week_structure(markdown: str) -> bool:
    return bool(re.search(r"### Week \d+", markdown))


def check_primary_keyword_labels(markdown: str) -> bool:
    return "Primary Keyword:" in markdown


def check_lead_magnet_cta(markdown: str) -> bool:
    return "Lead Magnet CTA:" in markdown


def check_no_banned_country(posts: list, active_country: str) -> bool:
    active = active_country.lower().strip()
    for post in posts:
        kw = post.get("primary_keyword", "").lower()
        for country in _COUNTRY_NAMES:
            if country == active:
                continue
            if country in kw:
                return False
    return True


def check_anti_cannibalization(posts: list, s1_keywords_used: list) -> bool:
    used = {k.lower().strip() for k in s1_keywords_used}
    for post in posts:
        kw = post.get("primary_keyword", "").lower().strip()
        if kw in used:
            return False
    return True


def run_all(markdown: str, posts: list, active_country: str, s1_keywords_used: list) -> list[str]:
    """Run all 5 checks. Returns list of error strings (empty = all passed)."""
    errors = []
    if not check_week_structure(markdown):
        errors.append("week_structure: '### Week N' heading not found in calendar")
    if not check_primary_keyword_labels(markdown):
        errors.append("primary_keyword_labels: 'Primary Keyword:' missing from calendar")
    if not check_lead_magnet_cta(markdown):
        errors.append("lead_magnet_cta: 'Lead Magnet CTA:' not found in calendar")
    if not check_no_banned_country(posts, active_country):
        errors.append(f"banned_country: primary_keyword references a country other than '{active_country}'")
    if not check_anti_cannibalization(posts, s1_keywords_used):
        errors.append("anti_cannibalization: primary_keyword overlaps with s1_keywords_used")
    return errors
