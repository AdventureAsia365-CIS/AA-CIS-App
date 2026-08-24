"""services.acp_content_writing — AA-450 T9 (write) + T10-inline (quality gates), written fresh
per ADR-2026-038 §0.5 (same "no reuse of the old pipeline" precedent T7/T8 already followed).

See docs/claude_audit/AA-450-00-step0-t9-content-writing-investigation.md (STEP0),
AA-450-01-t9-t10-retry-loop-investigation.md (Phase 1 architecture), AA-450-02-t10-gate-map.md
(F1-F9 -> T10 mapping) for the full reasoning behind this package's shape.
"""
