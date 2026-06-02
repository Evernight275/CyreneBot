from __future__ import annotations

from typing import Protocol

from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolResult,
)


class ToolExecutorProtocol(Protocol):
    """
    工具执行器协议
    """

    async def execute(self, call: ToolCall) -> ToolResult:
        """
        执行工具调用
        """
        ...


class ToolRegistryProtocol(Protocol):
    """
    工具注册器协议
    """

    def register(self, definition: ToolDefinition, executor: ToolExecutorProtocol) -> None:
        """
        注册工具
        """
        ...

    def unregister(self, name: str) -> None:
        """
        注销工具
        """
        ...

    def get_definition(self, name: str) -> ToolDefinition:
        """
        获取工具定义
        """
        ...

    def get_executor(self, name: str) -> ToolExecutorProtocol:
        """
        获取工具执行器
        """
        ...

    def exists(self, name: str) -> bool:
        """
        判断工具是否存在
        """
        ...

    def set_enabled(self, name: str, enabled: bool) -> ToolDefinition:
        """
        启用或禁用工具。
        """
        ...

    def is_enabled(self, name: str) -> bool:
        """
        判断工具是否启用。
        """
        ...

    def list_definitions(self) -> list[ToolDefinition]:
        """
        列出工具定义
        """
        ...

    def list_enabled_definitions(self) -> list[ToolDefinition]:
        """
        列出当前启用工具定义。
        """
        ...


class ToolSandboxRunnerProtocol(Protocol):
    """
    工具沙箱运行器协议。
    """

    async def execute(
        self,
        *,
        call: ToolCall,
        definition: ToolDefinition,
        executor: ToolExecutorProtocol,
        policy: ToolExecutionPolicy,
    ) -> ToolResult:
        """
        在受控执行环境中执行工具调用。
        """
        ...
