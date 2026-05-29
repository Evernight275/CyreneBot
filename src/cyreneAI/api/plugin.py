from __future__ import annotations

from cyreneAI.api._arguments import Arg, Flag, Option, Rest
from cyreneAI.api._depends import Depends, PluginDependency
from cyreneAI.api._replies import text
from cyreneAI.api._routing import CyreneBot, CyreneRouter
from cyreneAI.api._types import (
    PluginCommandAsyncGenerator,
    PluginCommandGenerator,
    PluginCommandHandler,
    PluginCommandHandlerResult,
    PluginCommandHandlerReturn,
    PluginEventHandler,
    PluginTaskHandler,
)


__all__ = [
    "CyreneBot",
    "CyreneRouter",
    "Depends",
    "PluginCommandAsyncGenerator",
    "PluginCommandGenerator",
    "PluginCommandHandler",
    "PluginCommandHandlerResult",
    "PluginCommandHandlerReturn",
    "PluginDependency",
    "PluginEventHandler",
    "PluginTaskHandler",
    "Arg",
    "Flag",
    "Option",
    "Rest",
    "text",
]
