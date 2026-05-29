from __future__ import annotations

from datetime import datetime
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
    TASK = "task"
    EVENT = "event"


class PluginPermission(StrEnum):
    """
    第三方插件可申请的运行时权限。
    """

    LLM = "llm"
    CHAT = "chat"
    IMAGE = "image"
    PROVIDER_READ = "provider_read"
    PROVIDER_WRITE = "provider_write"
    ADMIN = "admin"
    TOOL = "tool"
    SKILL = "skill"
    RAG = "rag"
    STORAGE = "storage"
    ASSETS = "assets"
    TASK = "task"
    MESSAGE_SEND = "message_send"
    MESSAGE_SEND_UNLIMITED = "message_send_unlimited"
    NETWORK = "network"


class PluginRuntimeCapabilityStatus(StrEnum):
    """
    插件运行时权限或依赖的宿主支持状态。
    """

    SUPPORTED = "supported"
    RESERVED = "reserved"
    NOT_IMPLEMENTED = "not_implemented"


class PluginLifecycleStatus(StrEnum):
    """
    插件在宿主内的加载生命周期状态。
    """

    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    FAILED = "failed"


class PluginTaskStatus(StrEnum):
    """
    插件受管任务实例状态。
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class PluginEventType(StrEnum):
    """
    插件可订阅的窄事件类型。
    """

    MESSAGE = "message"
    COMMAND = "command"
    MEMBER_JOINED = "member_joined"
    MEMBER_LEFT = "member_left"
    UNKNOWN = "unknown"


class PluginCommandArgumentKind(StrEnum):
    """
    插件命令参数的解析形态。
    """

    POSITIONAL = "positional"
    REST = "rest"
    OPTION = "option"
    FLAG = "flag"


class PluginCommandArgumentDefinition(PluginBase):
    """
    插件命令 handler 参数契约。
    """

    name: str
    type: str = "str"
    kind: PluginCommandArgumentKind = PluginCommandArgumentKind.POSITIONAL
    required: bool = True
    default: Any | None = None
    aliases: list[str] = Field(default_factory=list)
    choices: list[Any] = Field(default_factory=list)
    description: str = ""


class PluginCommandDefinition(PluginBase):
    """
    插件暴露给 bot 的命令定义。
    """

    name: str
    description: str
    usage: str | None = None
    arguments: list[PluginCommandArgumentDefinition] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    admin_required: bool = False
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginTaskDefinition(PluginBase):
    """
    插件声明的受管后台任务定义。
    """

    name: str
    description: str = ""
    interval_seconds: float | None = None
    daily_at: str | None = None
    run_on_start: bool = False
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginEventDefinition(PluginBase):
    """
    插件声明的事件订阅定义。
    """

    event_type: PluginEventType
    description: str = ""
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
    tasks: list[PluginTaskDefinition] = Field(default_factory=list)
    events: list[PluginEventDefinition] = Field(default_factory=list)
    enabled: bool = True
    builtin: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginRuntimePermissionInfo(PluginBase):
    """
    插件权限与宿主运行时能力的对应说明。
    """

    permission: PluginPermission
    status: PluginRuntimeCapabilityStatus
    dependencies: list[str] = Field(default_factory=list)
    setup_apis: list[str] = Field(default_factory=list)
    description: str = ""


class PluginRuntimeDependencyInfo(PluginBase):
    """
    Depends(...) 可注入依赖与权限的对应说明。
    """

    name: str
    status: PluginRuntimeCapabilityStatus
    permission: PluginPermission | None = None
    description: str = ""


class PluginStatusReport(PluginBase):
    """
    插件运行时状态报告。
    """

    plugin_id: str
    status: PluginLifecycleStatus
    enabled: bool = False
    name: str | None = None
    version: str | None = None
    reason: str | None = None
    error: str | None = None


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
    tasks: list[PluginTaskDefinition] = Field(default_factory=list)
    events: list[PluginEventDefinition] = Field(default_factory=list)
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
            tasks=list(self.tasks),
            events=list(self.events),
            enabled=self.enabled,
            builtin=self.builtin,
            metadata=dict(self.metadata),
        )


class PluginTaskRequest(PluginBase):
    """
    插件后台任务执行请求。
    """

    task: PluginTaskDefinition
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginTaskResult(PluginBase):
    """
    插件后台任务执行结果。
    """

    handled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginScheduledTask(PluginBase):
    """
    插件受管任务实例记录。
    """

    task_id: str
    plugin_id: str
    task_name: str
    run_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    key: str | None = None
    status: PluginTaskStatus = PluginTaskStatus.PENDING
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class PluginEvent(PluginBase):
    """
    插件 handler 接收的窄事件对象。

    该对象只暴露插件需要的会话与消息字段，不携带 channel adapter 的原始
    payload 或平台私有 metadata。
    """

    event_id: str
    event_type: PluginEventType
    session_id: str
    user_id: str | None = None
    thread_id: str | None = None
    message_id: str | None = None
    text: str | None = None


class PluginEventRequest(PluginBase):
    """
    插件事件执行请求。
    """

    route: PluginEventDefinition
    event: PluginEvent
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginEventResult(PluginBase):
    """
    插件事件执行结果。
    """

    handled: bool = True
    actions: list[BotAction] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginMessageReceipt(PluginBase):
    """
    插件出站消息发送回执。
    """

    session_id: str
    accepted: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


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
