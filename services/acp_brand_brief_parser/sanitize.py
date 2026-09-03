"""AA-487: sanitize tenant-supplied brand brief text before it becomes system_prompt.

Threat model (see Linear AA-487 / AA-279 / AA-478 STEP0): a tenant's own DOCX brand brief is
parsed by prefix-matching only (parser.py has no LLM re-interpretation step), so whatever a
tenant types is kept byte-for-byte. `build_system_prompt()` then f-string-interpolates that text
straight into a `system_prompt` that gets persisted and replayed on every future LLM call for
that tenant (T2 rewrite, F9 judge rubric, T8 brand_audience).

The redact/truncate logic here is intentionally duplicated (not imported) from
`shared.validators.prompt_sanitize`, which the SAME fix applies to
`api/routers/admin_pipeline.py::update_brand_identity()` — the tenant portal's direct "edit
brand voice" form, which writes to the exact same `system_prompt` column with no parsing step at
all (see that module's docstring). This Lambda is packaged by `scripts/package_lambdas.sh`'s
`package_brand_brief_parser()` as a FLAT zip of only `services/acp_brand_brief_parser/*.py`
(no `shared/`, confirmed while building this fix — see that script's own AA-78 packaging-bug
comment for the exact history) — importing `shared.*` here would work in tests (repo checkout on
sys.path) but raise `ModuleNotFoundError` in the real deployed Lambda. Keep both copies in sync
by hand if the injection-pattern list changes; this is a small, stable regex list, not worth a
packaging change to de-duplicate.
"""
import re

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+|any\s+)?(previous|prior|above|the\s+above)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+|any\s+)?(previous|prior|above|the\s+above)", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+|any\s+)?(previous|prior|above|everything)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(a|an|the)\b", re.IGNORECASE),
    re.compile(r"act\s+as\s+(if\s+you\s+are\s+)?(a|an|the)\b", re.IGNORECASE),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\b", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"system\s*(prompt)?\s*:", re.IGNORECASE),
    re.compile(
        r"\b(reveal|print|show|output|repeat)\s+(your|the)\s+(system\s+)?(prompt|instructions)\b",
        re.IGNORECASE,
    ),
    re.compile(r"</?(system|assistant|user)>", re.IGNORECASE),
    re.compile(r"\[/?(system|inst|instructions)\]", re.IGNORECASE),
    re.compile(r"<\|.*?\|>"),  # fake special/control tokens (e.g. <|im_start|>)
]

_REDACTION = "[redacted]"

MAX_SHORT_FIELD_LEN = 200   # brand_type, core_idea, customer_segment, customer_mindset, single words
MAX_LONG_FIELD_LEN = 300    # style_guide — kept at the pre-existing 300 so behavior doesn't regress


def _strip_control_chars(text: str) -> str:
    return "".join(ch for ch in text if ch in "\n\t" or ch.isprintable())


def sanitize_text(text: str | None, max_len: int) -> str | None:
    """Sanitize one free-text field: strip control chars, redact known injection shapes,
    collapse whitespace, truncate. Returns None unchanged (absent field stays absent)."""
    if text is None:
        return None
    cleaned = _strip_control_chars(text)
    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub(_REDACTION, cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    return cleaned[:max_len]


def sanitize_list(items: list[str], max_len: int, max_items: int = 20) -> list[str]:
    out = []
    for item in items[:max_items]:
        sanitized = sanitize_text(item, max_len)
        if sanitized:
            out.append(sanitized)
    return out


def sanitize_parsed_brief(parsed: "ParsedBrief") -> "ParsedBrief":  # noqa: F821 (models.ParsedBrief)
    """Apply sanitize_text/sanitize_list to every tenant-authored free-text field of a
    ParsedBrief. Single choke point — call once, right where parse_docx() builds the result,
    so every downstream consumer (build_system_prompt(), the DB snapshot in db.py, any future
    reader of ParsedBrief) sees already-sanitized text without needing its own copy of this
    logic."""
    from models import ParsedBrief, VoiceExamples  # local import: avoids a hard dependency for
    # callers that only need sanitize_text/sanitize_list (e.g. unit tests on the regexes alone)

    voice = parsed.voice_examples
    return ParsedBrief(
        brand_name=sanitize_text(parsed.brand_name, MAX_SHORT_FIELD_LEN) or "",
        brand_type=sanitize_text(parsed.brand_type, MAX_SHORT_FIELD_LEN),
        core_idea=sanitize_text(parsed.core_idea, MAX_SHORT_FIELD_LEN),
        target_markets=sanitize_list(parsed.target_markets, MAX_SHORT_FIELD_LEN, max_items=10),
        customer_segment=sanitize_text(parsed.customer_segment, MAX_SHORT_FIELD_LEN),
        customer_mindset=sanitize_text(parsed.customer_mindset, MAX_SHORT_FIELD_LEN),
        voice_examples=VoiceExamples(
            tone_traits=sanitize_list(voice.tone_traits, MAX_SHORT_FIELD_LEN, max_items=10),
            good_example=sanitize_text(voice.good_example, MAX_LONG_FIELD_LEN),
            preferred=sanitize_list(voice.preferred, MAX_SHORT_FIELD_LEN, max_items=10),
            should_not_write=sanitize_list(voice.should_not_write, MAX_SHORT_FIELD_LEN, max_items=20),
        ),
        style_guide=sanitize_text(parsed.style_guide, MAX_LONG_FIELD_LEN),
        forbidden_words=sanitize_list(parsed.forbidden_words, MAX_SHORT_FIELD_LEN, max_items=20),
        confidence=parsed.confidence,
    )
