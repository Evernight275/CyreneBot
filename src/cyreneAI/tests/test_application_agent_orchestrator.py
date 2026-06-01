from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest

from cyreneAI.application.agent.orchestrator import (
    AgentOrchestrator,
    AgentRunRequest,
    AgentStopReason,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.errors.base import StateError
from cyreneAI.core.errors.tool import ToolExecutionError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.agent import (
    AgentMemoryRetrievalConfig,
    AgentPlanningConfig,
    AgentToolSelectionConfig,
)
from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest, ChatResponse
from cyreneAI.core.schema.context import (
    ContextItem,
    ContextItemSource,
    ContextItemType,
    ContextSegment,
    ContextSegmentRole,
    ContextSnapshot,
)
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolChoice,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolResult,
)
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


class MemorySearchToolExecutor:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content=json.dumps(
                {
                    "matches": [
                        {
                            "memory_id": "memory:session-1:1",
                            "content": "The user prefers concise answers.",
                            "score": 0.91,
                            "metadata": {"namespace": "session-1"},
                        }
                    ]
                },
                sort_keys=True,
            ),
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
            snapshot
            for snapshot in self.snapshots
            if snapshot.session_id == session_id
        ]

    async def delete_snapshot(self, snapshot_id: str) -> None:
        self.snapshots = [
            snapshot
            for snapshot in self.snapshots
            if snapshot.snapshot_id != snapshot_id
        ]


async def _build_provider_manager(provider: FakeChatProvider) -> ProviderManager:
    factory = ProviderFactory()

    async def build_provider(config: ProviderConfig) -> FakeChatProvider:
        return provider

    factory.register(ProviderType.OPENAI_COMPATIBLE, build_provider)
    manager = ProviderManager(factory)
    await manager.add(provider.config)
    return manager


async def _build_runtime(
    provider: FakeChatProvider,
    tool_registry: ToolRegistry | None = None,
    *,
    with_tool_manager: bool = True,
    context_manager: ContextManager | None = None,
) -> CyreneAIRuntime:
    provider_manager = await _build_provider_manager(provider)
    return CyreneAIRuntime(
        provider_manager=provider_manager,
        context_builder=ContextWindowBuilder(),
        context_manager=context_manager,
        tool_registry=tool_registry,
        tool_manager=(
            ToolManager(tool_registry)
            if with_tool_manager and tool_registry is not None
            else None
        ),
    )


async def _run_agent_executes_tool_and_returns_final_response() -> None:
    tool_call = ToolCall(
        id="call-1",
        name="lookup",
        arguments="{\"query\":\"delta\"}",
    )
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=Message(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[tool_call],
                ),
                tool_calls=[tool_call],
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
    executor = RecordingToolExecutor()
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="lookup", description="Lookup a value."),
        executor,
    )
    runtime = await _build_runtime(provider, tool_registry)

    result = await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="Find the answer.",
            messages=[_message(MessageRole.USER, "Use a tool.")],
        )
    )

    assert result.completed is True
    assert result.stop_reason == AgentStopReason.FINAL_RESPONSE
    assert result.response.message == _message(MessageRole.ASSISTANT, "final")
    assert len(result.steps) == 2
    assert result.steps[0].tool_calls == [tool_call]
    assert result.steps[0].tool_results[0].content == "executed:lookup"
    assert result.context_snapshot.session_id == "session-1"
    assert result.context_snapshot.window.segments[-1].role == ContextSegmentRole.WORKING
    assert executor.calls == [tool_call]

    first_request = provider.requests[0]
    assert first_request.tools is not None
    assert [tool.name for tool in first_request.tools] == ["lookup"]
    assert first_request.metadata["session_id"] == "session-1"
    assert first_request.metadata["agent_loop"] == "minimal"
    assert first_request.messages == [
        _message(MessageRole.USER, "Find the answer."),
        _message(MessageRole.USER, "Use a tool."),
    ]

    feedback_request = provider.requests[1]
    assert feedback_request.messages[-2].role == MessageRole.ASSISTANT
    assert feedback_request.messages[-2].tool_calls == [tool_call]
    assert feedback_request.messages[-1].role == MessageRole.TOOL
    assert feedback_request.messages[-1].name == "lookup"
    assert feedback_request.messages[-1].tool_call_id == "call-1"
    assert feedback_request.messages[-1].content is not None
    assert feedback_request.messages[-1].content[0].text == "executed:lookup"


