from __future__ import annotations

from cyreneAI.api import (
    Arg,
    CyreneBot,
    CyreneRouter,
    Depends,
    Flag,
    Option,
    PluginTestClient,
    PluginTestCommandResult,
    PluginTestEventResult,
    PluginTestTaskResult,
    Rest,
    text,
)
from cyreneAI.api.plugin import (
    Arg as PluginArg,
    CyreneBot as PluginCyreneBot,
    CyreneRouter as PluginCyreneRouter,
    Depends as plugin_depends,
    Flag as PluginFlag,
    Option as PluginOption,
    Rest as PluginRest,
    text as plugin_text,
)
from cyreneAI.api.testing import (
    PluginTestClient as TestingPluginTestClient,
    PluginTestCommandResult as TestingPluginTestCommandResult,
    PluginTestEventResult as TestingPluginTestEventResult,
    PluginTestTaskResult as TestingPluginTestTaskResult,
)


def test_public_api_facade_exports_plugin_dsl() -> None:
    assert Arg is PluginArg
    assert CyreneBot is PluginCyreneBot
    assert CyreneRouter is PluginCyreneRouter
    assert Depends is plugin_depends
    assert Flag is PluginFlag
    assert Option is PluginOption
    assert Rest is PluginRest
    assert text is plugin_text
    assert PluginTestClient is TestingPluginTestClient
    assert PluginTestCommandResult is TestingPluginTestCommandResult
    assert PluginTestEventResult is TestingPluginTestEventResult
    assert PluginTestTaskResult is TestingPluginTestTaskResult
