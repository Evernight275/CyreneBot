from __future__ import annotations

import asyncio
import json
from datetime import timedelta

from cyreneAI.application.chat.orchestrator import (
    ApplicationChatRequest,
    ChatOrchestrator,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.core.plugin.registry import PluginRegistry
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest, ChatResponse
from cyreneAI.core.schema.context import (
    ContextBuildRequest,
    ContextBuildResult,
    ContextItem,
    ContextItemSource,
    ContextItemType,
    ContextSegment,
    ContextSegmentRole,
    ContextSnapshot,
    ContextWindow,
)
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.plugin import (
    PluginDefinition,
    PluginMiddlewareDefinition,
    PluginMiddlewareRequest,
    PluginMiddlewareType,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.core.schema.skill import SkillDefinition
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolChoice,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolResult,
    ToolRiskLevel,
    ToolSafetyProfile,
)
from cyreneAI.core.skill.manager import SkillManager
from cyreneAI.core.skill.registry import SkillRegistry
from cyreneAI.core.tool.manager import ToolManager
from cyreneAI.core.tool.registry import ToolRegistry


def _message(role: MessageRole, text: str) -> Message:
    return Message(
        role=role,
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text=text,
            )
        ],
    )


class FakeContextStore:
    def __init__(self) -> None:
        self.snapshots: list[ContextSnapshot] = []

    async def save_snapshot(self, snapshot: ContextSnapshot) -> None:
        self.snapshots.append(snapshot)

    async def get_snapshot(self, snapshot_id: str) -> ContextSnapshot:
        for snapshot in self.snapshots:
            if snapshot.snapshot_id == snapshot_id:
                return snapshot
        raise KeyError(snapshot_id)

    async def list_snapshots(self, session_id: str) -> list[ContextSnapshot]:
        return [
            snapshot for snapshot in self.snapshots if snapshot.session_id == session_id
        ]

    async def delete_snapshot(self, snapshot_id: str) -> None:
        self.snapshots = [
            snapshot
            for snapshot in self.snapshots
            if snapshot.snapshot_id != snapshot_id
        ]

    async def delete_snapshots_for_session(self, session_id: str) -> int:
        deleted_count = len(
            [
                snapshot
                for snapshot in self.snapshots
                if snapshot.session_id == session_id
            ]
        )
        self.snapshots = [
            snapshot for snapshot in self.snapshots if snapshot.session_id != session_id
        ]
        return deleted_count


class FakeChatProvider:
    info = ProviderInfo(
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        name="fake",
        description="Fake chat provider.",
    )
    config = ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        timeout=timedelta(seconds=1),
    )

    def __init__(self, response: ChatResponse | list[ChatResponse]) -> None:
        self.responses = response if isinstance(response, list) else [response]
        self.requests: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.responses) - 1)
        return self.responses[index]

    async def close(self) -> None:
        pass


class FakeToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=f"executed:{call.arguments}",
        )


class RecordingToolExecutor:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=f"executed:{call.name}",
        )


class RecordingLLMMiddlewareExecutor:
    def __init__(self) -> None:
        self.calls: list[PluginMiddlewareRequest] = []

    async def execute(
        self, request: PluginMiddlewareRequest, next_call
    ) -> ChatResponse:
        self.calls.append(request)
        updated = request.model_copy(
            update={
                "chat_request": request.chat_request.model_copy(
                    update={
                        "metadata": {
                            **request.chat_request.metadata,
                            "middleware": "seen",
                        }
                    }
                )
            }
        )
        return await next_call(updated)


class ContentOnlyContextBuilder:
    async def build(self, request: ContextBuildRequest) -> ContextBuildResult:
        return ContextBuildResult(
            window=ContextWindow(
                window_id=f"{request.session_id}:window",
                segments=[
                    ContextSegment(
                        segment_id=f"{request.session_id}:history",
                        role=ContextSegmentRole.HISTORY,
                        items=[
                            ContextItem(
                                item_id="assistant-summary",
                                type=ContextItemType.SUMMARY,
                                source=ContextItemSource.ASSISTANT,
                                content="Assistant summary.",
                            )
                        ],
                    )
                ],
            )
        )


async def _build_provider_manager(provider: FakeChatProvider) -> ProviderManager:
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig) -> FakeChatProvider:
        return provider

    factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
    manager = ProviderManager(factory)
    await manager.add(provider.config)
    return manager


