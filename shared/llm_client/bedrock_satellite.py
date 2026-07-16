"""
shared/llm_client/bedrock_satellite.py — AA-296 Satellite Bedrock client
ADDITIVE: Bedrock satellite là primary writer, GPT-4.1 giữ nguyên làm fallback.
KHÔNG xoá/sửa code GPT-4.1 hiện tại — chỉ thêm nhánh mới trước nó, caller quyết định fallback.

STATUS: VERIFIED THẬT qua terminal độc lập 16/07/2026 — cả Sonnet 4.6 lẫn Haiku 4.5
invoke thành công qua satellite chain. Đã dọn trust policy (bỏ statement debug tạm).

═══════════════════════════════════════════════════════════════════════════
⚠️ BUG QUAN TRỌNG ĐÃ PHÁT HIỆN (16/07/2026) — ĐỌC TRƯỚC KHI SỬA FILE NÀY:

Khi gọi bedrock:InvokeModel qua một ASSUMED-ROLE session (STS AssumeRole,
chính là cơ chế satellite này dùng), Bedrock IAM evaluation dùng dạng ARN
foundation-model KHÔNG CÓ REGION:
    arn:aws:bedrock:::foundation-model/anthropic.claude-sonnet-4-6
                     ^^ region rỗng, 3 dấu : liền nhau

...KHÁC với dạng CÓ region mà CloudTrail/Console luôn hiển thị:
    arn:aws:bedrock:us-west-1::foundation-model/anthropic.claude-sonnet-4-6

Không có tài liệu AWS chính thức nào mô tả rõ hành vi này. Phát hiện được
bằng thực nghiệm: gọi trực tiếp từ terminal (ngoài ECS/container), test cả
2 dạng ARN riêng lẻ rồi cùng lúc — chỉ khi policy có ĐỦ CẢ 2 dạng thì
invoke mới thành công nhất quán.

⇒ IAM permission policy trên role AA-Bedrock-Invoker (acc1) PHẢI có cả 2
  dạng ARN cho mỗi model, không chỉ 1. Nếu sau này thêm model mới (không
  chỉ Sonnet 4.6/Haiku 4.5), nhớ thêm CẢ 2 dạng ARN vào policy, không chỉ
  dạng có region như trực giác thường làm.

⚠️ Đừng tin errorMessage (free text) khi debug AccessDeniedException từ
  Bedrock qua assumed-role — nó có thể hiển thị SAI dạng ARN đang thực sự
  được đánh giá (đã quan sát: cùng policy, cùng request, error text đổi
  qua lại giữa 2 dạng không theo quy luật). Tin resources[].ARN trong
  CloudTrail (structured field) nếu cần đối chiếu, không tin câu chữ.
═══════════════════════════════════════════════════════════════════════════

STEP 0 verified (16/07/2026):
- Role acc1: arn:aws:iam::867490540162:role/AA-Bedrock-Invoker
  trust: CHỈ arn:aws:iam::005097885195:role/aa-cis-dev-ecs-task-role,
         Condition StringEquals sts:ExternalId=aa296-satellite-bedrock
  permission (policy InvokeApprovedClaudeModelsOnly): bedrock:InvokeModel +
  InvokeModelWithResponseStream, scoped 6 Resource ARN (2 model × 3 dạng:
  inference-profile, foundation-model+region, foundation-model region-rỗng)
- Role acc2: aa-cis-dev-ecs-task-role có inline policy RIÊNG
  (aa-cis-dev-ecs-assume-bedrock-invoker, KHÔNG đụng policy cũ
  aa-cis-dev-ecs-task-policy) cho phép sts:AssumeRole đúng role acc1 trên.
- Inference profile prefix Claude = "global." (KHÔNG phải "us." như ghi cũ
  trong skill/memory trước AA-296 — đã xác nhận qua Console, tài liệu skill
  cần update).
- Response schema Anthropic-on-Bedrock: content[0].text, KHÔNG phải
  choices[].message.content như Writer/Palmyra (OpenAI-compatible) — nếu
  sau này thêm Palmyra vào cùng client, cần parser riêng theo provider.

TODO còn lại trước khi coi AA-296 hoàn tất production-ready:
[x] AssumeRole chain verify thật (qua S3, qua terminal độc lập)
[x] Invoke Sonnet 4.6 + Haiku 4.5 thành công (terminal độc lập)
[ ] Cache SessionToken theo TTL trong code thật (không AssumeRole mỗi request)
[ ] CloudWatch metric t3_fallback_used khi rơi về GPT-4.1
[ ] Unit test: mock STS + Bedrock, verify fallback path khi satellite lỗi
[ ] Tích hợp vào S1 rewrite node thật (services/content_generation/ hoặc
    tương đương) — file này mới chỉ là client, chưa gọi từ pipeline
[ ] Update skill aa-ecosys-repos / ai-nghiep với bài học "2-dạng ARN" này
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------- config
ACC1_ROLE_ARN = "arn:aws:iam::867490540162:role/AA-Bedrock-Invoker"
ACC1_EXTERNAL_ID = "aa296-satellite-bedrock"
ACC1_REGION = "us-west-1"

INFERENCE_PROFILE_SONNET = "arn:aws:bedrock:us-west-1:867490540162:inference-profile/global.anthropic.claude-sonnet-4-6"
INFERENCE_PROFILE_HAIKU = (
    "arn:aws:bedrock:us-west-1:867490540162:inference-profile/"
    "global.anthropic.claude-haiku-4-5-20251001-v1:0"
)

ANTHROPIC_VERSION = "bedrock-2023-05-31"

# session cache — tránh gọi AssumeRole mỗi request (STS session mặc định 1h,
# nhưng role có MaxSessionDuration=3600s — xem Console AA-Bedrock-Invoker)
_cached_session: Optional[boto3.Session] = None
_cached_session_expiry: float = 0.0
_SESSION_REFRESH_MARGIN_SECONDS = 300  # refresh 5 phút trước khi hết hạn thật


class BedrockUnavailable(Exception):
    """Caller (pipeline node) bắt exception này → gọi fallback GPT-4.1 hiện có.
    KHÔNG để lỗi satellite (AssumeRole fail, InvokeModel fail, network...)
    làm crash request người dùng — luôn có đường lui GPT-4.1."""
    pass


@dataclass
class BedrockInvokeResult:
    text: str
    model_used: str          # "sonnet-4-6" | "haiku-4-5"
    latency_ms: float
    usage: dict


def _get_satellite_session() -> boto3.Session:
    """STS AssumeRole vào acc1, cache theo TTL."""
    global _cached_session, _cached_session_expiry
    now = time.time()
    if _cached_session is not None and now < _cached_session_expiry:
        return _cached_session

    sts = boto3.client("sts")  # dùng identity ECS task role hiện tại (acc2)
    try:
        resp = sts.assume_role(
            RoleArn=ACC1_ROLE_ARN,
            RoleSessionName=f"aa-cis-ecs-{int(now)}",
            ExternalId=ACC1_EXTERNAL_ID,
            DurationSeconds=3600,
        )
    except ClientError as e:
        raise BedrockUnavailable(f"AssumeRole to satellite failed: {e}") from e

    creds = resp["Credentials"]
    _cached_session = boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=ACC1_REGION,
    )
    _cached_session_expiry = creds["Expiration"].timestamp() - _SESSION_REFRESH_MARGIN_SECONDS
    return _cached_session


def invoke_claude(
    prompt: str,
    model: str = "sonnet",
    max_tokens: int = 4096,
    system: Optional[str] = None,
) -> BedrockInvokeResult:
    """
    model: "sonnet" (editorial, S1 rewrite) | "haiku" (schema/fast tasks)
    system: system prompt riêng (brand rules, JSON-schema instructions...).
      QUAN TRỌNG — AA-296 review (16/07/2026): field này BẮT BUỘC phải truyền
      khi gọi từ pipeline S1 rewrite thật. _call_bedrock (acc2, T1) gửi
      system tách biệt qua build_cached_system_prompt — nếu invoke_claude()
      không nhận và forward đúng field system của Anthropic Messages API,
      brand rules sẽ ÂM THẦM BỊ MẤT khi nhánh satellite (T1.5) kích hoạt,
      KHÔNG có lỗi nào báo — chỉ là output tệ đi không rõ nguyên nhân.
      Không nối system vào đầu prompt (user message) — Anthropic xử lý
      system khác ưu tiên/ngữ nghĩa so với user turn, nối vào sẽ giảm độ
      tuân thủ brand rules so với cách acc2/T1 đang làm.
    Raise BedrockUnavailable khi lỗi — caller ở lớp trên (pipeline node)
    chịu trách nhiệm bắt exception này và gọi fallback GPT-4.1 hiện có
    (KHÔNG sửa code GPT-4.1 đang chạy, chỉ thêm nhánh gọi hàm này trước).
    """
    inference_profile = INFERENCE_PROFILE_SONNET if model == "sonnet" else INFERENCE_PROFILE_HAIKU
    model_label = "sonnet-4-6" if model == "sonnet" else "haiku-4-5"

    t0 = time.time()
    try:
        session = _get_satellite_session()
        bedrock_rt = session.client("bedrock-runtime", region_name=ACC1_REGION)

        body_dict = {
            "anthropic_version": ANTHROPIC_VERSION,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body_dict["system"] = system  # field riêng, đúng chuẩn Anthropic Messages API
        body = json.dumps(body_dict)
        resp = bedrock_rt.invoke_model(
            modelId=inference_profile,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        latency_ms = (time.time() - t0) * 1000
        payload = json.loads(resp["body"].read())
        text = payload["content"][0]["text"]
        usage = payload.get("usage", {})

        return BedrockInvokeResult(
            text=text,
            model_used=model_label,
            latency_ms=round(latency_ms, 1),
            usage=usage,
        )
    except BedrockUnavailable:
        raise  # đã đúng loại exception, propagate thẳng
    except Exception as e:
        latency_ms = (time.time() - t0) * 1000
        # TODO: emit CloudWatch metric t3_fallback_used=1 ở đây trước khi raise
        raise BedrockUnavailable(f"Satellite Bedrock invoke failed ({model_label}): {type(e).__name__}: {e}") from e
