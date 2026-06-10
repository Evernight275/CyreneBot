from __future__ import annotations

import asyncio
import json
from datetime import timedelta

from cyreneAI.application.agent.orchestrator import (
    AgentOrchestrator,
    AgentRunRequest,
    AgentStopReason,
)
from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.context.manager import ContextManager
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.agent import (
    AgentMemoryRetrievalConfig,
    AgentPlanningConfig,
    AgentPlanningMode,
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
    ContextWindow,
)
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderInfo, ProviderType
from cyreneAI.core.schema.skill import SkillDefinition
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolChoice,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolResult,
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


class LongOutputToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content="abcdefghijklmnopqrstuvwxyz",
        )


class AssumptionChangingToolExecutor:
    async def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            content="assumption changed",
            metadata={"agent_assumption_changed": True},
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
    skill_manager: SkillManager | None = None,
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
        skill_manager=skill_manager,
    )


async def _run_agent_executes_tool_and_returns_final_response() -> None:
    tool_call = ToolCall(
        id="call-1",
        name="lookup",
        arguments='{"query":"delta"}',
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
    assert (
        result.context_snapshot.window.segments[-1].role == ContextSegmentRole.WORKING
    )
    assert result.context_snapshot.metadata["completed"] is True
    assert result.context_snapshot.metadata["stop_reason"] == "final_response"
    assert isinstance(result.context_snapshot.metadata["finished_at"], str)
    assert result.context_snapshot.metadata["finished_at"]
    assert result.context_snapshot.metadata["step_count"] == 2
    assert result.context_snapshot.metadata["tool_call_count"] == 1
    assert result.context_snapshot.metadata["tool_result_count"] == 1
    assert result.context_snapshot.metadata["tool_error_count"] == 0
    assert result.context_snapshot.metadata["tool_names"] == ["lookup"]
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
    assert (
        result.context_snapshot.window.segments[-1].role == ContextSegmentRole.WORKING
    )


def test_agent_orchestrator_builds_prompt_from_context_window() -> None:
    asyncio.run(_run_agent_builds_prompt_from_context_window())


async def _run_agent_loads_session_history_before_current_messages() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            message=_message(MessageRole.ASSISTANT, "final"),
            finish_reason=ChatFinishReason.STOP,
        )
    )
    context_store = FakeContextStore()
    context_store.snapshots.append(
        ContextSnapshot(
            snapshot_id="snapshot-1",
            session_id="session-1",
            window=ContextWindow(
                window_id="window-1",
                segments=[
                    ContextSegment(
                        segment_id="history",
                        role=ContextSegmentRole.HISTORY,
                        items=[
                            ContextItem(
                                item_id="history-1",
                                type=ContextItemType.MESSAGE,
                                source=ContextItemSource.USER,
                                message=_message(MessageRole.USER, "Earlier context."),
                            )
                        ],
                    )
                ],
            ),
        )
    )
    runtime = await _build_runtime(
        provider,
        context_manager=ContextManager(context_store),
    )

    await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="Continue from there.",
        )
    )

    assert provider.requests[0].messages == [
        _message(MessageRole.USER, "Earlier context."),
        _message(MessageRole.USER, "Continue from there."),
    ]


def test_agent_orchestrator_loads_session_history_before_current_messages() -> None:
    asyncio.run(_run_agent_loads_session_history_before_current_messages())