def test_agent_orchestrator_executes_tool_and_returns_final_response() -> None:
    asyncio.run(_run_agent_executes_tool_and_returns_final_response())


async def _run_agent_builds_prompt_from_context_window() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            message=_message(MessageRole.ASSISTANT, "final"),
            finish_reason=ChatFinishReason.STOP,
        )
    )
    context_store = FakeContextStore()
    runtime = await _build_runtime(
        provider,
        context_manager=ContextManager(context_store),
    )

    result = await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="Use indexed context.",
            additional_context_segments=[
                ContextSegment(
                    segment_id="retrieved",
                    role=ContextSegmentRole.RETRIEVED,
                    items=[
                        ContextItem(
                            item_id="retrieved-1",
                            type=ContextItemType.RETRIEVED,
                            source=ContextItemSource.RETRIEVER,
                            content="Relevant indexed memory.",
                        )
                    ],
                )
            ],
        )
    )

    assert provider.requests[0].messages == [
        _message(MessageRole.USER, "Use indexed context."),
        _message(MessageRole.SYSTEM, "Relevant indexed memory."),
    ]
    assert context_store.snapshots == [result.context_snapshot]
    assert result.context_snapshot.window.segments[1].segment_id == "retrieved"
    assert result.context_snapshot.window.segments[-1].role == ContextSegmentRole.WORKING


def test_agent_orchestrator_builds_prompt_from_context_window() -> None:
    asyncio.run(_run_agent_builds_prompt_from_context_window())


async def _run_agent_stops_after_max_steps() -> None:
    tool_call = ToolCall(id="call-1", name="lookup", arguments="{}")
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            tool_calls=[tool_call],
            finish_reason=ChatFinishReason.TOOL_CALLS,
        )
    )
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="lookup", description="Lookup a value."),
        RecordingToolExecutor(),
    )
    runtime = await _build_runtime(provider, tool_registry)

    result = await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="Keep going.",
            max_steps=1,
        )
    )

    assert result.completed is False
    assert result.stop_reason == AgentStopReason.MAX_STEPS
    assert len(result.steps) == 1
    assert result.steps[0].tool_calls == [tool_call]
    assert result.steps[0].tool_results[0].name == "lookup"
    assert len(provider.requests) == 1


def test_agent_orchestrator_stops_after_max_steps() -> None:
    asyncio.run(_run_agent_stops_after_max_steps())


async def _run_agent_rejects_disallowed_tool_call() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            tool_calls=[
                ToolCall(
                    id="call-1",
                    name="delete",
                    arguments="{}",
                )
            ],
            finish_reason=ChatFinishReason.TOOL_CALLS,
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
    runtime = await _build_runtime(provider, tool_registry)

    with pytest.raises(ToolExecutionError):
        await AgentOrchestrator(runtime).run(
            AgentRunRequest(
                session_id="session-1",
                provider_id="provider-1",
                model="fake-model",
                goal="Use tools.",
                allowed_tool_names=["lookup"],
            )
        )

    assert delete_executor.calls == []
    assert provider.requests[0].tools is not None
    assert [tool.name for tool in provider.requests[0].tools] == ["lookup"]


def test_agent_orchestrator_rejects_disallowed_tool_call() -> None:
    asyncio.run(_run_agent_rejects_disallowed_tool_call())


async def _run_agent_intersects_policy_and_legacy_allowed_tools() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            message=_message(MessageRole.ASSISTANT, "final"),
            finish_reason=ChatFinishReason.STOP,
        )
    )
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="lookup", description="Lookup a value."),
        RecordingToolExecutor(),
    )
    tool_registry.register(
        ToolDefinition(name="delete", description="Delete a value."),
        RecordingToolExecutor(),
    )
    runtime = await _build_runtime(provider, tool_registry)

    await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="Use tools.",
            allowed_tool_names=["lookup"],
            tool_execution_policy=ToolExecutionPolicy(
                allowed_tool_names=["lookup", "delete"]
            ),
            tool_choice=ToolChoice(mode="tool", name="delete"),
        )
    )

    assert provider.requests[0].tools is not None
    assert [tool.name for tool in provider.requests[0].tools] == ["lookup"]
    assert provider.requests[0].tool_choice is None


def test_agent_orchestrator_intersects_policy_and_legacy_allowed_tools() -> None:
    asyncio.run(_run_agent_intersects_policy_and_legacy_allowed_tools())