async def _run_chat_orchestrator_request() -> None:
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=Message(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="lookup",
                            arguments='{"key":"value"}',
                        )
                    ],
                    metadata={
                        "openai_compatible": {
                            "reasoning_content": "thinking before tool call",
                        }
                    },
                ),
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="lookup",
                        arguments='{"key":"value"}',
                    )
                ],
                finish_reason=ChatFinishReason.TOOL_CALLS,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "final"),
                finish_reason=ChatFinishReason.STOP,
            ),
        ]
    )
    provider_manager = await _build_provider_manager(provider)
    context_store = FakeContextStore()
    skill_registry = SkillRegistry()
    skill_registry.register(
        SkillDefinition(
            name="memory",
            description="Use memory.",
            instructions="Prefer relevant memory.",
            triggers=["memory"],
            allowed_tools=["lookup"],
        )
    )
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="lookup",
            description="Lookup a value.",
        ),
        FakeToolExecutor(),
    )
    runtime = CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContextWindowBuilder(),
        context_manager=ContextManager(context_store),
        skill_manager=SkillManager(skill_registry),
        tool_registry=tool_registry,
        tool_manager=ToolManager(tool_registry),
    )

    result = await ChatOrchestrator(runtime).chat(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "Use memory.")],
        )
    )

    assert context_store.snapshots == [result.context_snapshot]
    assert result.context_snapshot.session_id == "session-1"
    assert result.skill_bundle is not None
    assert result.skill_bundle.metadata == {"skills": ["memory"]}
    assert [tool_result.content for tool_result in result.tool_results] == [
        'executed:{"key":"value"}'
    ]
    assert result.response.message == _message(MessageRole.ASSISTANT, "final")
    assert len(provider.requests) == 2

    provider_request = provider.requests[0]
    assert provider_request.provider_id == "provider-1"
    assert provider_request.model == "fake-model"
    assert provider_request.tools is not None
    assert [tool.name for tool in provider_request.tools] == ["lookup"]
    assert provider_request.metadata["session_id"] == "session-1"
    assert provider_request.metadata["skill_names"] == ["memory"]
    assert provider_request.messages[0].role == MessageRole.SYSTEM
    assert provider_request.messages[0].name == "skills"
    assert provider_request.messages[0].content is not None
    assert provider_request.messages[0].content[0].text == (
        "[memory]\nPrefer relevant memory."
    )
    assert provider_request.messages[1].role == MessageRole.USER

    feedback_request = provider.requests[1]
    assert feedback_request.messages[-2].role == MessageRole.ASSISTANT
    assert feedback_request.messages[-2].tool_calls is not None
    assert feedback_request.messages[-2].tool_calls[0].id == "call-1"
    assert feedback_request.messages[-2].metadata == {
        "openai_compatible": {
            "reasoning_content": "thinking before tool call",
        }
    }
    assert feedback_request.messages[-1].role == MessageRole.TOOL
    assert feedback_request.messages[-1].name == "lookup"
    assert feedback_request.messages[-1].tool_call_id == "call-1"
    assert feedback_request.messages[-1].content is not None
    assert feedback_request.messages[-1].content[0].text == ('executed:{"key":"value"}')


def test_chat_orchestrator_builds_context_skills_tools_and_calls_provider() -> None:
    asyncio.run(_run_chat_orchestrator_request())


async def _run_chat_orchestrator_filters_tools_by_request_and_skill() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            message=_message(MessageRole.ASSISTANT, "hello"),
            finish_reason=ChatFinishReason.STOP,
        )
    )
    provider_manager = await _build_provider_manager(provider)
    skill_registry = SkillRegistry()
    skill_registry.register(
        SkillDefinition(
            name="memory",
            description="Use memory.",
            instructions="Prefer relevant memory.",
            triggers=["memory"],
            allowed_tools=["lookup", "delete"],
        )
    )
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="lookup", description="Lookup a value."),
        FakeToolExecutor(),
    )
    tool_registry.register(
        ToolDefinition(name="delete", description="Delete a value."),
        FakeToolExecutor(),
    )
    runtime = CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContextWindowBuilder(),
        skill_manager=SkillManager(skill_registry),
        tool_registry=tool_registry,
        tool_manager=ToolManager(tool_registry),
    )

    await ChatOrchestrator(runtime).chat(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "Use memory.")],
            tool_choice=ToolChoice(mode="tool", name="delete"),
            allowed_tool_names=["lookup"],
        )
    )

    provider_tools = provider.requests[0].tools
    assert provider_tools is not None
    assert [tool.name for tool in provider_tools] == ["lookup"]
    assert provider.requests[0].tool_choice is None


def test_chat_orchestrator_filters_tools_by_request_and_skill() -> None:
    asyncio.run(_run_chat_orchestrator_filters_tools_by_request_and_skill())


