from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.bot import BotAction, BotCommand, BotEvent


class PluginBase(CyreneAISchema):
    """
    所有插件相关 schema 应该继承这个 schema。
    """

    pass


class PluginCapability(StrEnum):
    """
    插件声明的能力类型。
    """

    BOT_COMMAND = "bot_command"
    CHAT = "chat"
    IMAGE = "image"
    PROVIDER = "provider"
    STATUS = "status"
    ADMIN = "admin"
    RAG = "rag"
    TOOL = "tool"
    SKILL = "skill"


class PluginPermission(StrEnum):
    """
    第三方插件可申请的运行时权限。
    """

    CHAT = "chat"
    IMAGE = "image"
    PROVIDER_READ = "provider_read"
    PROVIDER_WRITE = "provider_write"
    ADMIN = "admin"
    TOOL = "tool"
    SKILL = "skill"
    RAG = "rag"
    STORAGE = "storage"
    NETWORK = "network"


class PluginCommandDefinition(PluginBase):
    """
    插件暴露给 bot 的命令定义。
    """

    name: str
    description: str
    usage: str | None = None
    aliases: list[str] = Field(default_factory=list)
    admin_required: bool = False
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginDefinition(PluginBase):
    """
    插件清单定义。
    """

    plugin_id: str
    name: str
    description: str
    version: str = "0.1.0"
    author: str | None = None
    license: str | None = None
    homepage: str | None = None
    repository: str | None = None
    keywords: list[str] = Field(default_factory=list)
    capabilities: list[PluginCapability] = Field(default_factory=list)
    permissions: list[PluginPermission] = Field(default_factory=list)
    commands: list[PluginCommandDefinition] = Field(default_factory=list)
    enabled: bool = True
    builtin: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginManifest(PluginBase):
    """
    第三方插件清单。
    """

    plugin_id: str
    name: str
    description: str
    entrypoint: str
    version: str = "0.1.0"
    author: str | None = None
    license: str | None = None
    homepage: str | None = None
    repository: str | None = None
    keywords: list[str] = Field(default_factory=list)
    capabilities: list[PluginCapability] = Field(default_factory=list)
    permissions: list[PluginPermission] = Field(default_factory=list)
    commands: list[PluginCommandDefinition] = Field(default_factory=list)
    enabled: bool = True
    builtin: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_definition(self) -> PluginDefinition:
        """
        转换为运行时插件定义。
        """
        return PluginDefinition(
            plugin_id=self.plugin_id,
            name=self.name,
            description=self.description,
            version=self.version,
            author=self.author,
            license=self.license,
            homepage=self.homepage,
            repository=self.repository,
            keywords=list(self.keywords),
            capabilities=list(self.capabilities),
            permissions=list(self.permissions),
            commands=list(self.commands),
            enabled=self.enabled,
            builtin=self.builtin,
            metadata=dict(self.metadata),
        )


class PluginCommandRequest(PluginBase):
    """
    插件命令执行请求。
    """

    command: BotCommand
    event: BotEvent | None = None
    is_admin: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginCommandResult(PluginBase):
    """
    插件命令执行结果。
    """

    handled: bool = True
    actions: list[BotAction] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
