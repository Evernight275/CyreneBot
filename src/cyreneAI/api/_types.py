from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from typing import Any, TypeAlias

from cyreneAI.core.schema.chat import ChatResponse
from cyreneAI.core.schema.plugin import (
    PluginCommandResult,
    PluginEventResult,
    PluginTaskResult,
)
from cyreneAI.core.schema.tool import ToolResult

PluginCommandHandlerResult: TypeAlias = str | PluginCommandResult
PluginCommandGenerator: TypeAlias = Generator[
    PluginCommandHandlerResult,
    None,
    Any,
]
PluginCommandAsyncGenerator: TypeAlias = AsyncGenerator[
    PluginCommandHandlerResult,
    None,
]
PluginCommandHandlerReturn: TypeAlias = (
    PluginCommandHandlerResult
    | PluginCommandGenerator
    | PluginCommandAsyncGenerator
    | Awaitable[PluginCommandHandlerResult]
)
PluginCommandHandler: TypeAlias = Callable[..., PluginCommandHandlerReturn]
PluginTaskHandler = Callable[
    ...,
    PluginTaskResult | None | Awaitable[PluginTaskResult | None],
]
PluginEventHandler = Callable[
    ...,
    PluginEventResult | None | Awaitable[PluginEventResult | None],
]
PluginMiddlewareNext = Callable[..., Awaitable[ChatResponse]]
PluginMiddlewareHandler = Callable[
    ...,
    ChatResponse | Awaitable[ChatResponse],
]
PluginToolHandlerResult: TypeAlias = str | dict[str, Any] | ToolResult
PluginToolHandler = Callable[
    ...,
    PluginToolHandlerResult | Awaitable[PluginToolHandlerResult],
]
