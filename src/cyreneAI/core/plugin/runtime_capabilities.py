from __future__ import annotations

from cyreneAI.core.schema.plugin import (
    PluginPermission,
    PluginRuntimeCapabilityStatus,
    PluginRuntimeDependencyInfo,
    PluginRuntimePermissionInfo,
)


def list_plugin_runtime_permissions() -> list[PluginRuntimePermissionInfo]:
    """
    列出插件权限与当前宿主运行面支持状态。
    """
    return [
        PluginRuntimePermissionInfo(
            permission=PluginPermission.LLM,
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            dependencies=["llm", "agent"],
            description="Allows plugins to call host-managed LLM and agent namespaces.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.CHAT,
            status=PluginRuntimeCapabilityStatus.RESERVED,
            description="Reserved compatibility name; plugins should request llm instead.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.IMAGE,
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            dependencies=["image", "generate_image"],
            description="Allows plugins to call the application image orchestrator.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.PROVIDER_READ,
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            dependencies=[
                "providers",
                "list_providers",
                "provider_models",
                "list_provider_models",
            ],
            description="Allows plugins to inspect running providers and models.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.STORAGE,
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            dependencies=["storage"],
            description="Allows plugins to use their host-managed storage namespace.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.ASSETS,
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            dependencies=["assets"],
            description="Allows plugins to read their packaged asset namespace.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.TASK,
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            dependencies=["task", "tasks", "scheduler"],
            description="Allows plugins to schedule declared host-managed tasks.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.MESSAGE_SEND,
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            dependencies=["message", "messages", "outbox"],
            description="Allows plugins to send messages through the host outbox.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.MESSAGE_SEND_UNLIMITED,
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            dependencies=["message", "messages", "outbox"],
            description="Allows explicit outbox sends to bypass host rate limits.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.TOOL,
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            setup_apis=["register_tool"],
            description="Allows setup-time tool registration; no runtime dependency is exposed.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.SKILL,
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            setup_apis=["register_skill"],
            description="Allows setup-time skill registration; no runtime dependency is exposed.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.RAG,
            status=PluginRuntimeCapabilityStatus.RESERVED,
            description="Reserved until a narrow RAG runtime API is designed.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.PROVIDER_WRITE,
            status=PluginRuntimeCapabilityStatus.RESERVED,
            description="Reserved; plugins cannot mutate provider runtime configuration yet.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.ADMIN,
            status=PluginRuntimeCapabilityStatus.RESERVED,
            description="Reserved for future administrative plugin APIs.",
        ),
        PluginRuntimePermissionInfo(
            permission=PluginPermission.NETWORK,
            status=PluginRuntimeCapabilityStatus.RESERVED,
            description="Reserved; network access is not mediated by the host yet.",
        ),
    ]


def list_plugin_runtime_dependencies() -> list[PluginRuntimeDependencyInfo]:
    """
    列出 Depends(...) 可注入依赖与所需权限。
    """
    return [
        PluginRuntimeDependencyInfo(
            name="ctx",
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            description="Alias for the controlled runtime context.",
        ),
        PluginRuntimeDependencyInfo(
            name="context",
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            description="Alias for the controlled runtime context.",
        ),
        PluginRuntimeDependencyInfo(
            name="runtime",
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            description="Alias for the controlled runtime context.",
        ),
        PluginRuntimeDependencyInfo(
            name="llm",
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            permission=PluginPermission.LLM,
            description="Host-managed LLM namespace.",
        ),
        PluginRuntimeDependencyInfo(
            name="agent",
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            permission=PluginPermission.LLM,
            description="Host-managed Agent loop namespace.",
        ),
        PluginRuntimeDependencyInfo(
            name="generate_image",
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            permission=PluginPermission.IMAGE,
            description="Callable image generation orchestrator entrypoint.",
        ),
        PluginRuntimeDependencyInfo(
            name="list_providers",
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            permission=PluginPermission.PROVIDER_READ,
            description="Callable provider listing entrypoint.",
        ),
        PluginRuntimeDependencyInfo(
            name="list_provider_models",
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            permission=PluginPermission.PROVIDER_READ,
            description="Callable provider model listing entrypoint.",
        ),
        PluginRuntimeDependencyInfo(
            name="storage",
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            permission=PluginPermission.STORAGE,
            description="Host-managed plugin storage namespace.",
        ),
        PluginRuntimeDependencyInfo(
            name="assets",
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            permission=PluginPermission.ASSETS,
            description="Read-only packaged plugin asset namespace.",
        ),
        PluginRuntimeDependencyInfo(
            name="tasks",
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            permission=PluginPermission.TASK,
            description="Host-managed plugin task namespace.",
        ),
        PluginRuntimeDependencyInfo(
            name="outbox",
            status=PluginRuntimeCapabilityStatus.SUPPORTED,
            permission=PluginPermission.MESSAGE_SEND,
            description="Host-managed outbound message namespace.",
        ),
    ]


__all__ = [
    "list_plugin_runtime_dependencies",
    "list_plugin_runtime_permissions",
]