async def _run_agent_stops_after_max_steps() -> None:
    tool_call = ToolCall(id="call-1", name="lookup", arguments="{}")
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                tool_calls=[tool_call],
                finish_reason=ChatFinishReason.TOOL_CALLS,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "final after tool"),
                finish_reason=ChatFinishReason.STOP,
            ),
        ]
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
            planning=AgentPlanningConfig(enabled=True, max_objectives=2),
        )
    )

    assert result.completed is False
    assert result.stop_reason == AgentStopReason.MAX_STEPS
    assert result.response.message == _message(
        MessageRole.ASSISTANT, "final after tool"
    )
    assert len(result.steps) == 2
    assert result.steps[0].tool_calls == [tool_call]
    assert result.steps[0].tool_results[0].name == "lookup"
    assert result.steps[1].tool_calls == []
    assert result.steps[1].request.tools is None
    assert result.steps[1].request.tool_choice is None
    assert result.steps[1].request.metadata["agent_max_steps_finalization"] is True
    final_plan_execution = result.steps[1].metadata["plan_execution"]
    assert isinstance(final_plan_execution, dict)
    assert final_plan_execution["status"] == "finalizing"
    assert final_plan_execution["completed"] is False
    assert final_plan_execution["deviation_reason"] == "agent_max_steps_finalization"
    assert final_plan_execution["finalization_reason"] == (
        "agent_max_steps_finalization"
    )
    assert len(provider.requests) == 2


def test_agent_orchestrator_stops_after_max_steps() -> None:
    asyncio.run(_run_agent_stops_after_max_steps())


async def _run_agent_completes_multi_step_tool_loop() -> None:
    first_call = ToolCall(id="call-1", name="lookup", arguments='{"step":1}')
    second_call = ToolCall(id="call-2", name="lookup", arguments='{"step":2}')
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=Message(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[first_call],
                ),
                tool_calls=[first_call],
                finish_reason=ChatFinishReason.TOOL_CALLS,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=Message(
                    role=MessageRole.ASSISTANT,
                    tool_calls=[second_call],
                ),
                tool_calls=[second_call],
                finish_reason=ChatFinishReason.TOOL_CALLS,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "multi-step final"),
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
            goal="Use two tool steps, then answer.",
            max_steps=3,
        )
    )

    assert result.completed is True
    assert result.stop_reason == AgentStopReason.FINAL_RESPONSE
    assert result.response.message == _message(
        MessageRole.ASSISTANT, "multi-step final"
    )
    assert len(result.steps) == 3
    assert executor.calls == [first_call, second_call]
    assert result.metadata["tool_call_count"] == 2
    assert result.metadata["tool_result_count"] == 2
    assert len(provider.requests) == 3
    assert provider.requests[1].messages[-1].tool_call_id == "call-1"
    assert provider.requests[2].messages[-1].tool_call_id == "call-2"
    assert "agent_max_steps_finalization" not in provider.requests[-1].metadata


def test_agent_orchestrator_completes_multi_step_tool_loop() -> None:
    asyncio.run(_run_agent_completes_multi_step_tool_loop())


async def _run_agent_rejects_disallowed_tool_call() -> None:
    provider = FakeChatProvider(
        [
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
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "cannot delete"),
                finish_reason=ChatFinishReason.STOP,
            ),
        ]
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

    result = await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="Use tools.",
            allowed_tool_names=["lookup"],
        )
    )

    assert result.completed is True
    assert result.steps[0].tool_results[0].success is False
    assert result.steps[0].tool_results[0].error == "Tool delete is not allowed"
    assert result.metadata["tool_error_count"] == 1
    assert delete_executor.calls == []
    assert provider.requests[0].tools is not None
    assert [tool.name for tool in provider.requests[0].tools] == ["lookup"]
    assert provider.requests[1].messages[-1].role == MessageRole.TOOL
    assert provider.requests[1].messages[-1].tool_call_id == "call-1"


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
    assert len(result.plan.steps) == 2
    assert result.plan.instructions == "Prefer low-risk tools first."
    assert result.plan.constraints.selected_tool_names == ["lookup"]
    assert result.plan.constraints.denied_tool_names == ["delete"]
    assert result.plan.metadata["planning_mode"] == "planner_step"

    first_request = provider.requests[0]
    assert first_request.tools is not None
    assert [tool.name for tool in first_request.tools] == ["lookup"]
    assert first_request.tool_choice is None
    assert first_request.messages[0].role == MessageRole.SYSTEM
    assert first_request.messages[0].name == "agent_plan"
    assert first_request.messages[0].content is not None
    assert first_request.metadata["agent_plan_mode"] == "planner_step"
    assert first_request.metadata["agent_plan_step_count"] == 2
    assert "Prefer low-risk tools first." in first_request.messages[0].content[0].text
    assert "Steps:" in first_request.messages[0].content[0].text
    assert "Denied tools: delete" in first_request.messages[0].content[0].text


