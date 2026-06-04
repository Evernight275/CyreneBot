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
)
from cyreneAI.api.plugin import (
    CyreneBot as PluginCyreneBot,
)
from cyreneAI.api.plugin import (
    CyreneRouter as PluginCyreneRouter,
)
from cyreneAI.api.plugin import (
    Depends as plugin_depends,
)
from cyreneAI.api.plugin import (
    Flag as PluginFlag,
)
from cyreneAI.api.plugin import (
    Option as PluginOption,
)
from cyreneAI.api.plugin import (
    Rest as PluginRest,
)
from cyreneAI.api.plugin import (
    text as plugin_text,
)
from cyreneAI.api.testing import (
    PluginTestClient as TestingPluginTestClient,
)
from cyreneAI.api.testing import (
    PluginTestCommandResult as TestingPluginTestCommandResult,
)
from cyreneAI.api.testing import (
    PluginTestEventResult as TestingPluginTestEventResult,
)
from cyreneAI.api.testing import (
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
