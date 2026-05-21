"""
AA-49 H-1 — Isolated S4 Content Evaluator Lambda.

Receives ONLY raw blog text (no brand context, no outline, no DB access).
Returns multi-dimension quality scores + SHA256 hash of evaluated text.

Isolation guarantee: evaluator_input_hash proves what the evaluator saw.
No DB calls. No tenant context. Text-only payload.
"""
import json
import hashlib
import boto3
import os

BEDROCK = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-west-1"))
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

RUBRIC = """You are a strict content quality evaluator. You receive ONLY the raw text of a travel blog draft.
Score each dimension 1-10 (float). Return ONLY valid JSON, no preamble, no explanation.

Dimensions:
- readability: sentence clarity, flow, paragraph structure
- factual_trust: avoids unverifiable claims, no hallucinated facts
- engagement: hooks, storytelling, reader interest
- keyword_naturalness: keywords feel organic, not forced
- completeness: all sections present, logical conclusion

Output schema (JSON only):
{"evaluator_score": <avg float 1-10>, "dimension_scores": {"readability": x,
"factual_trust": x, "engagement": x, "keyword_naturalness": x, "completeness": x},
"issues": ["<string>", ...]}"""


def lambda_handler(event, context):
    text = event.get("text", "")
    if not text or not text.strip():
        return {"statusCode": 400, "body": json.dumps({"error": "Missing or empty text field"})}

    evaluator_input_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    try:
        response = BEDROCK.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 512,
                "messages": [{"role": "user", "content": f"{RUBRIC}\n\nBlog text:\n{text}"}],
            }),
            contentType="application/json",
            accept="application/json",
        )
        raw = json.loads(response["body"].read())
        content_text = raw["content"][0]["text"].strip()

        # Strip markdown fences if LLM wraps JSON
        if content_text.startswith("```"):
            parts = content_text.split("```")
            content_text = parts[1]
            if content_text.startswith("json"):
                content_text = content_text[4:]
            content_text = content_text.strip()

        result = json.loads(content_text)
        required = {"evaluator_score", "dimension_scores", "issues"}
        if not required.issubset(result.keys()):
            missing = list(required - result.keys())
            return {"statusCode": 500, "body": json.dumps({"error": f"LLM response missing fields: {missing}"})}
        result["evaluator_input_hash"] = evaluator_input_hash
        return {"statusCode": 200, "body": json.dumps(result)}

    except json.JSONDecodeError as e:
        return {"statusCode": 500, "body": json.dumps({"error": f"LLM returned invalid JSON: {e}"})}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
