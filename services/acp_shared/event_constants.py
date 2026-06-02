"""
EventBridge source + detail-type constants for the ACP pipeline.

Rules that match events on aa-cis-dev-acp-events must use these exact strings.
Never hardcode source/detail-type strings outside this file.
"""


class ACPEventSource:
    S0 = "acp.s0"
    S1 = "acp.s1"
    S2 = "acp.s2"
    S3 = "acp.s3"
    S4_BLOG = "acp.s4_blog"
    S4_SOCIAL = "acp.s4_social"
    HITL = "acp.hitl"


class ACPEventDetailType:
    S0_COMPLETED = "acp.s0.completed"
    S1_COMPLETED = "acp.s1.completed"
    S2_COMPLETED = "acp.s2.completed"
    S3_COMPLETED = "acp.s3.completed"
    S4_BLOG_COMPLETED = "acp.s4_blog.completed"
    S4_SOCIAL_COMPLETED = "acp.s4_social.completed"
    HITL_APPROVED = "acp.hitl.approved"
    HITL_REJECTED = "acp.hitl.rejected"
    RUN_FAILED = "acp.run.failed"
