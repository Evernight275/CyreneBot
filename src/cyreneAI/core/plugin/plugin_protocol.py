from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from cyreneAI.core.schema.application import (
    ApplicationChatResult,
    ApplicationImageGenerationRequest,
    ApplicationImageGenerationResult,
)
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
    PluginEvent,
    PluginEventDefinition,
    PluginEventRequest,
    PluginEventResult,
    PluginManifest,
    PluginMessageReceipt,
    PluginPermission,
    PluginScheduledTask,
    PluginStatusReport,
    PluginTaskDefinition,
    PluginTaskRequest,
    PluginTaskResult,
    PluginTaskStatus,
)
from cyreneAI.core.schema.provider import ProviderInfo, ProviderModel
from cyreneAI.core.schema.skill import SkillDefinition
from cyreneAI.core.schema.tool import ToolDefinition
from cyreneAI.core.tool.tool_protocol import ToolExecutorProtocol


class PluginExecutorProtocol(Protocol):
    """
    插件命令执行器协议。
    """

    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        """
        执行插件命令。
        """
        ...


class PluginTaskExecutorProtocol(Protocol):
    """
    插件后台任务执行器协议。
    """

    async def execute(self, request: PluginTaskRequest) -> PluginTaskResult:
        """
        执行插件后台任务。
        """
        ...


class PluginEventExecutorProtocol(Protocol):
    """
    插件事件执行器协议。
    """

    async def execute(self, request: PluginEventRequest) -> PluginEventResult:
        """
        执行插件事件 handler。
        """
        ...


