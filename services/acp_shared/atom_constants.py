"""
Atom decomposition thresholds — ACP v2 (AA-302/AA-299).

Values ported verbatim from aamc/config.py (aa-marketing-v2 research build,
AA-299 STEP 0 diff against production). Shared by both the inline (<100
tours) and future Batch (>=100 tours) atom-decompose paths in
api/routers/v1_atoms.py — do not redefine these elsewhere.
"""

THIN_TRIP_ATOM_MIN = 5          # <5 atoms ⇒ thin-trip rule (§2.2)
CURATION_MANDATORY_BELOW = 8    # <8 atoms ⇒ mandatory curation pass
ATOM_DENSITY_WORDS = 300        # ≥1 atom/fact cite per this many words (F2; spec: 200–300)