def test_agent_orchestrator_builds_plan_and_selects_tools() -> None:
    asyncio.run(_run_agent_builds_plan_and_selects_tools())


async def _run_agent_builds_llm_plan_from_provider_response() -> None:
    planner_payload = {
        "goal": "Find the project status.",
        "objectives": [
            "Inspect available project status evidence.",
            "Return the current status.",
        ],
        "steps": [
            {
                "objective": "Inspect available project status evidence.",
                "action": "Use lookup for current project status.",
                "tool_names": ["lookup", "delete"],
                "skill_names": [],
            },
            {
                "objective": "Return the current status.",
                "action": "Summarize the status from evidence.",
                "tool_names": [],
                "skill_names": [],
            },
        ],
    }
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="planner-model",
                message=_message(
                    MessageRole.ASSISTANT,
                    json.dumps(planner_payload, sort_keys=True),
                ),
                finish_reason=ChatFinishReason.STOP,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "final"),
                finish_reason=ChatFinishReason.STOP,
            ),
        ]
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
                mode=AgentPlanningMode.LLM,
                instructions="Prefer low-risk tools first.",
                max_objectives=3,
                max_plan_steps=3,
                planner_model="planner-model",
            ),
            tool_selection=AgentToolSelectionConfig(
                allowed_tool_names=["lookup"],
                denied_tool_names=["delete"],
            ),
        )
    )

    assert result.plan is not None
    assert result.plan.goal == "Find the project status."
    assert result.plan.objectives == [
        "Inspect available project status evidence.",
        "Return the current status.",
    ]
    assert result.plan.steps[0].action == "Use lookup for current project status."
    assert result.plan.steps[0].tool_names == ["lookup"]
    assert result.plan.steps[1].tool_names == []
    assert result.plan.selected_tool_names == ["lookup"]
    assert result.plan.constraints.denied_tool_names == ["delete"]
    assert result.plan.metadata["planning_mode"] == "llm"
    assert result.plan.metadata["planner_model"] == "planner-model"

    planner_request = provider.requests[0]
    assert planner_request.model == "planner-model"
    assert planner_request.tools is None
    assert planner_request.metadata["agent_planner"] is True
    assert planner_request.metadata["agent_planner_mode"] == "llm"
    assert planner_request.messages[0].name == "agent_planner"
    assert planner_request.messages[1].content is not None
    planner_request_payload = json.loads(planner_request.messages[1].content[0].text)
    assert planner_request_payload["constraints"]["selected_tool_names"] == ["lookup"]
    assert planner_request_payload["constraints"]["denied_tool_names"] == ["delete"]

    agent_request = provider.requests[1]
    assert agent_request.model == "fake-model"
    assert agent_request.messages[0].name == "agent_plan"
    assert agent_request.metadata["agent_plan_mode"] == "llm"
    assert agent_request.metadata["agent_plan_step_count"] == 2
    plan_execution = result.steps[0].metadata["plan_execution"]
    assert isinstance(plan_execution, dict)
    assert plan_execution["status"] == "deviated"
    assert plan_execution["completed"] is False
    assert plan_execution["plan_step_index"] == 0
    assert plan_execution["expected_tool_names"] == ["lookup"]
    assert plan_execution["actual_tool_names"] == []
    assert plan_execution["deviation_reason"] == "planned_tool_not_called"


