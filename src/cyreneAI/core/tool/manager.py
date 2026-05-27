from __future__ import annotations

from cyreneAI.core.schema.tool import ToolCall, ToolResult
from cyreneAI.core.tool.tool_protocol import ToolRegistryProtocol
from cyreneAI.core.tool.validation import validate_tool_call_arguments


class ToolManager:
    """
    工具运行管理器
    """

    def __init__(self, registry: ToolRegistryProtocol) -> None:
        self._registry = registry

    async def execute(self, call: ToolCall) -> ToolResult:
        """
        执行工具调用
        """
        definition = self._registry.get_definition(call.name)
        validate_tool_call_arguments(definition=definition, call=call)
        executor = self._registry.get_executor(call.name)
        return await executor.execute(call)

    def exists(self, name: str) -> bool:
        """
        判断工具是否存在
        """
        return self._registry.exists(name)
