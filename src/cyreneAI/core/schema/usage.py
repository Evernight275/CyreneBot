from __future__ import annotations

from cyreneAI.core.schema.base import CyreneAISchema


class TokenUsage(CyreneAISchema):
    """
    令牌消耗schema，极有可能没有所有字段，故None表示非常有必要
    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
