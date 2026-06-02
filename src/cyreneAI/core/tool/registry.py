from __future__ import annotations

from cyreneAI.core.errors.base import ConflictError
from cyreneAI.core.errors.tool import ToolNotFoundError
from cyreneAI.core.schema.tool import ToolDefinition
from cyreneAI.core.tool.tool_protocol import ToolExecutorProtocol


class ToolRegistry:
    """
    工具注册器
    """

    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._executors: dict[str, ToolExecutorProtocol] = {}
        self._disabled_names: set[str] = set()

    def register(
        self,
        definition: ToolDefinition,
        executor: ToolExecutorProtocol,
    ) -> None:
        """
        注册工具
        """
        if definition.name in self._definitions:
            raise ConflictError(f"该工具 {definition.name} 已注册")
        self._definitions[definition.name] = definition
        self._executors[definition.name] = executor

    def unregister(self, name: str) -> None:
        """
        注销工具
        """
        if name not in self._definitions:
            raise ToolNotFoundError(f"该工具 {name} 不存在")
        self._definitions.pop(name, None)
        self._executors.pop(name, None)
        self._disabled_names.discard(name)

    def get_definition(self, name: str) -> ToolDefinition:
        """
        获取工具定义
        """
        definition = self._definitions.get(name)
        if definition is None:
            raise ToolNotFoundError(f"该工具 {name} 不存在")
        return definition

    def get_executor(self, name: str) -> ToolExecutorProtocol:
        """
        获取工具执行器
        """
        executor = self._executors.get(name)
        if executor is None:
            raise ToolNotFoundError(f"该工具 {name} 不存在")
        return executor

    def exists(self, name: str) -> bool:
        """
        判断工具是否存在
        """
        return name in self._definitions

    def set_enabled(self, name: str, enabled: bool) -> ToolDefinition:
        """
        启用或禁用工具。
        """
        definition = self.get_definition(name)
        if enabled:
            self._disabled_names.discard(name)
        else:
            self._disabled_names.add(name)
        return definition

    def is_enabled(self, name: str) -> bool:
        """
        判断工具是否启用。
        """
        if name not in self._definitions:
            raise ToolNotFoundError(f"该工具 {name} 不存在")
        return name not in self._disabled_names

    def enabled_names(self) -> set[str]:
        """
        返回当前启用工具名。
        """
        return set(self._definitions) - self._disabled_names

    def list_definitions(self) -> list[ToolDefinition]:
        """
        列出工具定义
        """
        return list(self._definitions.values())

    def list_enabled_definitions(self) -> list[ToolDefinition]:
        """
        列出当前启用工具定义。
        """
        return [
            definition
            for definition in self._definitions.values()
            if definition.name not in self._disabled_names
        ]