async def _run_chat_orchestrator_filters_tools_by_execution_policy() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            message=_message(MessageRole.ASSISTANT, "hello"),
            finish_reason=ChatFinishReason.STOP,
        )
    )
    provider_manager = await _build_provider_manager(provider)
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="lookup",
            description="Lookup a value.",
            safety_profile=ToolSafetyProfile(risk_level=ToolRiskLevel.READ_ONLY),
        ),
        FakeToolExecutor(),
    )
    tool_registry.register(
        ToolDefinition(
            name="delete",
            description="Delete a value.",
            safety_profile=ToolSafetyProfile(risk_level=ToolRiskLevel.WRITE),
        ),
        FakeToolExecutor(),
    )
    runtime = CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContextWindowBuilder(),
        tool_registry=tool_registry,
        tool_manager=ToolManager(tool_registry),
    )

    await ChatOrchestrator(runtime).chat(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "Use tools.")],
            tool_choice=ToolChoice(mode="tool", name="delete"),
            tool_execution_policy=ToolExecutionPolicy(
                max_risk_level=ToolRiskLevel.READ_ONLY
            ),
        )
    )

    provider_tools = provider.requests[0].tools
    assert provider_tools is not None
    assert [tool.name for tool in provider_tools] == ["lookup"]
    assert provider.requests[0].tool_choice is None


def test_chat_orchestrator_filters_tools_by_execution_policy() -> None:
    asyncio.run(_run_chat_orchestrator_filters_tools_by_execution_policy())


async def _run_chat_orchestrator_runs_plugin_llm_middlewares() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            message=_message(MessageRole.ASSISTANT, "hello"),
            finish_reason=ChatFinishReason.STOP,
        )
    )
    provider_manager = await _build_provider_manager(provider)
    registry = PluginRegistry()
    middleware_executor = RecordingLLMMiddlewareExecutor()
    registry.register(
        PluginDefinition(
            plugin_id="thirdparty.audit",
            name="Audit",
            description="Trace LLM calls.",
            middlewares=[
                PluginMiddlewareDefinition(middleware_type=PluginMiddlewareType.LLM)
            ],
        ),
        middleware_executor=middleware_executor,
    )
    runtime = CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContextWindowBuilder(),
        plugin_manager=PluginManager(registry),
    )

    await ChatOrchestrator(runtime).chat(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "hello")],
        )
    )

    assert len(middleware_executor.calls) == 1
    assert provider.requests[0].metadata["middleware"] == "seen"


def test_chat_orchestrator_runs_plugin_llm_middlewares() -> None:
    asyncio.run(_run_chat_orchestrator_runs_plugin_llm_middlewares())


async def _run_chat_orchestrator_rejects_disallowed_tool_call() -> None:
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="delete",
                        arguments='{"key":"value"}',
                    )
                ],
                finish_reason=ChatFinishReason.TOOL_CALLS,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "tool failed"),
                finish_reason=ChatFinishReason.STOP,
            ),
        ]
    )
    provider_manager = await _build_provider_manager(provider)
    skill_registry = SkillRegistry()
    skill_registry.register(
        SkillDefinition(
            name="memory",
            description="Use memory.",
            instructions="Prefer relevant memory.",
            triggers=["memory"],
            allowed_tools=["lookup"],
        )
    )
    delete_executor = RecordingToolExecutor()
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="lookup", description="Lookup a value."),
        RecordingToolExecutor(),
    )
    tool_registry.register(
        ToolDefinition(name="delete", description="Delete a value."),
        delete_executor,
    )
    runtime = CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContextWindowBuilder(),
        skill_manager=SkillManager(skill_registry),
        tool_registry=tool_registry,
        tool_manager=ToolManager(tool_registry),
    )

    result = await ChatOrchestrator(runtime).chat(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "Use memory.")],
        )
    )

    assert delete_executor.calls == []
    assert len(provider.requests) == 2
    assert provider.requests[0].tools is not None
    assert [tool.name for tool in provider.requests[0].tools] == ["lookup"]
    assert len(result.tool_results) == 1
    assert result.tool_results[0].success is False
    assert result.tool_results[0].name == "delete"
    assert result.tool_results[0].error is not None
    assert "not allowed" in result.tool_results[0].error

    feedback_message = provider.requests[1].messages[-1]
    assert feedback_message.role == MessageRole.TOOL
    assert feedback_message.tool_call_id == "call-1"
    assert feedback_message.content is not None
    payload = json.loads(feedback_message.content[0].text or "{}")
    assert payload["success"] is False
    assert payload["error_type"] == "ToolPolicyError"


def test_chat_orchestrator_rejects_disallowed_tool_call() -> None:
    asyncio.run(_run_chat_orchestrator_rejects_disallowed_tool_call())


