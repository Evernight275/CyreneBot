from __future__ import annotations

from typing import Any, Protocol

from cyreneAI.core.schema.context import (
    ContextBudget,
    ContextBuildRequest,
    ContextBuildResult,
    ContextItem,
    ContextSnapshot,
    ContextWindow,
)
from cyreneAI.core.schema.message import Message


class ContextStoreProtocol(Protocol):
    """
    上下文存储协议
    """

    async def save_snapshot(self, snapshot: ContextSnapshot) -> None:
        """
        保存上下文快照
        """
        ...

    async def get_snapshot(self, snapshot_id: str) -> ContextSnapshot:
        """
        获取上下文快照
        """
        ...

    async def list_snapshots(self, session_id: str) -> list[ContextSnapshot]:
        """
        列出指定会话的上下文快照
        """
        ...

    async def delete_snapshot(self, snapshot_id: str) -> None:
        """
        删除上下文快照
        """
        ...

    async def delete_snapshots_for_session(self, session_id: str) -> int:
        """
        删除指定会话的全部上下文快照，返回删除数量。
        """
        ...


class ContextBuilderProtocol(Protocol):
    """
    上下文构建器协议
    """

    async def build(self, request: ContextBuildRequest) -> ContextBuildResult:
        """
        构建上下文窗口
        """
        ...


class ContextCompressorProtocol(Protocol):
    """
    上下文压缩器协议
    """

    async def compress(
        self,
        items: list[ContextItem],
        budget: ContextBudget | None = None,
    ) -> ContextItem:
        """
        压缩上下文条目
        """
        ...


class ContextRetrieverProtocol(Protocol):
    """
    上下文检索器协议
    """

    async def retrieve(
        self,
        *,
        session_id: str,
        query: str | None = None,
        limit: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[ContextItem]:
        """
        检索相关上下文条目
        """
        ...


class ContextTokenCounterProtocol(Protocol):
    """
    上下文 token 计数器协议
    """

    def count_message(self, message: Message) -> int:
        """
        计算消息 token 数
        """
        ...

    def count_item(self, item: ContextItem) -> int:
        """
        计算上下文条目 token 数
        """
        ...

    def count_window(self, window: ContextWindow) -> int:
        """
        计算上下文窗口 token 数
        """
        ...
