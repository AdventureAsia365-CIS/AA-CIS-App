"""
AA-80 — ValidatorAgent: port of Ms. Thư's validator_agent.py.

Input:  blog dict {content_md, title, seo_title, seo_meta, target_keywords, ...}
        brief dict {primary_keyword, outline, destination, ...}  (optional)
Output: ValidationResult with 30+ CheckResult items.

No OpenAI dependency. No structured BlogArticle — parses raw markdown.
db_rules come from acp_shared.acp_output_rules (fetched by caller).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from services.acp_s4_blog.models import CheckResult, ValidationResult
from services.acp_s4_blog.sample_loader import get_sample_metrics

# ── Constants from Ms. Thư's models.py ───────────────────────────────────────

LEAK_PHRASES: tuple[str, ...] = (
    "this section follows the calendar brief",
    "this guide follows the editorial brief",
    "operational note",
    "verify provider details",
    "planner agent",
    "return json only",
    "selected content calendar post",
    "itinerary context",
    "route-specific logistics, seasonal caveats",
    "calendar brief",
    "brief outline",
    "internal note",
    "writer note",
    "placeholder text",
)

PROCESS_LANGUAGE_PHRASES: tuple[str, ...] = (
    "start by validating",
    "use this as a logistics check",
    "practical filter is seasonality and access",
    "treat this as a budgeting decision",
    "confirm operator assumptions",
    "changes execution on the ground",
    "refer to brief",
    "cross-check with",
    "double-check",
)

HYPE_PHRASES: tuple[str, ...] = (
    "trip of a lifetime",
    "once in a lifetime",
    "book now before it is too late",
    "don't miss out",
    "ultimate adventure",
    "hidden gem",
    "unforgettable",
    "breathtaking",
    "stunning",
    "world-class",
    "iconic",
    "epic",
)

KOREA_PLACES: frozenset[str] = frozenset({
    "seoul", "busan", "jeju", "seoraksan", "gangneung", "sokcho",
    "gyeongju", "jeonju", "dmz", "hallasan", "jirisan",
})

CAVEAT_MARKERS: tuple[str, ...] = (
    "caveat", "trade-off", "harder", "humidity", "friction",
    "limitation", "pace", "season", "consider", "be aware",
)

PROOF_PLACES: frozenset[str] = frozenset({
    "seoul", "busan", "jeju", "gyeongju", "sokcho", "gangneung",
    "seoraksan", "hallasan", "han river", "dmz",
})

RAW_DATETIME_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}[ t]\d{2}:\d{2}:\d{2}\b", re.IGNORECASE)
RAW_FIELD_BLOB_PATTERN = re.compile(
    r"(day\s*\d+\s*[a-z].*arrival.*ride|from\s*\$\s*\d[\d,]*|tour_id|created_at|updated_at)",
    re.IGNORECASE,
)

STRATEGIC_PHRASES: tuple[str, ...] = (
    "optimize for", "traveler energy", "sequence logic",
    "controlled intensity", "practical elegance",
)

TRANSITION_MARKERS: tuple[str, ...] = (
    "that shift", "from there", "the route then",
    "this matters because", "by contrast", "as a result",
)

INTIMACY_MARKERS: tuple[str, ...] = (
    "you notice", "you feel", "at sunrise", "at dusk", "locals",
    "the air", "what changes", "the moment", "arriving", "stops feeling",
)

ROUTE_LOGIC_MARKERS: tuple[str, ...] = (
    "sequence", "transition", "pace", "fit", "intensity", "transfer",
)


# ── Markdown parser ───────────────────────────────────────────────────────────

@dataclass
class _ParsedBlog:
    h1: str = ""
    intro_paragraphs: list[str] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)  # {heading, paragraphs}
    faq_items: list[dict] = field(default_factory=list)  # {question, answer}
    full_text: str = ""


def _parse_markdown(text: str) -> _ParsedBlog:
    """Parse raw markdown into structured blog representation."""
    parsed = _ParsedBlog(full_text=text)
    lines = text.split("\n")

    current_section: Optional[dict] = None
    current_faq_q: Optional[str] = None
    current_faq_a_lines: list[str] = []
    in_faq_section = False
    before_first_h2 = True

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("# ") and not parsed.h1:
            parsed.h1 = stripped[2:].strip()
            continue

        if stripped.startswith("## "):
            # Save previous FAQ answer if pending
            if current_faq_q and current_faq_a_lines:
                parsed.faq_items.append({
                    "question": current_faq_q,
                    "answer": " ".join(current_faq_a_lines).strip(),
                })
                current_faq_q = None
                current_faq_a_lines = []

            heading = stripped[3:].strip()
            in_faq_section = any(kw in heading.lower() for kw in ("faq", "frequently asked", "questions"))
            before_first_h2 = False
            current_section = {"heading": heading, "paragraphs": []}
            parsed.sections.append(current_section)
            continue

        if stripped.startswith("### "):
            if current_section:
                current_section["paragraphs"].append(stripped[4:].strip())
            continue

        # FAQ detection: **Q: ...** pattern
        faq_q_match = re.match(r"^\*\*Q(?:uestion)?[:.]?\s*(.*?)\*\*", stripped, re.IGNORECASE)
        if faq_q_match or (in_faq_section and re.match(r"^\d+\.\s+.+\?$", stripped)):
            if current_faq_q and current_faq_a_lines:
                parsed.faq_items.append({
                    "question": current_faq_q,
                    "answer": " ".join(current_faq_a_lines).strip(),
                })
            current_faq_q = faq_q_match.group(1).strip() if faq_q_match else stripped
            current_faq_a_lines = []
            continue

        # FAQ answer: **A:** or bold answer
        faq_a_match = re.match(r"^\*\*A(?:nswer)?[:.]?\*\*\s*(.*)", stripped, re.IGNORECASE)
        if faq_a_match and current_faq_q:
            current_faq_a_lines = [faq_a_match.group(1)]
            continue

        if not stripped:
            continue

        if before_first_h2:
            if stripped and not stripped.startswith("#"):
                parsed.intro_paragraphs.append(stripped)
        elif current_faq_q is not None:
            if not stripped.startswith("**Q"):
                current_faq_a_lines.append(stripped)
        elif in_faq_section and stripped.endswith("?") and len(stripped.split()) < 15:
            if current_faq_q and current_faq_a_lines:
                parsed.faq_items.append({
                    "question": current_faq_q,
                    "answer": " ".join(current_faq_a_lines).strip(),
                })
            current_faq_q = stripped
            current_faq_a_lines = []
        elif current_section is not None and stripped:
            if not stripped.startswith("|") and not stripped.startswith("- [ ]"):
                current_section["paragraphs"].append(stripped)

    # Flush pending FAQ item
    if current_faq_q and current_faq_a_lines:
        parsed.faq_items.append({
            "question": current_faq_q,
            "answer": " ".join(current_faq_a_lines).strip(),
        })

    return parsed


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _word_count_text(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _ok(name: str, hint: str = "") -> CheckResult:
    return CheckResult(check_name=name, passed=True, score=1.0, issues=[], repair_hint=hint)


def _fail(name: str, issues: list[str], score: float = 0.0, hint: str = "") -> CheckResult:
    return CheckResult(check_name=name, passed=False, score=score, issues=issues, repair_hint=hint)


# ── GROUP A: Structural checks ────────────────────────────────────────────────

def _check_word_count(parsed: _ParsedBlog) -> CheckResult:
    wc = _word_count_text(parsed.full_text)
    if 1500 <= wc <= 3000:
        return _ok("word_count")
    if wc < 1500:
        return _fail("word_count", [f"Word count too low: {wc} (need 1500–3000)"],
                     score=wc / 1500, hint="Expand sections with proof points and route detail")
    return _fail("word_count", [f"Word count too high: {wc} (max 3000)"],
                 score=3000 / wc, hint="Trim repetitive paragraphs and list items")


def _check_h1_matches_topic(title: str, brief: dict) -> CheckResult:
    primary_kw = brief.get("primary_keyword", "")
    if not primary_kw:
        return _ok("h1_matches_topic")
    h1_tokens = set(_tokens(title))
    kw_tokens = set(_tokens(primary_kw))
    if not h1_tokens or not kw_tokens:
        return _fail("h1_matches_topic", ["H1 or primary keyword is empty"],
                     hint="Ensure title and primary_keyword are provided")
    overlap = len(h1_tokens & kw_tokens) / max(1, len(kw_tokens))
    if overlap >= 0.3:
        return _ok("h1_matches_topic")
    return _fail("h1_matches_topic",
                 [f"H1 '{title}' has low overlap ({overlap:.0%}) with keyword '{primary_kw}'"],
                 score=overlap,
                 hint="Align H1 with primary keyword — include key terms naturally")


def _check_outline_coverage(parsed: _ParsedBlog, brief: dict) -> CheckResult:
    outline = brief.get("outline") or []
    if not outline:
        return _ok("outline_coverage")
    article_text = " ".join(
        [parsed.h1] + parsed.intro_paragraphs
        + [s["heading"] for s in parsed.sections]
        + [p for s in parsed.sections for p in s["paragraphs"]]
    ).lower()
    matched = 0
    for point in outline:
        key_terms = [t for t in _tokens(point) if len(t) > 3][:5]
        if not key_terms:
            continue
        if sum(1 for term in key_terms if term in article_text) >= 2:
            matched += 1
    coverage = matched / max(1, len(outline))
    if coverage >= 0.6:
        return _ok("outline_coverage")
    return _fail("outline_coverage",
                 [f"Only {matched}/{len(outline)} outline points covered ({coverage:.0%}, need 60%)"],
                 score=coverage,
                 hint="Ensure each outline section is reflected in content headings or body")


def _check_duplicate_faq_answers(parsed: _ParsedBlog) -> CheckResult:
    answers = [item["answer"].strip().lower() for item in parsed.faq_items if item.get("answer", "").strip()]
    for i in range(len(answers)):
        for j in range(i + 1, len(answers)):
            if SequenceMatcher(None, answers[i], answers[j]).ratio() >= 0.9:
                return _fail("duplicate_faq_answers",
                             [f"FAQ answers {i+1} and {j+1} are near-duplicates"],
                             hint="Rewrite duplicated FAQ answers with distinct direct responses")
    return _ok("duplicate_faq_answers")


def _check_notes_style(parsed: _ParsedBlog) -> CheckResult:
    """Compare paragraph quality against sample benchmark metrics."""
    issues = []
    paragraphs = [p for s in parsed.sections for p in s["paragraphs"] if p.strip()]
    if not paragraphs:
        return _fail("notes_style", ["No section prose paragraphs found"],
                     hint="Add substantive paragraph prose to each section")

    unique_ratio = len({p.lower() for p in paragraphs}) / max(1, len(paragraphs))
    if unique_ratio < 0.75:
        issues.append("Paragraphs are overly repetitive and read like undeveloped outline notes")

    para_lengths = [_word_count_text(p) for p in paragraphs]
    avg_len = sum(para_lengths) / max(1, len(para_lengths))
    try:
        sample_metrics = get_sample_metrics()
        sample_avg = (
            sum(m["avg_paragraph_length"] for m in sample_metrics.values()) / max(1, len(sample_metrics))
        )
    except Exception:
        sample_avg = 70.0
    if avg_len < max(30.0, sample_avg * 0.45):
        issues.append(
            f"Paragraph development too thin ({avg_len:.0f} words avg, sample benchmark: {sample_avg:.0f})"
        )

    transition_markers = ("but", "while", "because", "however", "instead", "then", "after", "before")
    transition_hits = sum(1 for p in paragraphs if any(f" {m} " in f" {p.lower()} " for m in transition_markers))
    if transition_hits < max(2, len(paragraphs) // 4):
        issues.append("Narrative flow weak; prose reads like disconnected notes")

    if not issues:
        return _ok("notes_style")
    score = max(0.0, 1.0 - len(issues) * 0.25)
    return _fail("notes_style", issues, score=score,
                 hint="Develop paragraphs with 50+ words, add transitions, eliminate repetition")


def _check_broad_destination(parsed: _ParsedBlog, brief: dict) -> CheckResult:
    """Only applies for Korea destination articles."""
    destination = (brief.get("destination") or "").lower()
    if "korea" not in destination:
        return _ok("broad_destination")
    full_text = " ".join(
        [parsed.h1] + parsed.intro_paragraphs
        + [p for s in parsed.sections for p in s["paragraphs"]]
        + [item["answer"] for item in parsed.faq_items]
    ).lower()
    hits = sum(1 for place in KOREA_PLACES if place in full_text)
    if hits >= 3:
        return _ok("broad_destination")
    places_list = ", ".join(sorted(KOREA_PLACES))
    return _fail("broad_destination",
                 [f"Korea destination article references only {hits} locations (need ≥3 from: {places_list})"],
                 score=hits / 3,
                 hint="Add specific South Korea regional examples (Seoul, Busan, Jeju, Gyeongju, etc.)")


def _check_faq_process_language(parsed: _ParsedBlog) -> CheckResult:
    issues = []
    for idx, item in enumerate(parsed.faq_items):
        answer = (item.get("answer") or "").lower()
        if any(phrase in answer for phrase in PROCESS_LANGUAGE_PHRASES):
            issues.append(f"FAQ answer {idx+1} uses internal/process language instead of direct guidance")
        if "verify provider" in answer or "operational note" in answer:
            issues.append(f"FAQ answer {idx+1} contains internal workflow wording")
    if not issues:
        return _ok("faq_process_language")
    return _fail("faq_process_language", issues,
                 hint="Rewrite FAQ answers as direct reader-facing guidance — no planning/operational language")


def _check_proof_point_count(parsed: _ParsedBlog, brief: dict) -> CheckResult:
    """Count distinct proof points: named places + measurable facts."""
    tokens: set[str] = set()
    text = " ".join(
        parsed.intro_paragraphs
        + [s["heading"] for s in parsed.sections]
        + [p for s in parsed.sections for p in s["paragraphs"]]
    ).lower()

    for place in PROOF_PLACES:
        if place in text:
            tokens.add(f"place:{place}")
    if re.search(r"\b\d+\s*(?:km|kilometres|kilometers)\b", text):
        tokens.add("distance:km")
    if re.search(r"\b\d+\s*(?:day|days|hour|hours)\b", text):
        tokens.add("duration")
    for marker in ("terrain", "trail", "coast", "mountain", "transfer", "ktx", "spring", "autumn", "humidity"):
        if marker in text:
            tokens.add(f"detail:{marker}")
    for marker in ("food", "market", "temple", "hanok", "bbq"):
        if marker in text:
            tokens.add(f"culture:{marker}")
    for marker in ("harder", "trade-off", "caveat", "limitation", "friction"):
        if marker in text:
            tokens.add(f"caveat:{marker}")

    count = len(tokens)
    if count >= 6:
        return _ok("proof_point_count")
    return _fail("proof_point_count",
                 [f"Only {count} distinct proof points (need ≥6): add places, distances, terrain, seasonal facts"],
                 score=count / 6,
                 hint="Add named places, km/day measurements, terrain details, seasonal trade-offs")


def _check_honest_caveat(parsed: _ParsedBlog) -> CheckResult:
    text = " ".join(
        parsed.intro_paragraphs
        + [p for s in parsed.sections for p in s["paragraphs"]]
        + [item["answer"] for item in parsed.faq_items]
    ).lower()
    if any(marker in text for marker in CAVEAT_MARKERS):
        return _ok("honest_caveat")
    return _fail("honest_caveat",
                 ["Missing honest caveat/trade-off about difficulty, season, or logistics"],
                 hint="Insert one honest caveat: humidity change, harder day, transfer friction, seasonal limitation")


def _check_opening_generic(parsed: _ParsedBlog) -> CheckResult:
    intro_text = " ".join(parsed.intro_paragraphs[:2])
    lowered = intro_text.lower()
    generic_patterns = [
        "is a destination", "is known for", "this guide will",
        "south korea is", "this itinerary is designed",
        "this guide follows", "use it to evaluate",
    ]
    is_generic = any(p in lowered for p in generic_patterns) and _word_count_text(intro_text) < 90
    if not is_generic:
        return _ok("opening_generic")
    return _fail("opening_generic",
                 ["Opening is generic and does not set a specific scene, contrast, or grounded claim"],
                 hint="Rewrite opening with scene/contrast/surprising claim — avoid 'is known for' or brochure intros")


# ── GROUP B: Content quality checks ──────────────────────────────────────────

def _check_looks_generic(parsed: _ParsedBlog, brief: dict) -> CheckResult:
    destination = (brief.get("destination") or "").lower().replace("_", " ")
    outline = brief.get("outline") or []
    text = " ".join(
        [parsed.h1] + parsed.intro_paragraphs
        + [s["heading"] for s in parsed.sections]
        + [p for s in parsed.sections for p in s["paragraphs"]]
    ).lower()

    country_ok = destination in text if destination else True
    if outline:
        outline_tokens: set[str] = set()
        for point in outline:
            outline_tokens.update(t for t in _tokens(point) if len(t) > 4)
        hits = sum(1 for t in list(outline_tokens)[:15] if t in text)
        if not country_ok or hits < 5:
            return _fail("looks_generic",
                         [f"Article is too generic: destination in text={country_ok}, outline hits={hits}/15"],
                         score=hits / 15,
                         hint="Include destination name and cover ≥5 key outline topic tokens throughout")
    elif not country_ok:
        return _fail("looks_generic",
                     [f"Destination '{destination}' not mentioned in content"],
                     hint="Reference the destination name naturally in the article body")
    return _ok("looks_generic")


def _check_token_overlap_brief(parsed: _ParsedBlog, brief: dict) -> CheckResult:
    kw = brief.get("primary_keyword", "")
    if not kw:
        return _ok("token_overlap_brief")
    kw_tokens = set(_tokens(kw))
    text_tokens = set(_tokens(parsed.full_text))
    if not kw_tokens:
        return _ok("token_overlap_brief")
    overlap = len(kw_tokens & text_tokens) / len(kw_tokens)
    if overlap >= 0.5:
        return _ok("token_overlap_brief")
    return _fail("token_overlap_brief",
                 [f"Primary keyword token coverage {overlap:.0%} (need ≥50%) — keyword: '{kw}'"],
                 score=overlap,
                 hint="Use primary keyword terms naturally throughout headings and body")


def _check_leak_phrases(text: str) -> CheckResult:
    lowered = text.lower()
    found = [phrase for phrase in LEAK_PHRASES if phrase in lowered]
    if not found:
        return _ok("leak_phrases")
    return _fail("leak_phrases",
                 [f"Internal phrase leaked: '{p}'" for p in found],
                 hint="Remove all scaffolding/planning language — article must be reader-facing prose only")


def _check_process_language(text: str) -> CheckResult:
    lowered = text.lower()
    found = [phrase for phrase in PROCESS_LANGUAGE_PHRASES if phrase in lowered]
    if not found:
        return _ok("process_language")
    return _fail("process_language",
                 [f"Process language detected: '{p}'" for p in found],
                 hint="Replace planning/workflow instructions with direct reader guidance")


def _check_raw_datetime(text: str) -> CheckResult:
    if RAW_DATETIME_PATTERN.search(text):
        return _fail("raw_datetime",
                     ["Raw datetime stamp detected (e.g. 2024-01-15 14:30:00)"],
                     hint="Strip all raw datetime fields — they must not appear in rendered content")
    return _ok("raw_datetime")


def _check_raw_field_blob(text: str) -> CheckResult:
    if RAW_FIELD_BLOB_PATTERN.search(text):
        return _fail("raw_field_blob",
                     ["Raw DB field blob detected (tour_id, created_at, updated_at, or price field)"],
                     hint="Strip all raw source fields before rendering")
    return _ok("raw_field_blob")


def _check_section_leaks(parsed: _ParsedBlog) -> CheckResult:
    """Scan each section for leak phrases — more granular than whole-text check."""
    issues = []
    for s in parsed.sections:
        section_text = " ".join([s["heading"]] + s["paragraphs"]).lower()
        for phrase in LEAK_PHRASES:
            if phrase in section_text:
                heading_short = s["heading"][:40]
                issues.append(f"Section '{heading_short}' leaks: '{phrase}'")
                break
    if not issues:
        return _ok("section_leaks")
    return _fail("section_leaks", issues,
                 hint="Remove leaked planning/scaffolding language section by section")


def _check_sentence_repetition(parsed: _ParsedBlog) -> CheckResult:
    """Detect near-duplicate sentences (>80% similarity) across paragraphs."""
    all_paragraphs = parsed.intro_paragraphs + [p for s in parsed.sections for p in s["paragraphs"]]
    sentences: list[str] = []
    for para in all_paragraphs:
        sentences.extend(re.split(r"[.!?]+", para))
    sentences = [s.strip() for s in sentences if len(s.strip().split()) > 6]

    for i in range(len(sentences)):
        for j in range(i + 1, len(sentences)):
            if SequenceMatcher(None, sentences[i].lower(), sentences[j].lower()).ratio() >= 0.8:
                return _fail("sentence_repetition",
                             [f"Near-duplicate sentences detected: '{sentences[i][:60]}...'"],
                             hint="Rewrite repeated sentences — each sentence must contribute unique information")
    return _ok("sentence_repetition")


def _check_cross_section_continuity(parsed: _ParsedBlog) -> CheckResult:
    """Detect copy-pasted paragraphs across sections."""
    all_paras = [p.strip().lower() for s in parsed.sections for p in s["paragraphs"] if p.strip()]
    seen: dict[str, int] = {}
    for idx, para in enumerate(all_paras):
        key = " ".join(para.split()[:12])
        if key in seen and len(para.split()) > 10:
            return _fail("cross_section_continuity",
                         [f"Paragraph starting '{key[:50]}...' appears in multiple sections"],
                         hint="Each section must develop unique content — remove copy-pasted paragraphs")
        seen[key] = idx
    return _ok("cross_section_continuity")


def _check_hype_phrases(text: str) -> CheckResult:
    lowered = text.lower()
    found = [p for p in HYPE_PHRASES if p in lowered]
    if not found:
        return _ok("hype_phrases")
    return _fail("hype_phrases",
                 [f"Hype/AI-filler phrase: '{p}'" for p in found],
                 hint="Replace generic hype terms with specific descriptive language")


# ── GROUP C: Additional structural quality checks ─────────────────────────────

def _check_section_count(parsed: _ParsedBlog) -> CheckResult:
    n = len(parsed.sections)
    if n >= 4:
        return _ok("section_count")
    return _fail("section_count", [f"Only {n} sections (need ≥4)"],
                 score=n / 4, hint="Add at least 4 H2 sections with substantive prose")


def _check_faq_count(parsed: _ParsedBlog) -> CheckResult:
    n = len(parsed.faq_items)
    if n >= 4:
        return _ok("faq_count")
    return _fail("faq_count", [f"Only {n} FAQ items detected (need ≥4)"],
                 score=n / 4, hint="Include at least 4 specific FAQ items with direct answers")


def _check_seo_title_length(blog: dict) -> CheckResult:
    seo_title = blog.get("seo_title", "")
    if not seo_title:
        return _fail("seo_title_length", ["Missing SEO title"],
                     hint="Provide an SEO title of 50–60 characters")
    n = len(seo_title)
    if 50 <= n <= 70:
        return _ok("seo_title_length")
    return _fail("seo_title_length",
                 [f"SEO title length {n} chars (ideal 50–60)"],
                 score=1.0 if n <= 70 else 0.5,
                 hint="Adjust SEO title to 50–60 characters")


def _check_strategic_language(parsed: _ParsedBlog) -> CheckResult:
    text = " ".join(parsed.intro_paragraphs + [p for s in parsed.sections for p in s["paragraphs"]]).lower()
    hits = sum(text.count(phrase) for phrase in STRATEGIC_PHRASES)
    if hits < 3:
        return _ok("strategic_language")
    return _fail("strategic_language",
                 [f"Overuse of strategic/advisory language ({hits} instances): {', '.join(STRATEGIC_PHRASES)}"],
                 score=max(0.0, 1.0 - (hits - 2) * 0.2),
                 hint="Replace abstract strategy phrases with specific place-authored observations")


def _check_transition_quality(parsed: _ParsedBlog) -> CheckResult:
    if len(parsed.sections) < 4:
        return _ok("transition_quality")
    body = [p.lower() for s in parsed.sections for p in s["paragraphs"]]
    hits = sum(1 for p in body if any(m in p for m in TRANSITION_MARKERS))
    need = max(2, len(parsed.sections) // 2)
    if hits >= need:
        return _ok("transition_quality")
    return _fail("transition_quality",
                 [f"Transitions weak: {hits} transition phrases (need ≥{need})"],
                 score=hits / need,
                 hint="Add transition phrases: 'from there', 'that shift', 'the route then', 'by contrast'")


def _check_destination_specificity(parsed: _ParsedBlog, brief: dict) -> CheckResult:
    """Check for named places and specific regional references."""
    text = " ".join(
        [parsed.h1] + parsed.intro_paragraphs
        + [p for s in parsed.sections for p in s["paragraphs"]]
    ).lower()
    named_places = len({p for p in KOREA_PLACES if p in text})
    destination = (brief.get("destination") or "").lower()
    if "korea" not in destination:
        return _ok("destination_specificity")
    if named_places >= 3:
        return _ok("destination_specificity")
    return _fail("destination_specificity",
                 [f"Only {named_places} named Korea locations (need ≥3 for credibility)"],
                 score=named_places / 3,
                 hint="Reference specific Korea locations: Seoul, Busan, Jeju, Gyeongju, Sokcho")


def _check_voice_intimacy(parsed: _ParsedBlog) -> CheckResult:
    text = " ".join(parsed.intro_paragraphs + [p for s in parsed.sections for p in s["paragraphs"]]).lower()
    hits = sum(1 for m in INTIMACY_MARKERS if m in text)
    if hits >= 3:
        return _ok("voice_intimacy")
    return _fail("voice_intimacy",
                 [f"Voice intimacy low ({hits}/8 markers): add observed details ('you notice', 'locals', 'at dusk')"],
                 score=hits / 8,
                 hint="Add one observed, lived-in sentence per section (sensory details, local moments)")


def _check_itinerary_duplication(parsed: _ParsedBlog) -> CheckResult:
    text = " ".join(
        [p for s in parsed.sections for p in s["paragraphs"]] + parsed.intro_paragraphs
    ).lower()
    day_markers = len(re.findall(r"\bday\s*\d+\b", text))
    time_block_markers = len(re.findall(r"\b(?:morning|afternoon|evening)\b", text))
    if day_markers >= 4 or time_block_markers >= 4:
        return _fail("itinerary_duplication",
                     [f"Schedule language overuse: {day_markers} 'day N' markers, {time_block_markers} time blocks"],
                     hint="Replace day-by-day schedule language with route-logic narrative")
    return _ok("itinerary_duplication")


def _check_thesis_presence(parsed: _ParsedBlog) -> CheckResult:
    intro = " ".join(parsed.intro_paragraphs[:3]).lower()
    if not parsed.intro_paragraphs:
        return _fail("thesis_presence", ["No intro paragraphs found — thesis cannot be evaluated"],
                     hint="Add 2 intro paragraphs: scene/contrast, then explicit thesis")
    if len(parsed.intro_paragraphs) < 2:
        return _fail("thesis_presence",
                     ["Opening has fewer than 2 paragraphs — thesis must be stated in second paragraph"],
                     hint="Add second intro paragraph with explicit destination thesis")
    return _ok("thesis_presence")


# ── GROUP D: Compiled db_rules checks ────────────────────────────────────────

def _check_compiled_rules(text: str, db_rules: list[dict]) -> list[CheckResult]:
    """One CheckResult per firing db_rule. Returns empty list if no rules provided."""
    if not db_rules:
        return [_ok("compiled_rules_no_rules")]

    results = []
    lowered = text.lower()

    for rule in db_rules:
        rule_id = rule.get("rule_id", "")
        rule_type = rule.get("rule_type", "flag")
        pattern = (rule.get("pattern") or "").lower()
        error_msg = rule.get("error_message") or f"Rule {rule_id} ({rule_type}): {pattern}"

        if not pattern:
            continue

        fired = pattern in lowered
        check_name = f"rule:{rule_type}:{pattern[:25].replace(' ', '_')}"

        if fired:
            if rule_type == "block":
                results.append(_fail(check_name, [error_msg], score=0.0,
                                     hint=f"Remove or rephrase content matching '{pattern}'"))
            elif rule_type == "flag":
                results.append(_fail(check_name, [f"[FLAG] {error_msg}"], score=0.7,
                                     hint=f"Review content matching '{pattern}' before publishing"))
            elif rule_type == "score_gate":
                results.append(_fail(check_name, [error_msg], score=0.0,
                                     hint=f"Score gate triggered by '{pattern}'"))
        else:
            results.append(_ok(check_name))

    return results


# ── ValidatorAgent ────────────────────────────────────────────────────────────

class ValidatorAgent:
    """
    Port of Ms. Thư's ValidatorAgent. Runs 30+ deterministic checks
    against a flat markdown blog dict.

    Args:
        db_rules: list of acp_output_rules rows (dicts with rule_id, rule_type,
                  pattern, action_value). Fetch with stage IS NULL before calling.
    """

    def __init__(self, db_rules: Optional[list[dict]] = None):
        self._db_rules = db_rules or []

    async def validate(self, blog: dict, brief: Optional[dict] = None) -> ValidationResult:
        brief = brief or {}
        text = blog.get("content_md", "")
        title = blog.get("title", "") or blog.get("seo_title", "")
        parsed = _parse_markdown(text)
        if not parsed.h1 and title:
            parsed.h1 = title

        checks: list[CheckResult] = []

        # GROUP A — Structural
        checks.append(_check_word_count(parsed))
        checks.append(_check_h1_matches_topic(parsed.h1, brief))
        checks.append(_check_outline_coverage(parsed, brief))
        checks.append(_check_duplicate_faq_answers(parsed))
        checks.append(_check_notes_style(parsed))
        checks.append(_check_broad_destination(parsed, brief))
        checks.append(_check_faq_process_language(parsed))
        checks.append(_check_proof_point_count(parsed, brief))
        checks.append(_check_honest_caveat(parsed))
        checks.append(_check_opening_generic(parsed))

        # GROUP B — Content quality
        checks.append(_check_looks_generic(parsed, brief))
        checks.append(_check_token_overlap_brief(parsed, brief))
        checks.append(_check_leak_phrases(text))
        checks.append(_check_process_language(text))
        checks.append(_check_raw_datetime(text))
        checks.append(_check_raw_field_blob(text))
        checks.append(_check_section_leaks(parsed))
        checks.append(_check_sentence_repetition(parsed))
        checks.append(_check_cross_section_continuity(parsed))
        checks.append(_check_hype_phrases(text))

        # GROUP C — Additional structural quality
        checks.append(_check_section_count(parsed))
        checks.append(_check_faq_count(parsed))
        checks.append(_check_seo_title_length(blog))
        checks.append(_check_strategic_language(parsed))
        checks.append(_check_transition_quality(parsed))
        checks.append(_check_destination_specificity(parsed, brief))
        checks.append(_check_voice_intimacy(parsed))
        checks.append(_check_itinerary_duplication(parsed))
        checks.append(_check_thesis_presence(parsed))

        # GROUP D — Compiled db_rules (one CheckResult per rule)
        checks.extend(_check_compiled_rules(text, self._db_rules))

        # Aggregate
        failing = [c for c in checks if not c.passed]
        passing = [c for c in checks if c.passed]
        overall_score = sum(c.score for c in checks) / max(1, len(checks))
        failing_sections = list({c.check_name for c in failing})

        repair_targets = [
            {
                "section": c.check_name,
                "check_name": c.check_name,
                "hint": c.repair_hint,
            }
            for c in failing
            if c.repair_hint
        ]

        return ValidationResult(
            blog_draft_id=blog.get("draft_id"),
            overall_passed=len(failing) == 0,
            overall_score=round(overall_score, 3),
            checks=checks,
            failing_sections=sorted(failing_sections),
            repair_targets=repair_targets,
        )
