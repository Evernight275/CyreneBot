from __future__ import annotations

from cyreneAI.core.errors.base import CyreneAIError
from cyreneAI.core.errors.plugin import (
    PluginAuthorizationError,
    PluginError,
    PluginExecutionError,
)
from cyreneAI.core.plugin.plugin_protocol import PluginRegistryProtocol
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
)


class PluginManager:
    """
    插件管理器。
    """

    def __init__(self, registry: PluginRegistryProtocol) -> None:
        self._registry = registry

    def list_plugins(self) -> list[PluginDefinition]:
        """
        列出插件。
        """
        return self._registry.list_definitions()

    def list_commands(self) -> list[PluginCommandDefinition]:
        """
        列出插件命令。
        """
        return self._registry.list_commands()

    async def execute_command(
        self,
        request: PluginCommandRequest,
    ) -> PluginCommandResult:
        """
        执行插件命令。
        """
        _, command, executor = self._registry.resolve_command(request.command.name)
        if command.admin_required and not request.is_admin:
            raise PluginAuthorizationError(
                f"插件命令 {command.name} 需要管理员权限"
            )

        try:
            return await executor.execute(request)
        except PluginError:
            raise
        except CyreneAIError:
            raise
        except Exception as exc:
            raise PluginExecutionError(
                f"插件命令 {command.name} 执行失败",
                cause=exc,
            ) from exc
