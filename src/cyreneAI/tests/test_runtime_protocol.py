from __future__ import annotations

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.runtime import CyreneAIRuntimeProtocol


def test_application_runtime_implements_core_runtime_protocol() -> None:
    runtime: CyreneAIRuntimeProtocol = CyreneAIRuntime(
        provider_manager=ProviderManager(ProviderFactory()),
        context_builder=ContextWindowBuilder(),
    )

    assert runtime.provider_manager.list_running() == []