def test_agent_orchestrator_builds_llm_plan_from_provider_response() -> None:
    asyncio.run(_run_agent_builds_llm_plan_from_provider_response())


async def _run_agent_records_plan_execution_awareness() -> None:
    tool_call = ToolCall(
        id="call-1",
        name="lookup",
        arguments='{"query":"status"}',
    )
    planner_payload = {
        "goal": "Find the project status.",
        "objectives": [
            "Look up project status evidence.",
            "Return the final status.",
        ],
        "steps": [
            {
                "objective": "Look up project status evidence.",
                "action": "Call lookup for current project status.",
                "tool_names": ["lookup"],
                "skill_names": [],
            },
            {
                "objective": "Return the final status.",
                "action": "Answer from the lookup result.",
                "tool_names": [],
                "skill_names": [],
            },
        ],
    }
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="planner-model",
                message=_message(
                    MessageRole.ASSISTANT,
                    json.dumps(planner_payload, sort_keys=True),
                ),
                finish_reason=ChatFinishReason.STOP,
            ),
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
                message=_message(MessageRole.ASSISTANT, "final status"),
                finish_reason=ChatFinishReason.STOP,
            ),
        ]
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
            goal="Find the project status.",
            planning=AgentPlanningConfig(
                enabled=True,
                mode=AgentPlanningMode.LLM,
                planner_model="planner-model",
            ),
            tool_selection=AgentToolSelectionConfig(
                allowed_tool_names=["lookup"],
            ),
        )
    )

    assert result.completed is True
    assert len(result.steps) == 2

    first_plan_execution = result.steps[0].metadata["plan_execution"]
    assert isinstance(first_plan_execution, dict)
    assert first_plan_execution["tracked"] is True
    assert first_plan_execution["status"] == "in_progress"
    assert first_plan_execution["completed"] is False
    assert first_plan_execution["deviation_reason"] is None
    assert first_plan_execution["plan_step_index"] == 0
    assert first_plan_execution["plan_step_objective"] == (
        "Look up project status evidence."
    )
    assert first_plan_execution["expected_tool_names"] == ["lookup"]
    assert first_plan_execution["actual_tool_names"] == ["lookup"]

    final_plan_execution = result.steps[1].metadata["plan_execution"]
    assert isinstance(final_plan_execution, dict)
    assert final_plan_execution["tracked"] is True
    assert final_plan_execution["status"] == "completed"
    assert final_plan_execution["completed"] is True
    assert final_plan_execution["deviation_reason"] is None
    assert final_plan_execution["plan_step_index"] == 1
    assert final_plan_execution["expected_tool_names"] == []
    assert final_plan_execution["actual_tool_names"] == []

    assert result.metadata["steps"][0]["plan_execution"] == first_plan_execution
    assert result.metadata["steps"][1]["plan_execution"] == final_plan_execution

    trace_items = result.context_snapshot.window.segments[-1].items
    assert len(trace_items) == 3
    assert trace_items[0].metadata["agent_step_index"] == 0
    assert trace_items[0].metadata["agent_trace_kind"] == "assistant"
    assert trace_items[0].metadata["plan_execution"] == first_plan_execution
    assert trace_items[1].metadata["agent_step_index"] == 0
    assert trace_items[1].metadata["agent_trace_kind"] == "tool"
    assert trace_items[1].metadata["tool_name"] == "lookup"
    assert trace_items[1].metadata["tool_success"] is True
    assert trace_items[1].metadata["plan_execution"] == first_plan_execution
    assert trace_items[2].metadata["agent_step_index"] == 1
    assert trace_items[2].metadata["agent_trace_kind"] == "assistant"
    assert trace_items[2].metadata["plan_execution"] == final_plan_execution


def test_agent_orchestrator_records_plan_execution_awareness() -> None:
    asyncio.run(_run_agent_records_plan_execution_awareness())


