"""
Shared exception types for the ACP pipeline.
"""


class S1ContextNotReadyError(Exception):
    """Raised when S2 starts but acp_run_context.s1_keywords_used is absent or empty.

    This prevents S2 from running keyword research without anti-cannibalization data,
    which would cause keyword overlap with S1-published content.
    """
    pass
