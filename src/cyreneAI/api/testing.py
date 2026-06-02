from __future__ import annotations

import shlex
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Any

from cyreneAI.api.plugin import CyreneBot
from cyreneAI.core.errors.bot import BotInputError
from cyreneAI.core.errors.plugin import (
    PluginAuthorizationError,
    PluginConfigurationError,
    PluginNotFoundError,
)
from cyreneAI.core.schema.bot import (
    BotAction,
    BotCommand,
    BotEvent,
    BotEventType,
    BotMessage,
)
from cyreneAI.core.schema.chat import ChatRequest, ChatResponse
from cyreneAI.core.schema.message import ContentPart, ContentPartType, Message, MessageRole
from cyreneAI.core.schema.plugin import (
    PluginCommandDefinition,
    PluginCommandRequest,
    PluginCommandResult,
    PluginEvent,
    PluginEventDefinition,
    PluginEventRequest,
    PluginEventResult,
    PluginEventType,
    PluginManifest,
    PluginMessageReceipt,
    PluginMiddlewareDefinition,
    PluginMiddlewareRequest,
    PluginMiddlewareType,
    PluginPermission,
    PluginTaskDefinition,
    PluginTaskRequest,
    PluginTaskResult,
)


class PluginTestCommandResult:
    """
    插件命令测试结果。
    """

    __test__ = False

    def __init__(self, result: PluginCommandResult) -> None:
        self.result = result

    @property
    def handled(self) -> bool:
        return self.result.handled

    @property
    def actions(self) -> list[BotAction]:
        return list(self.result.actions)

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self.result.metadata)

    @property
    def texts(self) -> list[str]:
        return _action_texts(self.result.actions)

    def has_text(self, text: str) -> bool:
        return text in self.texts


class PluginTestEventResult:
    """
    插件事件测试结果。
    """

    __test__ = False

    def __init__(self, results: list[PluginEventResult]) -> None:
        self.results = results

    @property
    def handled(self) -> bool:
        return all(result.handled for result in self.results)

    @property
    def actions(self) -> list[BotAction]:
        actions: list[BotAction] = []
        for result in self.results:
            actions.extend(result.actions)
        return actions

    @property
    def metadata(self) -> list[dict[str, Any]]:
        return [dict(result.metadata) for result in self.results]

    @property
    def texts(self) -> list[str]:
        return _action_texts(self.actions)

    def has_text(self, text: str) -> bool:
        return text in self.texts


class PluginTestTaskResult:
    """
    插件任务测试结果。
    """

    __test__ = False

    def __init__(self, result: PluginTaskResult) -> None:
        self.result = result

    @property
    def handled(self) -> bool:
        return self.result.handled

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self.result.metadata)


