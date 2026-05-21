"""
AA-49 H-2 — Deterministic post-processor: apply acp_output_rules after every LLM call.

Call order in S4 flow:
  LLM generation → apply_output_rules() → acp-s4-evaluate Lambda → DB save

DB schema (actual): acp_shared.acp_output_rules
  rule_id, tenant_id, stage, rule_type, pattern, action_value,
  error_message, source_type, source_hitl_id, run_count, is_active
"""
import re
import asyncpg
from typing import Optional


class OutputRuleViolation(Exception):
    def __init__(self, rule_id: str, rule_type: str, message: str):
        self.rule_id = rule_id
        self.rule_type = rule_type
        super().__init__(message, rule_id, rule_type)


async def apply_output_rules(
    output: dict,
    stage: Optional[str],
    tenant_id: str,
    db: asyncpg.Connection,
) -> dict:
    """
    Apply all active acp_output_rules for the given stage and tenant.

    Mutates output dict in place and appends:
      output["review_flags"]  — list of flagged rule dicts
      output["rules_applied"] — list of rule_id strings that triggered

    Raises OutputRuleViolation for block or score_gate rule types.
    """
    rules = await db.fetch(
        """SELECT rule_id::text, rule_type, pattern, action_value, error_message
           FROM acp_shared.acp_output_rules
           WHERE is_active = TRUE
             AND (stage = $1 OR stage IS NULL)
             AND (tenant_id = $2::uuid OR tenant_id IS NULL)
           ORDER BY source_type ASC, created_at ASC""",
        stage,
        tenant_id,
    )

    review_flags: list[dict] = []
    rules_applied: list[str] = []
    content: str = output.get("content", "") or output.get("content_md", "") or ""

    for rule in rules:
        rule_id = rule["rule_id"]
        rule_type = rule["rule_type"]
        pattern = (rule["pattern"] or "").lower()
        action_value = rule["action_value"] or ""
        error_msg = rule["error_message"] or f"Rule {rule_id} ({rule_type}) violated"

        if not pattern:
            continue

        triggered = pattern in content.lower()
        if not triggered:
            continue

        rules_applied.append(rule_id)
        await db.execute(
            "UPDATE acp_shared.acp_output_rules SET run_count = run_count + 1 WHERE rule_id = $1::uuid",
            rule_id,
        )

        if rule_type == "block":
            raise OutputRuleViolation(rule_id, rule_type, error_msg)

        elif rule_type == "replace":
            replacement = action_value
            content = re.sub(re.escape(pattern), replacement, content, flags=re.IGNORECASE)
            if "content_md" in output:
                output["content_md"] = content
            else:
                output["content"] = content

        elif rule_type == "flag":
            review_flags.append({
                "rule_id": rule_id,
                "pattern": pattern,
                "rule_type": rule_type,
                "message": error_msg,
            })

        elif rule_type == "score_gate":
            raise OutputRuleViolation(rule_id, rule_type, error_msg)

        elif rule_type == "truncate":
            try:
                max_len = int(action_value)
                target_field = pattern  # pattern = "seo_title" or "seo_meta"
                if target_field in output and len(output.get(target_field, "")) > max_len:
                    output[target_field] = output[target_field][:max_len]
            except (ValueError, TypeError):
                pass

    output["review_flags"] = review_flags
    output["rules_applied"] = rules_applied
    return output