async def _run_agent_replans_after_planned_tool_is_not_called() -> None:
    initial_plan_payload = {
        "goal": "Find the project status.",
        "objectives": ["Look up project status evidence."],
        "steps": [
            {
                "objective": "Look up project status evidence.",
                "action": "Call lookup before answering.",
                "tool_names": ["lookup"],
                "skill_names": [],
            }
        ],
    }
    revised_plan_payload = {
        "goal": "Find the project status.",
        "objectives": ["Answer from the available context."],
        "steps": [
            {
                "objective": "Answer from the available context.",
                "action": "Return the best available answer without tools.",
                "tool_names": [],
                "skill_names": [],
            }
        ],
    }
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="planner-model",
                message=_message(
                    MessageRole.ASSISTANT,
                    json.dumps(initial_plan_payload, sort_keys=True),
                ),
                finish_reason=ChatFinishReason.STOP,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "premature final"),
                finish_reason=ChatFinishReason.STOP,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="planner-model",
                message=_message(
                    MessageRole.ASSISTANT,
                    json.dumps(revised_plan_payload, sort_keys=True),
                ),
                finish_reason=ChatFinishReason.STOP,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "final after replan"),
                finish_reason=ChatFinishReason.STOP,
            ),
        ]
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
            goal="Find the project status.",
            max_steps=3,
            planning=AgentPlanningConfig(
                enabled=True,
                mode=AgentPlanningMode.LLM,
                planner_model="planner-model",
                replanning_enabled=True,
                max_replans=1,
            ),
            tool_selection=AgentToolSelectionConfig(
                allowed_tool_names=["lookup"],
            ),
        )
    )

    assert result.completed is True
    assert result.response.message == _message(
        MessageRole.ASSISTANT,
        "final after replan",
    )
    assert result.plan is not None
    assert result.plan.metadata["replanned"] is True
    assert result.plan.metadata["replan_reason"] == "planned_tool_not_called"
    assert result.metadata["replan_count"] == 1
    assert result.metadata["replan_reasons"] == ["planned_tool_not_called"]

    first_step = result.steps[0]
    assert first_step.metadata["replan_triggered"] is True
    assert first_step.metadata["replan_reason"] == "planned_tool_not_called"
    assert first_step.metadata["replanned_plan_step_count"] == 1

    replan_request = provider.requests[2]
    assert replan_request.metadata["agent_planner"] is True
    assert replan_request.messages[1].content is not None
    replan_payload = json.loads(replan_request.messages[1].content[0].text)
    assert replan_payload["replan_context"]["replan_reasons"] == [
        "planned_tool_not_called"
    ]
    assert replan_payload["replan_context"]["trigger_step"]["index"] == 0

    second_agent_request = provider.requests[3]
    assert second_agent_request.messages[-1].name == "agent_replan"
    assert second_agent_request.metadata["agent_replan_count"] == 1
    assert second_agent_request.metadata["agent_replan_reason"] == (
        "planned_tool_not_called"
    )


def test_agent_orchestrator_replans_after_planned_tool_is_not_called() -> None:
    asyncio.run(_run_agent_replans_after_planned_tool_is_not_called())


