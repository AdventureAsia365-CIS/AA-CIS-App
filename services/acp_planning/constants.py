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

# AA-448 — shared HIGH/MED/LOW -> numeric mapping. Was inline in quarter.py's
# compute_quarter_plan() (one dict literal, only used for `distinctiveness`); pulled out here
# so the SAME 3-bucket numeric ladder is reused for the new `dfs_relevance` term (AA-448,
# services/acp_shared/dfs_relevance.py) instead of that formula inventing its own scale — a
# "MED" atom and a "MED" tour-demand signal now contribute the same fractional weight.
SIGNAL_SCORE_MAP = {"HIGH": 1.0, "MED": 0.5, "LOW": 0.1}

# AA-448 — N5 quarter-plan scoring weights. Round 1 took this from 3 terms (runway_fit/richness/
# distinctiveness, original 0.4/0.3/0.3) to 4 (added dfs_relevance, ADR-2026-038 §0.4 — ADD not
# replace runway_fit, see docs/implementation-notes/AA-448-t7-content-planning.md "Decision 3"
# for the reasoning). Round 6 adds a 5th term, `engagement_adjustment` (real post-publish
# feedback, confidence-gated atom.weight rolled up to trip level — a NEW extension beyond
# aa-marketing-v2's own Module H, which never fed back into quarter-level trip selection at all,
# see that same file's "round 6" section) — done ONCE, in the same pass as this comment, per
# Nghiep's explicit instruction not to re-derive the weights a second time after dfs_relevance
# had already shipped. runway_fit stays the largest single term (the most concrete, deterministic
# signal); richness/distinctiveness equal at 0.20 each; dfs_relevance and engagement_adjustment
# both at 0.15 — smaller than the 3 established terms since both are newer/less-calibrated
# signals (dfs_relevance's thresholds are explicitly "chưa hiệu chỉnh" per the ADR; engagement
# feedback is sparse/confidence-gated early on, most trips will score the neutral 0.5 midpoint
# for a while). Kept named/importable (not inline) so `_score_reason()` and
# `compute_quarter_plan()` share one source of truth and can't drift out of sync.
QUARTER_SCORE_WEIGHTS = {
    "runway_fit": 0.30,
    "richness": 0.20,
    "distinctiveness": 0.20,
    "dfs_relevance": 0.15,
    "engagement_adjustment": 0.15,
}

# AA-448 round 6 — feedback loop (services/acp_shared/content_metrics.py). Confidence gate
# reused VERBATIM from aa-marketing-v2's aamc/config.py::CONFIDENCE_ATOM_MIN_POSTS — this part
# IS the original design, not an extension (see implementation notes "round 6" for the
# boundary: the gate threshold is ported, the per-post scoring formula and the trip-level
# reallocation suggestion built on top of it are new).
CONFIDENCE_ATOM_MIN_POSTS = 3

# Magnitude cap on tour_atoms.weight after a rollup — same bounds aamc's own rollup_atoms() uses
# (max(0.25, min(2.0, ...))). 1.0 stays the neutral/no-adjustment-yet value.
ATOM_WEIGHT_MIN = 0.25
ATOM_WEIGHT_MAX = 2.0

# NEW (not in aamc — travel content here has no capture_rate/engaged_time field to reuse):
# "typical" engagement rate an average post is assumed to get, used to CENTER the per-post score
# before it shifts atom.weight up/down from 1.0. A post at exactly this rate leaves the atom's
# weight unchanged; above it nudges weight up, below nudges down. Self-chosen, uncalibrated
# against real data yet (same class of caveat as DFS_RELEVANCE_THRESHOLDS) — kept as a named
# constant specifically so it's easy to tune later without touching the rollup formula's code.
ENGAGEMENT_RATE_BASELINE = 0.05
