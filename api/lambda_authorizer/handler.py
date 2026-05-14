import json
import os
import hashlib
import psycopg2


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _generate_policy(effect: str, resource: str, context: dict = None):
    policy = {
        "principalId": context.get("tenantId", "unknown") if context else "unknown",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{
                "Action": "execute-api:Invoke",
                "Effect": effect,
                "Resource": resource
            }]
        }
    }
    if context:
        policy["context"] = context
    return policy


def lambda_handler(event, context):
    token = event.get("authorizationToken", "")
    method_arn = event.get("methodArn", "")

    if not token:
        raise Exception("Unauthorized")

    # Wildcard ARN to allow all methods for this tenant's stage
    arn_parts = method_arn.split(":")
    region = arn_parts[3]
    account = arn_parts[4]
    api_stage = "/".join(method_arn.split("/")[:2])
    wildcard_arn = f"{api_stage}/*/*"

    db_url = os.environ["DATABASE_URL"]
    key_hash = _hash_key(token)

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT tenant_id, slug, plan_tier, rate_limit_rpm, is_active
            FROM shared.tenants
            WHERE api_key_hash = %s
        """, (key_hash,))
        row = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB error: {e}")
        raise Exception("Unauthorized")

    if not row or not row[4]:  # not found or inactive
        return _generate_policy("Deny", method_arn)

    tenant_id, slug, plan_tier, rate_limit_rpm, is_active = row

    return _generate_policy("Allow", wildcard_arn, {
        "tenantId": str(tenant_id),
        "tenantSlug": slug,
        "planTier": str(plan_tier),
        "rateLimitRpm": str(rate_limit_rpm)
    })