class PluginTestClient:
    """
    本地插件测试客户端，不启动 server 或完整 runtime。
    """

    __test__ = False

    def __init__(
        self,
        plugin: CyreneBot,
        *,
        dependencies: dict[str, Any] | None = None,
        manifest: PluginManifest | None = None,
        permissions: list[str | PluginPermission] | None = None,
        enforce_permissions: bool = False,
    ) -> None:
        self._manifest = manifest or _plugin_manifest_or_default(plugin)
        if permissions is not None:
            self._manifest = self._manifest.model_copy(
                update={"permissions": list(permissions)}
            )
        self.storage = _PluginTestStorage()
        self.assets = _PluginTestAssets()
        self.messages = _PluginTestMessages()
        self.scheduler = _PluginTestTasks()
        resolved_dependencies: dict[str, Any] = {
            "storage": self.storage,
            "assets": self.assets,
            "messages": self.messages,
            "message": self.messages,
            "outbox": self.messages,
            "tasks": self.scheduler,
            "task": self.scheduler,
            "scheduler": self.scheduler,
            "agent": _PluginTestAgent(),
            **(dependencies or {}),
        }
        self._runtime = _PluginTestRuntimeContext(
            self._manifest,
            dependencies=resolved_dependencies,
            enforce_permissions=enforce_permissions,
        )
        self._context = _PluginTestSetupContext(self._manifest, self._runtime)
        plugin.setup(self._context)

    @property
    def commands(self) -> list[PluginCommandDefinition]:
        return [entry.definition for entry in self._context.commands]

    @property
    def events(self) -> list[PluginEventDefinition]:
        return [entry.definition for entry in self._context.events]

    @property
    def tasks(self) -> list[PluginTaskDefinition]:
        return [entry.definition for entry in self._context.tasks]

    @property
    def middlewares(self) -> list[PluginMiddlewareDefinition]:
        return [entry.definition for entry in self._context.middlewares]

    @property
    def sent_messages(self) -> list[dict[str, Any]]:
        return list(self.messages.sent)

    @property
    def scheduled_tasks(self) -> list[dict[str, Any]]:
        return list(self.scheduler.scheduled)

    async def command(
        self,
        text: str,
        *,
        is_admin: bool = False,
        channel_id: str = "test",
        session_id: str = "test:user-1",
        user_id: str = "user-1",
        event_id: str = "event-1",
        provider_id: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PluginTestCommandResult:
        event = _command_event(
            text,
            channel_id=channel_id,
            session_id=session_id,
            user_id=user_id,
            event_id=event_id,
        )
        command = _parse_command(
            event,
            known_command_names=self._context.command_names,
        )
        entry = self._context.resolve_command(command.name)
        if entry.definition.admin_required and not is_admin:
            raise PluginAuthorizationError(
                f"插件命令 {entry.definition.name} 需要管理员权限"
            )

        result = await entry.executor.execute(
            PluginCommandRequest(
                command=command,
                event=event,
                is_admin=is_admin,
                metadata=_request_metadata(
                    metadata,
                    provider_id=provider_id,
                    model=model,
                    session_id=session_id,
                ),
            )
        )
        return PluginTestCommandResult(result)

    async def event(
        self,
        event_type: str | PluginEventType,
        *,
        text: str | None = None,
        session_id: str = "test:user-1",
        user_id: str | None = "user-1",
        thread_id: str | None = None,
        message_id: str | None = None,
        event_id: str = "event-1",
        provider_id: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PluginTestEventResult:
        event = PluginEvent(
            event_id=event_id,
            event_type=_normalize_event_type(event_type),
            session_id=session_id,
            user_id=user_id,
            thread_id=thread_id,
            message_id=message_id,
            text=text,
        )
        results: list[PluginEventResult] = []
        for entry in self._context.resolve_events(event.event_type):
            results.append(
                await entry.executor.execute(
                    PluginEventRequest(
                        route=entry.definition,
                        event=event,
                        metadata=_request_metadata(
                            metadata,
                            provider_id=provider_id,
                            model=model,
                            session_id=session_id,
                        ),
                    )
                )
            )
        return PluginTestEventResult(results)

    async def task(
        self,
        name: str,
        *,
        payload: dict[str, Any] | None = None,
        provider_id: str | None = None,
        model: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PluginTestTaskResult:
        entry = self._context.resolve_task(name)
        result = await entry.executor.execute(
            PluginTaskRequest(
                task=entry.definition,
                payload=dict(payload or {}),
                metadata=_request_metadata(
                    metadata,
                    provider_id=provider_id,
                    model=model,
                    session_id=session_id,
                ),
            )
        )
        return PluginTestTaskResult(result)

    async def llm_middleware(
        self,
        chat_request: ChatRequest | str,
        next_call: Callable[[ChatRequest], Awaitable[ChatResponse]],
        *,
        provider_id: str | None = None,
        model: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatResponse:
        current_chat_request = _chat_request(
            chat_request,
            provider_id=provider_id,
            model=model,
            session_id=session_id,
            metadata=metadata,
        )
        entries = self._context.resolve_middlewares(PluginMiddlewareType.LLM)

        async def call_at(index: int, current_request: ChatRequest) -> ChatResponse:
            if index >= len(entries):
                return await next_call(current_request)
            entry = entries[index]

            async def call_next(
                middleware_request: PluginMiddlewareRequest,
            ) -> ChatResponse:
                return await call_at(index + 1, middleware_request.chat_request)

            return await entry.executor.execute(
                PluginMiddlewareRequest(
                    route=entry.definition,
                    chat_request=current_request,
                    metadata={"plugin_id": self._manifest.plugin_id},
                ),
                call_next,
            )

        return await call_at(0, current_chat_request)


class _PluginTestRuntimeContext:
    def __init__(
        self,
        manifest: PluginManifest,
        *,
        dependencies: dict[str, Any],
        enforce_permissions: bool,
    ) -> None:
        self._manifest = manifest
        self._dependencies = {
            key.strip().lower(): value
            for key, value in dependencies.items()
        }
        self._enforce_permissions = enforce_permissions

    def require_permission(self, permission: PluginPermission) -> None:
        if not self._enforce_permissions:
            return
        allowed = {str(value) for value in self._manifest.permissions}
        if str(permission) not in allowed:
            raise PluginAuthorizationError(f"missing {permission}")

    @property
    def llm(self) -> Any:
        return self._dependency("llm")

    def llm_for_request(self, request: Any) -> Any:
        value = self.llm
        for_request = getattr(value, "for_request", None)
        if callable(for_request):
            return for_request(request)
        return value

    @property
    def agent(self) -> Any:
        return self._dependency("agent")

    def agent_for_request(self, request: Any) -> Any:
        value = self.agent
        for_request = getattr(value, "for_request", None)
        if callable(for_request):
            return for_request(request)
        return value

    async def generate_image(self, request: Any) -> Any:
        value = self._dependency("generate_image", "image")
        if callable(value):
            result = value(request)
            if isawaitable(result):
                return await result
            return result
        return value

    def list_providers(self) -> Any:
        value = self._dependency("providers", "list_providers")
        if callable(value):
            return value()
        return value

    def list_provider_models(self, provider_id: str) -> Any:
        value = self._dependency("provider_models", "list_provider_models")
        if callable(value):
            return value(provider_id)
        return value

    @property
    def storage(self) -> Any:
        self.require_permission(PluginPermission.STORAGE)
        return self._dependency("storage")

    @property
    def assets(self) -> Any:
        self.require_permission(PluginPermission.ASSETS)
        return self._dependency("assets")

    @property
    def tasks(self) -> Any:
        self.require_permission(PluginPermission.TASK)
        return self._dependency("tasks", "task", "scheduler")

    @property
    def messages(self) -> Any:
        self.require_permission(PluginPermission.MESSAGE_SEND)
        return self._dependency("messages", "message", "outbox")

    @property
    def outbox(self) -> Any:
        return self.messages

    def _dependency(self, *names: str) -> Any:
        for name in names:
            if name in self._dependencies:
                return self._dependencies[name]
        joined_names = ", ".join(names)
        raise PluginConfigurationError(f"测试依赖未提供: {joined_names}")


class _PluginTestStorage:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    async def set(self, key: str, value: Any) -> None:
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def list_keys(self) -> list[str]:
        return sorted(self.values)

    async def update(self, key: str, updater: Any, default: Any = None) -> Any:
        value = self.values.get(key, default)
        updated = updater(value)
        if isawaitable(updated):
            updated = await updated
        self.values[key] = updated
        return updated


class _PluginTestAssets:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def read_text(self, path: str) -> str:
        return (await self.read_bytes(path)).decode("utf-8")

    async def read_bytes(self, path: str) -> bytes:
        normalized_path = _normalize_asset_path(path)
        if normalized_path not in self.files:
            raise FileNotFoundError(normalized_path)
        return self.files[normalized_path]

    async def exists(self, path: str) -> bool:
        return _normalize_asset_path(path) in self.files

    async def list(self, path: str = "") -> list[str]:
        prefix = _normalize_asset_path(path)
        if prefix:
            prefix = f"{prefix}/"
        return sorted(
            item
            for item in self.files
            if not prefix or item.startswith(prefix)
        )

    def add_text(self, path: str, content: str) -> None:
        self.files[_normalize_asset_path(path)] = content.encode("utf-8")

    def add_bytes(self, path: str, content: bytes) -> None:
        self.files[_normalize_asset_path(path)] = bytes(content)


class _PluginTestMessages:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(
        self,
        session_id: str,
        *,
        text: str,
        metadata: dict[str, Any] | None = None,
        bypass_rate_limit: bool = False,
    ) -> PluginMessageReceipt:
        self.sent.append(
            {
                "session_id": session_id,
                "text": text,
                "metadata": dict(metadata or {}),
                "bypass_rate_limit": bypass_rate_limit,
            }
        )
        return PluginMessageReceipt(
            session_id=session_id,
            accepted=True,
            metadata=dict(metadata or {}),
        )


class _PluginTestAgent:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def chat(self, prompt: str, **kwargs: Any) -> str:
        self.requests.append({"prompt": prompt, **kwargs})
        return prompt

    async def result(self, prompt: str, **kwargs: Any) -> Any:
        self.requests.append({"prompt": prompt, **kwargs})
        return prompt


class _PluginTestTasks:
    def __init__(self) -> None:
        self.scheduled: list[dict[str, Any]] = []
        self.canceled: list[str] = []
        self.canceled_keys: list[str] = []

    async def schedule_once(
        self,
        task_name: str,
        *,
        delay_seconds: float,
        payload: dict[str, Any] | None = None,
        key: str | None = None,
    ) -> str:
        task_id = f"test-task-{len(self.scheduled) + 1}"
        self.scheduled.append(
            {
                "task_id": task_id,
                "task_name": task_name,
                "delay_seconds": delay_seconds,
                "payload": dict(payload or {}),
                "key": key,
            }
        )
        return task_id

    async def cancel(self, task_id: str) -> None:
        self.canceled.append(task_id)

    async def cancel_key(self, key: str) -> int:
        self.canceled_keys.append(key)
        return sum(1 for item in self.scheduled if item.get("key") == key)


class _PluginTestSetupContext:
    def __init__(
        self,
        manifest: PluginManifest,
        runtime: _PluginTestRuntimeContext,
    ) -> None:
        self.manifest = manifest
        self.runtime = runtime
        self.commands: list[_PluginTestCommandEntry] = []
        self.tasks: list[_PluginTestTaskEntry] = []
        self.events: list[_PluginTestEventEntry] = []
        self.middlewares: list[_PluginTestMiddlewareEntry] = []
        self.tools: list[tuple[Any, Any]] = []
        self.skills: list[Any] = []

    @property
    def command_names(self) -> set[str]:
        names: set[str] = set()
        for entry in self.commands:
            names.add(_normalize_command_name(entry.definition.name))
            names.update(
                _normalize_command_name(alias)
                for alias in entry.definition.aliases
            )
        return names

    def register_command(
        self,
        definition: PluginCommandDefinition,
        executor: Any,
    ) -> None:
        self.commands.append(_PluginTestCommandEntry(definition, executor))

    def register_task(
        self,
        definition: PluginTaskDefinition,
        executor: Any,
    ) -> None:
        self.tasks.append(_PluginTestTaskEntry(definition, executor))

    def register_event(
        self,
        definition: PluginEventDefinition,
        executor: Any,
    ) -> None:
        self.events.append(_PluginTestEventEntry(definition, executor))

    def register_tool(self, definition: Any, executor: Any) -> None:
        self.tools.append((definition, executor))

    def register_skill(self, definition: Any) -> None:
        self.skills.append(definition)

    def register_middleware(self, definition: Any, executor: Any) -> None:
        self.middlewares.append(_PluginTestMiddlewareEntry(definition, executor))

    def resolve_command(self, name: str) -> _PluginTestCommandEntry:
        normalized_name = _normalize_command_name(name)
        for entry in self.commands:
            names = {
                _normalize_command_name(entry.definition.name),
                *[
                    _normalize_command_name(alias)
                    for alias in entry.definition.aliases
                ],
            }
            if normalized_name in names:
                return entry
        raise PluginNotFoundError(f"插件命令不存在: {name}")

    def resolve_task(self, name: str) -> _PluginTestTaskEntry:
        normalized_name = _normalize_command_name(name)
        for entry in self.tasks:
            if _normalize_command_name(entry.definition.name) == normalized_name:
                return entry
        raise PluginNotFoundError(f"插件任务不存在: {name}")

    def resolve_events(
        self,
        event_type: PluginEventType,
    ) -> list[_PluginTestEventEntry]:
        entries = [
            entry
            for entry in self.events
            if entry.definition.event_type == event_type
        ]
        if not entries:
            raise PluginNotFoundError(f"插件事件订阅不存在: {event_type}")
        return entries

    def resolve_middlewares(
        self,
        middleware_type: PluginMiddlewareType,
    ) -> list["_PluginTestMiddlewareEntry"]:
        return [
            entry
            for entry in self.middlewares
            if entry.definition.middleware_type == middleware_type
        ]


class _PluginTestCommandEntry:
    def __init__(
        self,
        definition: PluginCommandDefinition,
        executor: Any,
    ) -> None:
        self.definition = definition
        self.executor = executor


class _PluginTestTaskEntry:
    def __init__(
        self,
        definition: PluginTaskDefinition,
        executor: Any,
    ) -> None:
        self.definition = definition
        self.executor = executor


class _PluginTestEventEntry:
    def __init__(
        self,
        definition: PluginEventDefinition,
        executor: Any,
    ) -> None:
        self.definition = definition
        self.executor = executor


class _PluginTestMiddlewareEntry:
    def __init__(
        self,
        definition: PluginMiddlewareDefinition,
        executor: Any,
    ) -> None:
        self.definition = definition
        self.executor = executor


def _plugin_manifest_or_default(plugin: CyreneBot) -> PluginManifest:
    try:
        return plugin.manifest
    except PluginConfigurationError:
        return PluginManifest(
            plugin_id="test.plugin",
            name="Test Plugin",
            description="Local plugin test manifest.",
            entrypoint="test.py",
        )


def _request_metadata(
    metadata: dict[str, Any] | None,
    *,
    provider_id: str | None = None,
    model: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    result = dict(metadata or {})
    if provider_id is not None:
        result["provider_id"] = provider_id
    if model is not None:
        result["model"] = model
    if session_id is not None:
        result.setdefault("session_id", session_id)
    return result


def _chat_request(
    value: ChatRequest | str,
    *,
    provider_id: str | None,
    model: str | None,
    session_id: str | None,
    metadata: dict[str, Any] | None,
) -> ChatRequest:
    if isinstance(value, ChatRequest):
        update: dict[str, Any] = {}
        if provider_id is not None:
            update["provider_id"] = provider_id
        if model is not None:
            update["model"] = model
        merged_metadata = _request_metadata(
            {
                **value.metadata,
                **(metadata or {}),
            },
            session_id=session_id,
        )
        if merged_metadata != value.metadata:
            update["metadata"] = merged_metadata
        if update:
            return value.model_copy(update=update)
        return value

    return ChatRequest(
        provider_id=provider_id or "test-provider",
        model=model or "test-model",
        messages=[
            Message(
                role=MessageRole.USER,
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text=value,
                    )
                ],
            )
        ],
        metadata=_request_metadata(metadata, session_id=session_id),
    )


def _command_event(
    text: str,
    *,
    channel_id: str,
    session_id: str,
    user_id: str,
    event_id: str,
) -> BotEvent:
    return BotEvent(
        event_id=event_id,
        event_type=BotEventType.COMMAND,
        channel_id=channel_id,
        session_id=session_id,
        user_id=user_id,
        message=BotMessage(
            sender_id=user_id,
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=text,
                )
            ],
        ),
    )


def _parse_command(
    event: BotEvent,
    *,
    known_command_names: set[str],
) -> BotCommand:
    raw_text = _event_text(event).strip()
    if not raw_text.startswith("/"):
        raise BotInputError("COMMAND event text must start with /")

    command_text = raw_text[1:].strip()
    if not command_text:
        raise BotInputError("COMMAND event must include command name")

    try:
        parts = shlex.split(command_text)
    except ValueError as exc:
        raise BotInputError(f"Invalid command syntax: {exc}") from exc
    if not parts:
        raise BotInputError("COMMAND event must include command name")

    name_token, args = _split_command_parts(parts, known_command_names)
    name, target = _split_command_target(name_token)
    if not name:
        raise BotInputError("COMMAND event must include command name")

    return BotCommand(
        raw_text=raw_text,
        name=name.lower(),
        target=target,
        args=tuple(args),
        args_text=" ".join(args),
    )


def _split_command_target(name_token: str) -> tuple[str, str | None]:
    name, separator, target = name_token.partition("@")
    if not separator:
        return name, None
    return name, target or None


def _split_command_parts(
    parts: list[str],
    known_command_names: set[str],
) -> tuple[str, list[str]]:
    if not known_command_names:
        name_token, *args = parts
        return name_token, args

    first_name, target = _split_command_target(parts[0])
    normalized_names = {_normalize_command_name(name) for name in known_command_names}
    best_size = 0
    best_name = ""
    for size in range(1, len(parts) + 1):
        candidate_parts = [first_name, *parts[1:size]]
        candidate = _normalize_command_name(" ".join(candidate_parts))
        if candidate in normalized_names:
            best_size = size
            best_name = candidate

    if best_size == 0:
        name_token, *args = parts
        return name_token, args

    if target is not None:
        best_name = f"{best_name}@{target}"
    return best_name, parts[best_size:]


def _normalize_command_name(value: str) -> str:
    return " ".join(value.strip().removeprefix("/").split()).lower()


def _normalize_asset_path(path: str) -> str:
    return "/".join(part for part in path.replace("\\", "/").split("/") if part)


def _normalize_event_type(value: str | PluginEventType) -> PluginEventType:
    if isinstance(value, PluginEventType):
        return value
    return PluginEventType(str(value).strip().lower())


def _action_texts(actions: list[BotAction]) -> list[str]:
    texts: list[str] = []
    for action in actions:
        if action.message is None:
            continue
        for part in action.message.content:
            if part.type == ContentPartType.TEXT and part.text is not None:
                texts.append(part.text)
    return texts


def _event_text(event: BotEvent) -> str:
    if event.message is None:
        raise BotInputError("COMMAND event must include message")

    chunks = [
        part.text
        for part in event.message.content
        if part.type == ContentPartType.TEXT and part.text
    ]
    if not chunks:
        raise BotInputError("COMMAND event must include text content")
    return "\n".join(chunks)


__all__ = [
    "PluginTestClient",
    "PluginTestCommandResult",
    "PluginTestEventResult",
    "PluginTestTaskResult",
]