async def _run_chat_orchestrator_does_not_save_unanswered_tool_calls() -> None:
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=Message(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="lookup",
                            arguments='{"key":"value"}',
                        )
                    ],
                ),
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="lookup",
                        arguments='{"key":"value"}',
                    )
                ],
                finish_reason=ChatFinishReason.TOOL_CALLS,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=Message(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            id="call-2",
                            name="lookup",
                            arguments='{"key":"next"}',
                        )
                    ],
                ),
                tool_calls=[
                    ToolCall(
                        id="call-2",
                        name="lookup",
                        arguments='{"key":"next"}',
                    )
                ],
                finish_reason=ChatFinishReason.TOOL_CALLS,
            ),
        ]
    )
    provider_manager = await _build_provider_manager(provider)
    context_store = FakeContextStore()
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="lookup", description="Lookup a value."),
        FakeToolExecutor(),
    )
    runtime = CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContextWindowBuilder(),
        context_manager=ContextManager(context_store),
        tool_registry=tool_registry,
        tool_manager=ToolManager(tool_registry),
    )

    result = await ChatOrchestrator(runtime).chat(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "Use lookup.")],
            max_tool_rounds=1,
        )
    )

    assert result.response.tool_calls[0].id == "call-2"
    assert len(provider.requests) == 2
    assert _context_messages(result.context_snapshot) == [
        _message(MessageRole.USER, "Use lookup.")
    ]
    assert context_store.snapshots == [result.context_snapshot]


def test_chat_orchestrator_does_not_save_unanswered_tool_calls() -> None:
    asyncio.run(_run_chat_orchestrator_does_not_save_unanswered_tool_calls())


async def _run_chat_orchestrator_without_optional_managers() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            message=_message(MessageRole.ASSISTANT, "hello"),
            finish_reason=ChatFinishReason.STOP,
        )
    )
    provider_manager = await _build_provider_manager(provider)
    runtime = CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContextWindowBuilder(),
    )

    result = await ChatOrchestrator(runtime).chat(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "hello")],
        )
    )

    assert result.response.message == _message(MessageRole.ASSISTANT, "hello")
    assert result.skill_bundle is None
    assert result.tool_results == []
    assert provider.requests[0].tools is None
    assert provider.requests[0].messages == [_message(MessageRole.USER, "hello")]


def test_chat_orchestrator_allows_minimal_runtime() -> None:
    asyncio.run(_run_chat_orchestrator_without_optional_managers())


async def _run_chat_orchestrator_uses_saved_session_history() -> None:
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "DeepSeek 是一家 AI 公司。"),
                finish_reason=ChatFinishReason.STOP,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "我们刚聊过 DeepSeek。"),
                finish_reason=ChatFinishReason.STOP,
            ),
        ]
    )
    provider_manager = await _build_provider_manager(provider)
    context_store = FakeContextStore()
    runtime = CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContextWindowBuilder(),
        context_manager=ContextManager(context_store),
    )
    orchestrator = ChatOrchestrator(runtime)

    await orchestrator.chat(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "deepseek 是什么")],
        )
    )
    second_result = await orchestrator.chat(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "回忆下我们会话内容")],
        )
    )

    assert provider.requests[0].messages == [
        _message(MessageRole.USER, "deepseek 是什么"),
    ]
    assert provider.requests[1].messages == [
        _message(MessageRole.USER, "deepseek 是什么"),
        _message(MessageRole.ASSISTANT, "DeepSeek 是一家 AI 公司。"),
        _message(MessageRole.USER, "回忆下我们会话内容"),
    ]
    assert len(context_store.snapshots) == 2
    assert _context_messages(second_result.context_snapshot) == [
        _message(MessageRole.USER, "deepseek 是什么"),
        _message(MessageRole.ASSISTANT, "DeepSeek 是一家 AI 公司。"),
        _message(MessageRole.USER, "回忆下我们会话内容"),
        _message(MessageRole.ASSISTANT, "我们刚聊过 DeepSeek。"),
    ]


def test_chat_orchestrator_uses_saved_session_history() -> None:
    asyncio.run(_run_chat_orchestrator_uses_saved_session_history())


async def _run_chat_orchestrator_maps_context_item_source() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            message=_message(MessageRole.ASSISTANT, "hello"),
            finish_reason=ChatFinishReason.STOP,
        )
    )
    provider_manager = await _build_provider_manager(provider)
    runtime = CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContentOnlyContextBuilder(),
    )

    await ChatOrchestrator(runtime).chat(
        ApplicationChatRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            messages=[_message(MessageRole.USER, "hello")],
        )
    )

    assert provider.requests[0].messages == [
        _message(MessageRole.ASSISTANT, "Assistant summary.")
    ]


def test_chat_orchestrator_maps_content_only_context_item_by_source() -> None:
    asyncio.run(_run_chat_orchestrator_maps_context_item_source())


def _context_messages(snapshot: ContextSnapshot) -> list[Message]:
    messages: list[Message] = []
    for segment in snapshot.window.segments:
        for item in segment.items:
            if item.message is not None:
                messages.append(item.message)
    return messages