async def _run_agent_replans_when_tool_result_changes_assumptions() -> None:
    tool_call = ToolCall(id="call-1", name="lookup", arguments="{}")
    initial_plan_payload = {
        "goal": "Find the project status.",
        "objectives": ["Look up project status evidence."],
        "steps": [
            {
                "objective": "Look up project status evidence.",
                "action": "Call lookup.",
                "tool_names": ["lookup"],
                "skill_names": [],
            }
        ],
    }
    revised_plan_payload = {
        "goal": "Find the project status.",
        "objectives": ["Adapt to changed assumptions."],
        "steps": [
            {
                "objective": "Adapt to changed assumptions.",
                "action": "Answer with the updated evidence.",
                "tool_names": [],
                "skill_names": [],
            }
        ],
    }
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="planner-model",
                message=_message(
                    MessageRole.ASSISTANT,
                    json.dumps(initial_plan_payload, sort_keys=True),
                ),
                finish_reason=ChatFinishReason.STOP,
            ),
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
                model="planner-model",
                message=_message(
                    MessageRole.ASSISTANT,
                    json.dumps(revised_plan_payload, sort_keys=True),
                ),
                finish_reason=ChatFinishReason.STOP,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "updated final"),
                finish_reason=ChatFinishReason.STOP,
            ),
        ]
    )
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(name="lookup", description="Lookup a value."),
        AssumptionChangingToolExecutor(),
    )
    runtime = await _build_runtime(provider, tool_registry)

    result = await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="Find the project status.",
            max_steps=3,
            planning=AgentPlanningConfig(
                enabled=True,
                mode=AgentPlanningMode.LLM,
                planner_model="planner-model",
                replanning_enabled=True,
                max_replans=1,
            ),
            tool_selection=AgentToolSelectionConfig(
                allowed_tool_names=["lookup"],
            ),
        )
    )

    assert result.completed is True
    assert result.metadata["replan_count"] == 1
    assert result.metadata["replan_reasons"] == ["tool_result_changed_assumption"]
    assert result.steps[0].metadata["replan_triggered"] is True
    assert result.steps[0].metadata["replan_reason"] == (
        "tool_result_changed_assumption"
    )
    assert result.steps[0].tool_results[0].metadata["agent_assumption_changed"] is True

    replan_request = provider.requests[2]
    assert replan_request.messages[1].content is not None
    replan_payload = json.loads(replan_request.messages[1].content[0].text)
    assert replan_payload["replan_context"]["replan_reasons"] == [
        "tool_result_changed_assumption"
    ]
    assert (
        replan_payload["replan_context"]["trigger_step"]["tool_results"][0]["metadata"][
            "agent_assumption_changed"
        ]
        is True
    )

    second_agent_request = provider.requests[3]
    assert second_agent_request.messages[-2].role == MessageRole.TOOL
    assert second_agent_request.messages[-1].name == "agent_replan"


def test_agent_orchestrator_replans_when_tool_result_changes_assumptions() -> None:
    asyncio.run(_run_agent_replans_when_tool_result_changes_assumptions())


async def _run_agent_skips_replan_after_max_replans() -> None:
    plan_payload = {
        "goal": "Find the project status.",
        "objectives": ["Look up project status evidence."],
        "steps": [
            {
                "objective": "Look up project status evidence.",
                "action": "Call lookup before answering.",
                "tool_names": ["lookup"],
                "skill_names": [],
            }
        ],
    }
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="planner-model",
                message=_message(
                    MessageRole.ASSISTANT,
                    json.dumps(plan_payload, sort_keys=True),
                ),
                finish_reason=ChatFinishReason.STOP,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "premature final"),
                finish_reason=ChatFinishReason.STOP,
            ),
        ]
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
            goal="Find the project status.",
            planning=AgentPlanningConfig(
                enabled=True,
                mode=AgentPlanningMode.LLM,
                planner_model="planner-model",
                replanning_enabled=True,
                max_replans=0,
            ),
            tool_selection=AgentToolSelectionConfig(
                allowed_tool_names=["lookup"],
            ),
        )
    )

    assert result.completed is True
    assert result.metadata["replan_count"] == 0
    assert result.metadata["replan_reasons"] == ["planned_tool_not_called"]
    assert len(provider.requests) == 2
    assert result.steps[0].metadata["replan_skipped"] is True
    assert result.steps[0].metadata["replan_skip_reason"] == "max_replans_reached"
    assert result.steps[0].metadata["replan_reasons"] == ["planned_tool_not_called"]


def test_agent_orchestrator_skips_replan_after_max_replans() -> None:
    asyncio.run(_run_agent_skips_replan_after_max_replans())


