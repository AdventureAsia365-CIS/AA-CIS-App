"""
AA-49 H-2 — Deterministic post-processor: apply acp_output_rules after every LLM call.
AA-115 — Forbidden word enforcement audit + fix.

Call order in S4 flow:
  LLM generation → apply_output_rules() → acp-s4-evaluate Lambda → DB save

DB schema (actual): acp_shared.acp_output_rules
  rule_id, tenant_id, stage, rule_type, pattern, action_value,
  error_message, source_type, source_hitl_id, run_count, is_active
"""
import re
import unicodedata
import asyncpg
import structlog
from typing import Optional

logger = structlog.get_logger()

# Ordered list of output dict fields scanned for forbidden content.
_TEXT_FIELDS = ("content", "content_md", "seo_title", "seo_meta", "title")


class OutputRuleViolation(Exception):
    def __init__(self, rule_id: str, rule_type: str, message: str,
                 field_name: str = "", matched_text: str = ""):
        self.rule_id = rule_id
        self.rule_type = rule_type
        self.field_name = field_name
        self.matched_text = matched_text
        super().__init__(message, rule_id, rule_type, field_name, matched_text)


def _normalize(text: str) -> str:
    """Lowercase + strip combining diacritics (NFKD) for deterministic comparison."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _collect_text_fields(output: dict) -> list[tuple[str, str]]:
    """Return [(field_name, field_value)] for all non-empty string fields in _TEXT_FIELDS."""
    return [
        (field, output[field])
        for field in _TEXT_FIELDS
        if output.get(field) and isinstance(output.get(field), str)
    ]


async def apply_output_rules(
    output: dict,
    stage: Optional[str],
    tenant_id: str,
    db: asyncpg.Connection,
) -> dict:
    """
    Apply all active acp_output_rules for the given stage and tenant.

    Mutates output dict in place and appends:
      output["review_flags"]  — list of flagged rule dicts (rule_id, rule_type, pattern,
                                 field_name, matched_text, message)
      output["rules_applied"] — list of rule_id strings that triggered

    Raises OutputRuleViolation for block or score_gate rule types.
    """
    rules = await db.fetch(
        """SELECT rule_id::text, rule_type, pattern, action_value, error_message
           FROM acp_shared.acp_output_rules
           WHERE is_active = TRUE
             AND (stage = $1 OR stage IS NULL)
             AND (tenant_id = $2 OR tenant_id IS NULL)
           ORDER BY source_type ASC, created_at ASC""",
        stage,
        tenant_id,
    )

    review_flags: list[dict] = []
    rules_applied: list[str] = []
    text_fields = _collect_text_fields(output)

    for rule in rules:
        rule_id = rule["rule_id"]
        rule_type = rule["rule_type"]
        pattern = (rule["pattern"] or "").strip()
        action_value = rule["action_value"] or ""
        error_msg = rule["error_message"] or f"Rule {rule_id} ({rule_type}) violated"

        if not pattern:
            continue

        matched_field = ""
        matched_text = ""
        triggered = False

        if rule_type in ("block", "score_gate"):
            # hard_forbidden: normalized case-insensitive substring match across all text fields.
            norm_pattern = _normalize(pattern)
            for field_name, field_val in text_fields:
                if norm_pattern in _normalize(field_val):
                    matched_field = field_name
                    matched_text = pattern
                    triggered = True
                    break

        elif rule_type == "flag":
            # sanitization_reject: regex search across all text fields.
            # re.escape() used because DB stores literal substrings (some contain regex metachar $).
            try:
                regex = re.compile(re.escape(pattern), re.IGNORECASE | re.MULTILINE)
            except re.error:
                norm_pattern = _normalize(pattern)
                for field_name, field_val in text_fields:
                    if norm_pattern in _normalize(field_val):
                        matched_field = field_name
                        matched_text = pattern
                        triggered = True
                        break
            else:
                for field_name, field_val in text_fields:
                    m = regex.search(field_val)
                    if m:
                        matched_field = field_name
                        matched_text = m.group(0)
                        triggered = True
                        break

        elif rule_type == "replace":
            # Operates on the primary content field only.
            content_field = "content_md" if "content_md" in output else "content"
            content = output.get(content_field, "") or ""
            triggered = _normalize(pattern) in _normalize(content)
            if triggered:
                matched_field = content_field
                matched_text = pattern

        elif rule_type == "truncate":
            # pattern = target field name; action_value = max char length.
            try:
                max_len = int(action_value)
                target_field = pattern
                field_val = output.get(target_field, "") or ""
                if len(field_val) > max_len:
                    output[target_field] = field_val[:max_len]
                    triggered = True
                    matched_field = target_field
            except (ValueError, TypeError):
                pass

        if not triggered:
            continue

        rules_applied.append(rule_id)
        await db.execute(
            "UPDATE acp_shared.acp_output_rules SET run_count = run_count + 1 WHERE rule_id = $1::uuid",
            rule_id,
        )

        if rule_type == "block":
            raise OutputRuleViolation(
                rule_id, rule_type, error_msg,
                field_name=matched_field, matched_text=matched_text,
            )

        elif rule_type == "replace":
            content_field = "content_md" if "content_md" in output else "content"
            content = output.get(content_field, "") or ""
            output[content_field] = re.sub(re.escape(pattern), action_value, content, flags=re.IGNORECASE)
            text_fields = _collect_text_fields(output)  # refresh after mutation

        elif rule_type == "flag":
            review_flags.append({
                "rule_id": rule_id,
                "rule_type": rule_type,
                "pattern": pattern,
                "field_name": matched_field,
                "matched_text": matched_text,
                "message": error_msg,
            })

        elif rule_type == "score_gate":
            raise OutputRuleViolation(
                rule_id, rule_type, error_msg,
                field_name=matched_field, matched_text=matched_text,
            )

    logger.info("output_rules_applied",
                violation_count=len(rules_applied),
                rules_applied=rules_applied)

    output["review_flags"] = review_flags
    output["rules_applied"] = rules_applied
    return output
