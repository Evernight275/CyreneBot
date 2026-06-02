from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, overload

from cyreneAI.core.errors.plugin import PluginConfigurationError
from cyreneAI.core.plugin.plugin_protocol import (
    PluginAgentNamespaceProtocol,
    PluginAssetsNamespaceProtocol,
    PluginLLMNamespaceProtocol,
    PluginOutboxNamespaceProtocol,
    PluginRuntimeContextProtocol,
    PluginStorageNamespaceProtocol,
    PluginTaskNamespaceProtocol,
)
from cyreneAI.core.schema.application import (
    ApplicationImageGenerationRequest,
    ApplicationImageGenerationResult,
)
from cyreneAI.core.schema.provider import ProviderInfo, ProviderModel
from cyreneAI.core.schema.plugin import (
    PluginCommandRequest,
    PluginEventRequest,
    PluginMiddlewareRequest,
    PluginPermission,
    PluginTaskRequest,
)


class PluginDependency:
    """
    插件 handler 依赖声明。
    """

    def __init__(self, name: str) -> None:
        normalized_name = name.strip().lower()
        if not normalized_name:
            raise PluginConfigurationError("插件依赖名称不能为空")
        self.name = normalized_name


@overload
def Depends(
    name: Literal["ctx", "context", "runtime"],
) -> PluginRuntimeContextProtocol: ...


@overload
def Depends(name: Literal["llm"]) -> PluginLLMNamespaceProtocol: ...


@overload
def Depends(name: Literal["agent"]) -> PluginAgentNamespaceProtocol: ...


@overload
def Depends(
    name: Literal["image", "generate_image"],
) -> Callable[
    [ApplicationImageGenerationRequest],
    Awaitable[ApplicationImageGenerationResult],
]: ...


@overload
def Depends(
    name: Literal["providers", "list_providers"],
) -> Callable[[], list[ProviderInfo]]: ...


@overload
def Depends(
    name: Literal["provider_models", "list_provider_models"],
) -> Callable[[str], Awaitable[list[ProviderModel]]]: ...


@overload
def Depends(name: Literal["storage"]) -> PluginStorageNamespaceProtocol: ...


@overload
def Depends(name: Literal["assets"]) -> PluginAssetsNamespaceProtocol: ...


@overload
def Depends(
    name: Literal["task", "tasks", "scheduler"],
) -> PluginTaskNamespaceProtocol: ...


@overload
def Depends(
    name: Literal["message", "messages", "outbox"],
) -> PluginOutboxNamespaceProtocol: ...


@overload
def Depends(name: str) -> Any: ...


def Depends(name: str) -> Any:
    """
    声明插件 handler 需要宿主注入的受控能力。
    """
    return PluginDependency(name)


def _resolve_dependency(
    dependency: PluginDependency,
    runtime_context: Any,
    request: (
        PluginCommandRequest
        | PluginTaskRequest
        | PluginEventRequest
        | PluginMiddlewareRequest
        | None
    ) = None,
) -> Any:
    if dependency.name in {"ctx", "context", "runtime"}:
        return runtime_context
    if dependency.name == "llm":
        runtime_context.require_permission(PluginPermission.LLM)
        llm_for_request = getattr(runtime_context, "llm_for_request", None)
        if llm_for_request is not None and request is not None:
            return llm_for_request(request)
        return runtime_context.llm
    if dependency.name == "agent":
        runtime_context.require_permission(PluginPermission.LLM)
        agent_for_request = getattr(runtime_context, "agent_for_request", None)
        if agent_for_request is not None and request is not None:
            return agent_for_request(request)
        return runtime_context.agent
    if dependency.name in {"image", "generate_image"}:
        runtime_context.require_permission(PluginPermission.IMAGE)
        return runtime_context.generate_image
    if dependency.name in {"providers", "list_providers"}:
        runtime_context.require_permission(PluginPermission.PROVIDER_READ)
        return runtime_context.list_providers
    if dependency.name in {"provider_models", "list_provider_models"}:
        runtime_context.require_permission(PluginPermission.PROVIDER_READ)
        return runtime_context.list_provider_models
    if dependency.name == "storage":
        return runtime_context.storage
    if dependency.name == "assets":
        return runtime_context.assets
    if dependency.name in {"task", "tasks", "scheduler"}:
        return runtime_context.tasks
    if dependency.name in {"message", "messages", "outbox"}:
        return runtime_context.messages
    raise PluginConfigurationError(f"未知插件依赖: {dependency.name}")