async def _run_agent_falls_back_when_llm_plan_is_invalid() -> None:
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "not json"),
                finish_reason=ChatFinishReason.STOP,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "final"),
                finish_reason=ChatFinishReason.STOP,
            ),
        ]
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
            goal="Find the project status.",
            planning=AgentPlanningConfig(
                enabled=True,
                mode=AgentPlanningMode.LLM,
                max_objectives=2,
            ),
        )
    )

    assert result.plan is not None
    assert result.plan.metadata["planning_mode"] == "planner_step"
    assert result.plan.metadata["planning_fallback"] is True
    assert result.plan.metadata["planning_fallback_from"] == "llm"
    assert result.plan.metadata["requested_planning_mode"] == "llm"
    assert result.plan.metadata["planning_error_type"] == "ValidationError"
    assert len(result.plan.objectives) == 2

    assert provider.requests[0].metadata["agent_planner"] is True
    assert provider.requests[1].metadata["agent_plan_mode"] == "planner_step"
    assert provider.requests[1].messages[0].name == "agent_plan"


def test_agent_orchestrator_falls_back_when_llm_plan_is_invalid() -> None:
    asyncio.run(_run_agent_falls_back_when_llm_plan_is_invalid())


async def _run_agent_builds_skill_bundle_and_constrains_tools() -> None:
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
    skill_registry = SkillRegistry()
    skill_registry.register(
        SkillDefinition(
            name="project_status",
            description="Project status style.",
            instructions="Answer with project status discipline.",
            allowed_tools=["lookup"],
        )
    )
    runtime = await _build_runtime(
        provider,
        tool_registry,
        skill_manager=SkillManager(skill_registry),
    )

    result = await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="Find the project status.",
            required_skill_names=["project_status"],
            tool_selection=AgentToolSelectionConfig(
                allowed_tool_names=["lookup", "delete"]
            ),
        )
    )

    assert result.skill_bundle is not None
    assert result.skill_bundle.metadata["skills"] == ["project_status"]

    first_request = provider.requests[0]
    assert first_request.messages[0].role == MessageRole.SYSTEM
    assert first_request.messages[0].name == "skills"
    assert first_request.messages[0].content is not None
    assert (
        "Answer with project status discipline."
        in first_request.messages[0].content[0].text
    )
    assert first_request.tools is not None
    assert [tool.name for tool in first_request.tools] == ["lookup"]
    assert first_request.metadata["skill_names"] == ["project_status"]


def test_agent_orchestrator_builds_skill_bundle_and_constrains_tools() -> None:
    asyncio.run(_run_agent_builds_skill_bundle_and_constrains_tools())


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
    assert result.plan.metadata["planning_mode"] == "planner_step"
    assert any(step.tool_names == ["search_memory"] for step in result.plan.steps)

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


async def _run_agent_skips_memory_retrieval_when_tool_is_missing() -> None:
    provider = FakeChatProvider(
        ChatResponse(
            provider_id="provider-1",
            model="fake-model",
            message=_message(MessageRole.ASSISTANT, "final"),
            finish_reason=ChatFinishReason.STOP,
        )
    )
    runtime = await _build_runtime(provider)

    result = await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="Use memory if available.",
            memory_retrieval=AgentMemoryRetrievalConfig(enabled=True),
        )
    )

    assert result.completed is True
    assert result.metadata["memory_retrieval_status"] == "skipped"
    assert result.metadata["memory_retrieval_error"] == (
        "Agent memory retrieval requires a tool manager"
    )
    assert provider.requests[0].messages == [
        _message(MessageRole.USER, "Use memory if available."),
    ]


def test_agent_orchestrator_skips_memory_retrieval_when_tool_is_missing() -> None:
    asyncio.run(_run_agent_skips_memory_retrieval_when_tool_is_missing())


