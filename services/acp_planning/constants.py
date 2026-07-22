"""
Runway/quarter/allocator thresholds — N4/N5/N6 (AA-301).

Values ported verbatim from aamc/config.py (aa-marketing-v2 research build,
docs/AI-gent-for automation works/aa-marketing-v2), same porting convention
already used by services/acp_shared/atom_constants.py (AA-299/302).

THIN_TRIP_ATOM_MIN lives in services.acp_shared.atom_constants (AA-299/302,
shared by the N0-N2 decompose gate) — import it from there, do not redefine
it here.
"""

RUNWAY_OFFSETS_MONTHS = {
    "long_haul": (3, 6),         # EU/US/AU -> Asia
    "family_extended": (6, 12),
    "short_haul": (0.5, 2),      # intra-Asia, 2-8 weeks
}
LONG_HAUL_MARKETS = {"US", "USA", "UK", "GB", "DE", "FR", "NL", "AU", "CA", "ES", "IT", "SE", "CH", "EU"}

FRAMEWORK_TABLE = {
    ("TOFU", "blog"): {"framework": "hub", "faq": True, "faq_n": (4, 8)},
    ("MOFU", "blog"): {"framework": "PAS", "faq": True, "faq_n": (4, 6)},
    ("BOFU", "blog"): {"framework": "AIDA", "faq": False, "faq_n": (0, 0)},
    ("ANY", "facebook"): {"framework": "hook_story_cta", "faq": False, "words": (80, 150)},
    ("ANY", "tiktok"): {"framework": "hook_beats_payoff", "faq": False},
    ("ANY", "email"): {"framework": "reader_as_hero", "faq": False},
}

SLOT_MIX = {"evergreen": 0.65, "campaign": 0.25, "reactive_held_empty": 0.10}
ATOM_COOLDOWN_WEEKS = 6

# B5 fix (N5) — a thin trip's content share is capped at this fraction, freed
# share redistributed proportionally to non-thin trips. Not specified in the
# original issue text (only "cap thin trip's share" is mandated) — 0.15 is a
# self-chosen default, see AA-301 implementation notes.
# TẠM THỜI — chưa có xác nhận chính thức từ Ms. Thư. Xem AA-319.
# KHÔNG liên quan tới "Sapa 0.15" trong research Session 104 (đó là share
# tự tính của 1 destination bình thường, không phải ngưỡng cap chủ định
# cho tour thin) — trùng số ngẫu nhiên, đừng nhầm lẫn khi đọc lại.
THIN_TRIP_MAX_SHARE = 0.15