class PluginLLMNamespaceProtocol(Protocol):
    """
    单个插件的受控 LLM 命名空间。
    """

    async def chat(
        self,
        prompt: str,
        *,
        provider_id: str | None = None,
        model: str | None = None,
        system: str | None = None,
        session_id: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        以最小文本输入调用 LLM，并返回首段文本回复。
        """
        ...

    async def result(
        self,
        prompt: str,
        *,
        provider_id: str | None = None,
        model: str | None = None,
        system: str | None = None,
        session_id: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApplicationChatResult:
        """
        调用 LLM 并返回完整 application chat 结果。
        """
        ...


class PluginRuntimeContextProtocol(Protocol):
    """
    第三方插件运行时上下文协议。
    """

    def require_permission(self, permission: PluginPermission) -> None:
        """
        要求插件具备指定权限。
        """
        ...

    async def generate_image(
        self,
        request: ApplicationImageGenerationRequest,
    ) -> ApplicationImageGenerationResult:
        """
        调用应用生图能力。
        """
        ...

    def list_providers(self) -> list[ProviderInfo]:
        """
        列出运行中的 provider。
        """
        ...

    async def list_provider_models(self, provider_id: str) -> list[ProviderModel]:
        """
        列出 provider 模型。
        """
        ...

    @property
    def llm(self) -> PluginLLMNamespaceProtocol:
        """
        当前插件的受控 LLM 命名空间。
        """
        ...

    @property
    def storage(self) -> "PluginStorageNamespaceProtocol":
        """
        当前插件的托管存储命名空间。
        """
        ...

    @property
    def assets(self) -> "PluginAssetsNamespaceProtocol":
        """
        当前插件的只读资产命名空间。
        """
        ...

    @property
    def tasks(self) -> "PluginTaskNamespaceProtocol":
        """
        当前插件的受管后台任务命名空间。
        """
        ...

    @property
    def messages(self) -> "PluginOutboxNamespaceProtocol":
        """
        当前插件的出站消息命名空间。
        """
        ...

    @property
    def outbox(self) -> "PluginOutboxNamespaceProtocol":
        """
        当前插件的出站消息命名空间。
        """
        ...


class PluginStorageNamespaceProtocol(Protocol):
    """
    单个插件的托管存储命名空间。
    """

    async def get(self, key: str, default: Any = None) -> Any:
        """
        读取插件状态。
        """
        ...

    async def set(self, key: str, value: Any) -> None:
        """
        写入插件状态。
        """
        ...

    async def delete(self, key: str) -> None:
        """
        删除插件状态。
        """
        ...

    async def update(
        self,
        key: str,
        updater: Callable[[Any], Any | Awaitable[Any]],
        default: Any = None,
    ) -> Any:
        """
        在宿主托管的事务锁内更新插件状态。
        """
        ...


class PluginStorageProtocol(Protocol):
    """
    插件托管存储根协议。
    """

    def namespace(self, plugin_id: str) -> PluginStorageNamespaceProtocol:
        """
        获取指定插件的隔离存储命名空间。
        """
        ...

    async def close(self) -> None:
        """
        关闭存储资源。
        """
        ...


class PluginAssetsNamespaceProtocol(Protocol):
    """
    单个插件的只读资产命名空间。
    """

    async def read_text(self, path: str) -> str:
        """
        读取文本资产。
        """
        ...

    async def read_bytes(self, path: str) -> bytes:
        """
        读取二进制资产。
        """
        ...

    async def exists(self, path: str) -> bool:
        """
        判断资产是否存在。
        """
        ...

    async def list(self, path: str = "") -> list[str]:
        """
        列出资产目录。
        """
        ...


class PluginAssetsProtocol(Protocol):
    """
    插件只读资产根协议。
    """

    def namespace(self, plugin_id: str) -> PluginAssetsNamespaceProtocol:
        """
        获取指定插件的资产命名空间。
        """
        ...

    async def close(self) -> None:
        """
        关闭资产资源。
        """
        ...


class PluginTaskNamespaceProtocol(Protocol):
    """
    单个插件的受管后台任务命名空间。
    """

    async def schedule_once(
        self,
        task_name: str,
        *,
        delay_seconds: float,
        payload: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> str:
        """
        调度一次已声明的插件任务。
        """
        ...

    async def cancel(self, task_id: str) -> None:
        """
        取消指定任务实例。
        """
        ...

    async def cancel_key(self, key: str) -> int:
        """
        取消指定业务 key 对应的任务实例。
        """
        ...


class PluginOutboxNamespaceProtocol(Protocol):
    """
    单个插件的出站消息命名空间。
    """

    async def send(
        self,
        session_id: str,
        *,
        text: str,
        metadata: dict[str, Any] | None = None,
        bypass_rate_limit: bool = False,
    ) -> PluginMessageReceipt:
        """
        发送一条文本消息到指定 bot 会话。
        """
        ...


class PluginOutboxProtocol(Protocol):
    """
    插件出站消息根协议。
    """

    def namespace(
        self,
        plugin_id: str,
        *,
        can_bypass_rate_limit: bool = False,
    ) -> PluginOutboxNamespaceProtocol:
        """
        获取指定插件的出站消息命名空间。
        """
        ...


class PluginTaskSchedulerProtocol(Protocol):
    """
    插件受管后台任务调度器协议。
    """

    def namespace(self, plugin_id: str) -> PluginTaskNamespaceProtocol:
        """
        获取指定插件的任务命名空间。
        """
        ...

    def register_task(
        self,
        plugin_id: str,
        definition: PluginTaskDefinition,
        executor: PluginTaskExecutorProtocol,
    ) -> None:
        """
        注册插件任务定义与执行器。
        """
        ...

    async def start(self) -> None:
        """
        启动调度器。
        """
        ...

    async def shutdown(self) -> None:
        """
        关闭调度器并取消受管任务。
        """
        ...


class PluginTaskStoreProtocol(Protocol):
    """
    插件受管后台任务实例持久化存储协议。
    """

    async def add_task(self, task: PluginScheduledTask) -> None:
        """
        保存待执行任务实例。
        """
        ...

    async def list_pending_tasks(
        self,
        *,
        plugin_id: str | None = None,
        task_name: str | None = None,
    ) -> list[PluginScheduledTask]:
        """
        列出待恢复的 pending/running 任务实例。
        """
        ...

    async def update_task_status(
        self,
        task_id: str,
        status: PluginTaskStatus,
        *,
        last_error: str | None = None,
    ) -> None:
        """
        更新任务实例状态。
        """
        ...

    async def cancel_task(self, task_id: str) -> None:
        """
        将任务实例标记为取消。
        """
        ...

    async def cancel_task_key(self, plugin_id: str, key: str) -> int:
        """
        将同一插件业务 key 下的待执行任务标记为取消。
        """
        ...

    async def close(self) -> None:
        """
        关闭存储资源。
        """
        ...


class PluginSetupContextProtocol(Protocol):
    """
    第三方插件 setup 阶段上下文协议。
    """

    @property
    def manifest(self) -> PluginManifest:
        """
        当前插件清单。
        """
        ...

    @property
    def runtime(self) -> PluginRuntimeContextProtocol:
        """
        受控运行时上下文。
        """
        ...

    def register_command(
        self,
        definition: PluginCommandDefinition,
        executor: PluginExecutorProtocol,
    ) -> None:
        """
        注册 bot 命令。
        """
        ...

    def register_task(
        self,
        definition: PluginTaskDefinition,
        executor: PluginTaskExecutorProtocol,
    ) -> None:
        """
        注册受管后台任务。
        """
        ...

    def register_event(
        self,
        definition: PluginEventDefinition,
        executor: PluginEventExecutorProtocol,
    ) -> None:
        """
        注册插件事件订阅。
        """
        ...

    def register_tool(
        self,
        definition: ToolDefinition,
        executor: ToolExecutorProtocol,
    ) -> None:
        """
        注册工具。
        """
        ...

    def register_skill(self, definition: SkillDefinition) -> None:
        """
        注册技能。
        """
        ...


class PluginModuleProtocol(Protocol):
    """
    第三方插件入口模块协议。
    """

    manifest: PluginManifest

    def setup(self, context: PluginSetupContextProtocol) -> None:
        """
        注册插件能力。
        """
        ...


class PluginLoaderProtocol(Protocol):
    """
    插件加载器协议。
    """

    def load(self) -> list[PluginModuleProtocol]:
        """
        加载插件入口模块。
        """
        ...


class PluginRegistryProtocol(Protocol):
    """
    插件注册器协议。
    """

    def register(
        self,
        definition: PluginDefinition,
        executor: PluginExecutorProtocol | None = None,
        event_executor: PluginEventExecutorProtocol | None = None,
    ) -> None:
        """
        注册插件。
        """
        ...

    def unregister(self, plugin_id: str) -> None:
        """
        注销插件。
        """
        ...

    def get_definition(self, plugin_id: str) -> PluginDefinition:
        """
        获取插件定义。
        """
        ...

    def get_executor(self, plugin_id: str) -> PluginExecutorProtocol:
        """
        获取插件执行器。
        """
        ...

    def exists(self, plugin_id: str) -> bool:
        """
        判断插件是否存在。
        """
        ...

    def list_definitions(self) -> list[PluginDefinition]:
        """
        列出插件定义。
        """
        ...

    def list_commands(self) -> list[PluginCommandDefinition]:
        """
        列出已启用命令定义。
        """
        ...

    def list_events(self) -> list[PluginEventDefinition]:
        """
        列出已启用事件订阅定义。
        """
        ...

    def list_tasks(self) -> list[PluginTaskDefinition]:
        """
        列出已启用任务定义。
        """
        ...

    def record_status(self, status: PluginStatusReport) -> None:
        """
        记录插件生命周期状态。
        """
        ...

    def list_statuses(self) -> list[PluginStatusReport]:
        """
        列出插件生命周期状态。
        """
        ...

    def resolve_command(
        self,
        command_name: str,
    ) -> tuple[PluginDefinition, PluginCommandDefinition, PluginExecutorProtocol]:
        """
        根据命令名解析插件定义、命令定义与执行器。
        """
        ...

    def resolve_events(
        self,
        event: PluginEvent,
    ) -> list[tuple[PluginDefinition, PluginEventDefinition, PluginEventExecutorProtocol]]:
        """
        根据窄事件解析匹配的插件事件订阅与执行器。
        """
        ...