async def _run_agent_stops_when_tool_call_limit_is_exceeded() -> None:
    first_call = ToolCall(id="call-1", name="lookup", arguments="{}")
    second_call = ToolCall(id="call-2", name="lookup", arguments="{}")
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                tool_calls=[first_call, second_call],
                finish_reason=ChatFinishReason.TOOL_CALLS,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "limited final"),
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
            goal="Use tools.",
            planning=AgentPlanningConfig(enabled=True, max_objectives=2),
            max_tool_calls_per_step=1,
        )
    )

    assert result.completed is False
    assert result.stop_reason == AgentStopReason.TOOL_LIMIT
    assert executor.calls == [first_call]
    assert result.steps[0].tool_results[0].success is True
    assert result.steps[0].tool_results[1].success is False
    assert result.steps[0].tool_results[1].metadata["agent_tool_limit_exceeded"] is True
    assert result.metadata["tool_error_count"] == 1
    assert provider.requests[1].tools is None
    assert provider.requests[1].metadata["agent_tool_limit_finalization"] is True
    limited_plan_execution = result.steps[0].metadata["plan_execution"]
    assert isinstance(limited_plan_execution, dict)
    assert limited_plan_execution["status"] == "deviated"
    assert limited_plan_execution["deviation_reason"] == "tool_limit_exceeded"
    final_plan_execution = result.steps[1].metadata["plan_execution"]
    assert isinstance(final_plan_execution, dict)
    assert final_plan_execution["status"] == "finalizing"
    assert final_plan_execution["deviation_reason"] == "agent_tool_limit_finalization"
    assert final_plan_execution["finalization_reason"] == (
        "agent_tool_limit_finalization"
    )


def test_agent_orchestrator_stops_when_tool_call_limit_is_exceeded() -> None:
    asyncio.run(_run_agent_stops_when_tool_call_limit_is_exceeded())


async def _run_agent_truncates_tool_result_content() -> None:
    tool_call = ToolCall(id="call-1", name="lookup", arguments="{}")
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
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
    tool_registry = ToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="lookup",
            description="Lookup a value.",
            safety_profile=ToolSafetyProfile(max_output_chars=12),
        ),
        LongOutputToolExecutor(),
    )
    runtime = await _build_runtime(provider, tool_registry)

    result = await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="Use tools.",
        )
    )

    tool_result = result.steps[0].tool_results[0]
    assert tool_result.content == "abcdefghijkl"
    assert tool_result.metadata["truncated"] is True
    assert tool_result.metadata["original_content_chars"] == 26
    assert provider.requests[1].messages[-1].content is not None
    assert provider.requests[1].messages[-1].content[0].text == "abcdefghijkl"


def test_agent_orchestrator_truncates_tool_result_content() -> None:
    asyncio.run(_run_agent_truncates_tool_result_content())


async def _run_agent_requires_tool_manager_for_tool_calls() -> None:
    provider = FakeChatProvider(
        [
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                tool_calls=[ToolCall(id="call-1", name="lookup", arguments="{}")],
                finish_reason=ChatFinishReason.TOOL_CALLS,
            ),
            ChatResponse(
                provider_id="provider-1",
                model="fake-model",
                message=_message(MessageRole.ASSISTANT, "tool unavailable"),
                finish_reason=ChatFinishReason.STOP,
            ),
        ]
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

    result = await AgentOrchestrator(runtime).run(
        AgentRunRequest(
            session_id="session-1",
            provider_id="provider-1",
            model="fake-model",
            goal="Use tools.",
        )
    )

    assert result.completed is True
    assert result.steps[0].tool_results[0].success is False
    assert result.steps[0].tool_results[0].error == "No tool manager is configured"
    assert provider.requests[1].messages[-1].role == MessageRole.TOOL


def test_agent_orchestrator_requires_tool_manager_for_tool_calls() -> None:
    asyncio.run(_run_agent_requires_tool_manager_for_tool_calls())
