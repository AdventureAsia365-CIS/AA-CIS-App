import re
from pathlib import Path

from docx import Document

from .models import ParsedBrief, VoiceExamples

_SECTION_PREFIXES = (
    "brand type:",
    "core idea:",
    "primary markets:",
    "customer segment:",
    "customer mindset:",
    "tone of voice",
    "writing style",
    "good example",
    "should write",
    "should not write",
)

_EXPECTED_SECTIONS = 8  # brand_type, core_idea, markets, segment, mindset, tone, style, should_not_write


def _is_section_header(line: str) -> bool:
    ll = line.lower()
    return any(ll.startswith(p) for p in _SECTION_PREFIXES)


def _after_colon(line: str) -> str:
    idx = line.find(":")
    return line[idx + 1:].strip() if idx != -1 else ""


def _get_lines(doc) -> list[str]:
    lines = []
    for para in doc.paragraphs:
        for part in para.text.split("\n"):
            stripped = part.strip()
            if stripped:
                lines.append(stripped)
    return lines


def _extract_forbidden_words(text: str) -> list[str]:
    # DOCX uses Unicode curly quotes “ / ”, not ASCII "
    _QUOTE_PATTERN = re.compile(r'[“""]([^“”"]+)[”""]')

    result = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        quoted = _QUOTE_PATTERN.findall(line)
        if quoted:
            result.extend(q.strip().rstrip(",") for q in quoted)
        else:
            # "Do not use X or Y language" — extract unquoted key terms
            m = re.match(
                r"do not (?:use|write)\s+(.+?)(?:\s+(?:language|words|wording|clich[eé]s)\b)",
                line,
                re.IGNORECASE,
            )
            if m:
                phrase = m.group(1)
                parts = re.split(r"\s+or\s+|\s+and\s+|,\s*", phrase)
                result.extend(p.strip() for p in parts if p.strip())

    seen: set[str] = set()
    deduped = []
    for w in result:
        key = w.lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(w)
    return deduped


def parse_docx(path: str | Path) -> ParsedBrief:
    doc = Document(str(path))
    lines = _get_lines(doc)

    if not lines:
        return ParsedBrief(
            brand_name="",
            brand_type=None,
            core_idea=None,
            target_markets=[],
            customer_segment=None,
            customer_mindset=None,
            voice_examples=VoiceExamples(tone_traits=[], good_example=None, preferred=[], should_not_write=[]),
            style_guide=None,
            forbidden_words=[],
            confidence=0.0,
        )

    brand_name = lines[0]
    sections_found = 0

    brand_type: str | None = None
    core_idea: str | None = None
    target_markets: list[str] = []
    customer_segment: str | None = None
    customer_mindset: str | None = None
    tone_traits: list[str] = []
    style_guide: str | None = None
    good_example: str | None = None
    preferred: list[str] = []
    should_not_write_lines: list[str] = []

    i = 1
    # Skip API key line (starts with "cis_")
    if i < len(lines) and lines[i].startswith("cis_"):
        i += 1

    while i < len(lines):
        line = lines[i]
        ll = line.lower()

        if ll.startswith("brand type:"):
            brand_type = _after_colon(line) or None
            sections_found += 1
            i += 1

        elif ll.startswith("core idea:"):
            core_idea = _after_colon(line) or None
            sections_found += 1
            i += 1

        elif ll.startswith("primary markets:"):
            value = _after_colon(line)
            if not value and i + 1 < len(lines) and not _is_section_header(lines[i + 1]):
                i += 1
                value = lines[i]
            target_markets = [m.strip() for m in value.split(",") if m.strip()]
            sections_found += 1
            i += 1

        elif ll.startswith("customer segment:"):
            value = _after_colon(line)
            i += 1
            seg_parts = [value] if value else []
            while i < len(lines) and not _is_section_header(lines[i]):
                seg_parts.append(lines[i])
                i += 1
            customer_segment = "\n".join(seg_parts).strip() or None
            sections_found += 1

        elif ll.startswith("customer mindset:"):
            value = _after_colon(line)
            i += 1
            if not value and i < len(lines) and not _is_section_header(lines[i]):
                value = lines[i]
                i += 1
            # Consume remaining content lines for this section
            while i < len(lines) and not _is_section_header(lines[i]):
                i += 1
            customer_mindset = value or None
            sections_found += 1

        elif ll.startswith("tone of voice"):
            sections_found += 1
            i += 1
            while i < len(lines) and not _is_section_header(lines[i]):
                tone_traits.append(lines[i])
                i += 1

        elif ll.startswith("writing style"):
            sections_found += 1
            i += 1
            parts = []
            while i < len(lines) and not _is_section_header(lines[i]):
                parts.append(lines[i])
                i += 1
            style_guide = "\n".join(parts) or None

        elif ll.startswith("good example"):
            i += 1
            while i < len(lines) and not _is_section_header(lines[i]):
                if good_example is None:
                    good_example = lines[i]
                i += 1

        elif ll.startswith("should not write"):
            sections_found += 1
            i += 1
            while i < len(lines) and not _is_section_header(lines[i]):
                should_not_write_lines.append(lines[i])
                i += 1

        elif ll.startswith("should write"):
            i += 1
            while i < len(lines) and not _is_section_header(lines[i]):
                preferred.append(lines[i])
                i += 1

        else:
            i += 1

    snw_text = "\n".join(should_not_write_lines)
    forbidden_words = _extract_forbidden_words(snw_text)

    return ParsedBrief(
        brand_name=brand_name,
        brand_type=brand_type,
        core_idea=core_idea,
        target_markets=target_markets,
        customer_segment=customer_segment,
        customer_mindset=customer_mindset,
        voice_examples=VoiceExamples(
            tone_traits=tone_traits,
            good_example=good_example,
            preferred=preferred,
            should_not_write=[line for line in snw_text.split("\n") if line.strip()],
        ),
        style_guide=style_guide,
        forbidden_words=forbidden_words,
        confidence=round(sections_found / _EXPECTED_SECTIONS, 2),
    )