async def _run_agent_builds_plan_and_selects_tools() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            message=_message(MessageRole.ASSISTANT, "final"),
            finish_reason=ChatFinishReason.STOP,
        )
    )
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="lookup", description="Lookup a value."),
        RecordingToolExecutor(),
    )
    tool_registry.register(
        ToolDefinition(name="delete", description="Delete a value."),
        RecordingToolExecutor(),
    )
    runtime = await _build_runtime(provider, tool_registry)

    result = await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="Find the project status.",
            planning=AgentPlanningConfig(
                enabled=True,
                instructions="Prefer low-risk tools first.",
                max_objectives=2,
            ),
            tool_selection=AgentToolSelectionConfig(
                allowed_tool_names=["lookup"],
                denied_tool_names=["delete"],
            ),
            tool_choice=ToolChoice(mode="tool", name="delete"),
        )
    )

    assert result.plan is not None
    assert result.plan.goal == "Find the project status."
    assert result.plan.selected_tool_names == ["lookup"]
    assert len(result.plan.objectives) == 2
    assert result.plan.instructions == "Prefer low-risk tools first."

    first_request = provider.requests[0]
    assert first_request.tools is not None
    assert [tool.name for tool in first_request.tools] == ["lookup"]
    assert first_request.tool_choice is None
    assert first_request.messages[0].role == MessageRole.SYSTEM
    assert first_request.messages[0].name == "agent_plan"
    assert first_request.messages[0].content is not None
    assert "Prefer low-risk tools first." in first_request.messages[0].content[0].text


def test_agent_orchestrator_builds_plan_and_selects_tools() -> None:
    asyncio.run(_run_agent_builds_plan_and_selects_tools())


async def _run_agent_retrieves_memory_before_first_step() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            message=_message(MessageRole.ASSISTANT, "final"),
            finish_reason=ChatFinishReason.STOP,
        )
    )
    memory_executor = MemorySearchToolExecutor()
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="search_memory", description="Search memory."),
        memory_executor,
    )
    runtime = await _build_runtime(provider, tool_registry)

    result = await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="How should you answer me?",
            planning=AgentPlanningConfig(enabled=True),
            memory_retrieval=AgentMemoryRetrievalConfig(
                enabled=True,
                query="answer style",
                top_k=3,
            ),
        )
    )

    assert len(memory_executor.calls) == 1
    assert memory_executor.calls[0].name == "search_memory"
    assert memory_executor.calls[0].arguments is not None
    assert json.loads(memory_executor.calls[0].arguments) == {
        "query": "answer style",
        "top_k": 3,
    }
    assert result.plan is not None
    assert result.plan.memory_query == "answer style"
    assert result.plan.metadata["memory_match_count"] == 1

    first_request = provider.requests[0]
    assert first_request.messages[0].name == "agent_plan"
    assert first_request.messages[-1].role == MessageRole.SYSTEM
    assert first_request.messages[-1].content is not None
    assert first_request.messages[-1].content[0].text == (
        "The user prefers concise answers."
    )

    memory_segment = result.context_snapshot.window.segments[1]
    assert memory_segment.role == ContextSegmentRole.MEMORY
    assert memory_segment.items[0].type == ContextItemType.MEMORY
    assert memory_segment.items[0].metadata["memory_id"] == "memory:session-1:1"


def test_agent_orchestrator_retrieves_memory_before_first_step() -> None:
    asyncio.run(_run_agent_retrieves_memory_before_first_step())


async def _run_agent_requires_tool_manager_for_tool_calls() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            tool_calls=[ToolCall(id="call-1", name="lookup", arguments="{}")],
            finish_reason=ChatFinishReason.TOOL_CALLS,
        )
    )
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="lookup", description="Lookup a value."),
        RecordingToolExecutor(),
    )
    runtime = await _build_runtime(
        provider,
        tool_registry,
        with_tool_manager=False,
    )

    with pytest.raises(StateError):
        await AgentOrchestrator(runtime).run(
            AgentRunRequest(
                session_id="session-1",
                provider_id="provider-1",
                model="fake-model",
                goal="Use tools.",
            )
        )


def test_agent_orchestrator_requires_tool_manager_for_tool_calls() -> None:
    asyncio.run(_run_agent_requires_tool_manager_for_tool_calls())
