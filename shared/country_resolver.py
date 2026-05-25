"""
Country resolution: raw Excel value → canonical country name.
Priority: 1) normalize raw value against master list  2) extract from filename  3) None
"""

import re

COUNTRY_MASTER = {
    "Japan":         ["JAPAN", "JAPANESE"],
    "Sri Lanka":     ["SRI LANKA", "SRILANKA", "LKA"],
    "South Korea":   ["SOUTH KOREA", "KOREA", "KOR", "REPUBLIC OF KOREA"],
    "Vietnam":       ["VIETNAM", "VIET NAM", "VNM"],
    "Thailand":      ["THAILAND", "THAI"],
    "Bhutan":        ["BHUTAN", "BTN"],
    "Nepal":         ["NEPAL", "NPL"],
    "India":         ["INDIA", "IND"],
    "Cambodia":      ["CAMBODIA", "KHMER", "KHM"],
    "Laos":          ["LAOS", "LAO", "LAO PDR"],
    "Myanmar":       ["MYANMAR", "BURMA", "MMR"],
    "Indonesia":     ["INDONESIA", "IDN", "BALI"],
    "Malaysia":      ["MALAYSIA", "MYS"],
    "Singapore":     ["SINGAPORE", "SGP"],
    "Philippines":   ["PHILIPPINES", "PHIL", "PHL"],
    "Mongolia":      ["MONGOLIA", "MNG"],
    "China":         ["CHINA", "CHN", "PRC"],
    "Tibet":         ["TIBET"],
    "Taiwan":        ["TAIWAN", "TWN"],
    "Maldives":      ["MALDIVES", "MDV"],
}

# alias (uppercase) → canonical name
_ALIAS_MAP: dict[str, str] = {}
for _canonical, _aliases in COUNTRY_MASTER.items():
    _ALIAS_MAP[_canonical.upper()] = _canonical
    for _alias in _aliases:
        _ALIAS_MAP[_alias] = _canonical


def resolve_country(raw_value: str | None, filename: str | None = None) -> str | None:
    """
    Resolve raw country value to canonical country name.
    Falls back to filename parsing if raw_value is absent or unrecognised.
    """
    if raw_value:
        normalized = raw_value.strip().upper()
        if normalized in _ALIAS_MAP:
            return _ALIAS_MAP[normalized]

    if filename:
        # Strip path and extension; normalise separators to spaces
        fname = filename.split("/")[-1]
        fname = fname.rsplit(".", 1)[0]
        fname_upper = fname.upper().replace("_", " ").replace("-", " ")
        # Sort by length descending so "SOUTH KOREA" matches before "KOREA"
        for alias in sorted(_ALIAS_MAP, key=len, reverse=True):
            if re.search(r'\b' + re.escape(alias) + r'\b', fname_upper):
                return _ALIAS_MAP[alias]

    return None
