from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Any

from cyreneAI.core.errors.plugin import (
    PluginConfigurationError,
    PluginError,
    PluginExecutionError,
    PluginInputError,
)
from cyreneAI.core.plugin.plugin_protocol import PluginSetupContextProtocol
from cyreneAI.core.schema.bot import BotAction, BotActionType, BotMessage
from cyreneAI.core.schema.message import ContentPart, ContentPartType
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginManifest,
)


PluginCommandHandler = Callable[
    [PluginCommandRequest, Any],
    PluginCommandResult | Awaitable[PluginCommandResult],
]


class CyreneBot:
    """
    第三方 bot 插件局部 router。
    """

    def __init__(self, manifest: PluginManifest | None = None) -> None:
        self._manifest = manifest
        self._routes: list[_CommandRoute] = []

    @property
    def manifest(self) -> PluginManifest:
        if self._manifest is None:
            raise PluginConfigurationError("插件缺少 plugin.json manifest")
        return self._manifest

    @property
    def routes(self) -> tuple[PluginCommandDefinition, ...]:
        return tuple(route.definition for route in self._routes)

    def configure(self, manifest: PluginManifest) -> "CyreneBot":
        """
        注入 plugin.json 清单。
        """
        self._manifest = manifest
        return self

    def command(
        self,
        path: str,
        *,
        description: str | None = None,
        usage: str | None = None,
        aliases: list[str] | None = None,
        admin_required: bool = False,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> Callable[[PluginCommandHandler], PluginCommandHandler]:
        """
        注册 bot 命令 handler。
        """
        command_name = _normalize_command_name(path)
        if not command_name:
            raise PluginConfigurationError("插件命令 path 必须包含命令名")

        def decorator(handler: PluginCommandHandler) -> PluginCommandHandler:
            command_description = description
            if command_description is None:
                command_description = _handler_description(handler)

            definition = PluginCommandDefinition(
                name=command_name,
                description=command_description,
                usage=usage or _default_usage(path),
                aliases=[
                    normalized_alias
                    for alias in aliases or []
                    if (normalized_alias := _normalize_command_name(alias))
                ],
                admin_required=admin_required,
                enabled=enabled,
                metadata=metadata or {},
            )
            self._routes.append(_CommandRoute(definition, handler))
            return handler

        return decorator

    def setup(self, context: PluginSetupContextProtocol) -> None:
        """
        将当前 router 中的命令注册到插件宿主。
        """
        for route in self._routes:
            context.register_command(
                route.definition,
                _CommandHandlerExecutor(route.handler, context.runtime),
            )


class _CommandRoute:
    def __init__(
        self,
        definition: PluginCommandDefinition,
        handler: PluginCommandHandler,
    ) -> None:
        self.definition = definition
        self.handler = handler


class _CommandHandlerExecutor:
    def __init__(
        self,
        handler: PluginCommandHandler,
        runtime_context: Any,
    ) -> None:
        self._handler = handler
        self._runtime_context = runtime_context

    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        try:
            result = self._handler(request, self._runtime_context)
            if isawaitable(result):
                result = await result
        except PluginError:
            raise
        except Exception as exc:
            raise PluginExecutionError(
                f"插件命令 {request.command.name} 执行失败",
                cause=exc,
            ) from exc

        if not isinstance(result, PluginCommandResult):
            raise PluginExecutionError(
                f"插件命令 {request.command.name} 必须返回 PluginCommandResult"
            )
        return result


def text(
    request: PluginCommandRequest,
    content: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> PluginCommandResult:
    """
    构造文本回复结果。
    """
    if request.event is None:
        raise PluginInputError("text reply requires request.event")

    action = BotAction(
        action_type=BotActionType.SEND_MESSAGE,
        channel_id=request.event.channel_id,
        session_id=request.event.session_id,
        recipient_id=request.event.user_id,
        thread_id=request.event.thread_id,
        message=BotMessage(
            sender_id="bot",
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=content,
                )
            ],
            metadata={
                "command": request.command.name,
                **(metadata or {}),
            },
        ),
        metadata={
            "bot_event_id": request.event.event_id,
            "command": request.command.name,
            **(metadata or {}),
        },
    )
    return PluginCommandResult(
        actions=[action],
        metadata=metadata or {},
    )


def _normalize_command_name(value: str) -> str:
    return value.strip().split(maxsplit=1)[0].removeprefix("/").lower()


def _default_usage(path: str) -> str:
    stripped = path.strip()
    if not stripped:
        return ""
    if stripped.startswith("/"):
        return stripped
    return f"/{stripped}"


def _handler_description(handler: PluginCommandHandler) -> str:
    doc = getattr(handler, "__doc__", None)
    if not doc:
        return ""
    return doc.strip().splitlines()[0].strip()
