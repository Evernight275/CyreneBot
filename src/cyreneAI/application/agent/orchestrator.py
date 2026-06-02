from __future__ import annotations

import json
from typing import Any, cast
from uuid import uuid4

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.application.tools.execution_policy import (
    build_effective_tool_execution_policy,
    filter_tool_definitions_for_policy,
)
from cyreneAI.application.tools.execution_context import use_tool_execution_context
from cyreneAI.core.errors.base import StateError, UnsupportedError
from cyreneAI.core.errors.tool import ToolExecutionError
from cyreneAI.core.provider.provider_protocol import ChatProviderProtocol
from cyreneAI.core.schema.agent import (
    AgentMemoryRetrievalConfig,
    AgentPlan,
    AgentPlanningConfig,
    AgentRunRequest,
    AgentRunResult,
    AgentStep,
    AgentStopReason,
)
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
from cyreneAI.core.schema.message import ContentPart, ContentPartType, Message, MessageRole
from cyreneAI.core.schema.skill import SkillInstructionBundle, SkillSelectionRequest
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolChoice,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolResult,
)


class AgentOrchestrator:
    """
    最小 Agent Loop 编排器。
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        provider = self._get_chat_provider(request.provider_id)
        request_messages = _build_initial_messages(request)
        history_messages = await self._load_session_history_messages(
            request.session_id
        )
        context_messages = [
            *history_messages,
            *request_messages,
        ]
        skill_bundle = self._build_skill_bundle(
            request=request,
            messages=context_messages,
        )
        tool_execution_policy = build_effective_tool_execution_policy(
            policy=request.tool_execution_policy,
            allowed_tool_names=request.allowed_tool_names,
            constrained_tool_names=_tool_constraint_names(
                skill_bundle=skill_bundle,
                request=request,
            ),
            additional_denied_tool_names=(
                request.tool_selection.denied_tool_names
                if request.tool_selection is not None
                else None
            ),
        )
        tools = self._list_tool_definitions(
            tool_execution_policy=tool_execution_policy
        )
        plan = _build_agent_plan(
            request=request,
            tools=tools,
        )
        context_result = await self._build_context(
            request=request,
            messages=context_messages,
        )
        memory_segment = await self._retrieve_memory_context(
            request=request,
            plan=plan,
            tool_execution_policy=tool_execution_policy,
        )
        context_window = _append_context_segments(
            context_result.window,
            [
                *([memory_segment] if memory_segment is not None else []),
                *request.additional_context_segments,
            ],
        )
        current_request = self._build_provider_request(
            request=request,
            messages=_build_provider_messages(
                context_window=context_window,
                skill_bundle=skill_bundle,
                plan=plan,
            ),
            tools=tools,
            skill_bundle=skill_bundle,
        )
        steps: list[AgentStep] = []
        response: ChatResponse | None = None

        for index in range(request.max_steps):
            response = await self._chat_provider(provider, current_request)
            tool_calls = list(response.tool_calls)
            tool_results = await self._execute_tool_calls(
                current_request,
                response,
                tool_execution_policy=tool_execution_policy,
            )
            steps.append(
                AgentStep(
                    index=index,
                    request=current_request,
                    response=response,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                )
            )

            if not tool_calls:
                context_snapshot = _build_context_snapshot(
                    request=request,
                    context_window=_append_agent_trace_segment(
                        context_window=context_window,
                        steps=steps,
                    ),
                )
                if self._runtime.context_manager is not None:
                    await self._runtime.context_manager.save(context_snapshot)
                return AgentRunResult(
                    response=response,
                    steps=steps,
                    plan=plan,
                    skill_bundle=skill_bundle,
                    context_snapshot=context_snapshot,
                    completed=True,
                    stop_reason=AgentStopReason.FINAL_RESPONSE,
                    metadata={
                        **request.metadata,
                        "session_id": request.session_id,
                        "dropped_context_items": [
                            item.item_id for item in context_result.dropped_items
                        ],
                    },
                )

            current_request = _append_tool_feedback_messages(
                request=current_request,
                response=response,
                tool_results=tool_results,
            )

        if response is None:
            raise StateError("Agent loop did not execute any step")

        if response.tool_calls:
            final_request = _build_max_steps_final_response_request(current_request)
            final_response = await self._chat_provider(provider, final_request)
            response = _ensure_max_steps_final_response(
                request=final_request,
                response=final_response,
            )
            steps.append(
                AgentStep(
                    index=len(steps),
                    request=final_request,
                    response=response,
                    tool_calls=[],
                    tool_results=[],
                )
            )

        context_snapshot = _build_context_snapshot(
            request=request,
            context_window=_append_agent_trace_segment(
                context_window=context_window,
                steps=steps,
            ),
        )
        if self._runtime.context_manager is not None:
            await self._runtime.context_manager.save(context_snapshot)
        return AgentRunResult(
            response=response,
            steps=steps,
            plan=plan,
            skill_bundle=skill_bundle,
            context_snapshot=context_snapshot,
            completed=False,
            stop_reason=AgentStopReason.MAX_STEPS,
            metadata={
                **request.metadata,
                "session_id": request.session_id,
                "dropped_context_items": [
                    item.item_id for item in context_result.dropped_items
                ],
            },
        )

    async def _build_context(
        self,
        *,
        request: AgentRunRequest,
        messages: list[Message],
    ) -> ContextBuildResult:
        return await self._runtime.context_builder.build(
            ContextBuildRequest(
                session_id=request.session_id,
                messages=messages,
                budget=request.context_budget,
                metadata={
                    **request.metadata,
                    "agent_loop": "minimal",
                },
            )
        )

    async def _load_session_history_messages(self, session_id: str) -> list[Message]:
        if self._runtime.context_manager is None:
            return []
        snapshots = await self._runtime.context_manager.list_by_session(session_id)
        if not snapshots:
            return []
        return _context_window_to_messages(snapshots[-1].window)

    def _build_skill_bundle(
        self,
        *,
        request: AgentRunRequest,
        messages: list[Message],
    ) -> SkillInstructionBundle | None:
        if self._runtime.skill_manager is None:
            return None
        return self._runtime.skill_manager.build_instruction_bundle(
            SkillSelectionRequest(
                text=_messages_to_text(messages),
                required_skill_names=request.required_skill_names,
                max_skills=request.max_skills,
                metadata=request.metadata.copy(),
            )
        )

    def _build_provider_request(
        self,
        *,
        request: AgentRunRequest,
        messages: list[Message],
        tools: list[ToolDefinition],
        skill_bundle: SkillInstructionBundle | None,
    ) -> ChatRequest:
        tool_choice = _filter_tool_choice(
            tool_choice=request.tool_choice,
            tools=tools,
        )
        return ChatRequest(
            provider_id=request.provider_id,
            model=request.model,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=request.stream,
            tools=tools or None,
            tool_choice=tool_choice,
            metadata={
                **request.metadata,
                "session_id": request.session_id,
                "agent_loop": "minimal",
                "agent_plan_enabled": plan_enabled(request.planning),
                "agent_plan_mode": (
                    "runtime_hint" if plan_enabled(request.planning) else None
                ),
                "skill_names": (
                    skill_bundle.metadata.get("skills", [])
                    if skill_bundle is not None
                    else []
                ),
            },
        )

    def _list_tool_definitions(
        self,
        *,
        tool_execution_policy: ToolExecutionPolicy,
    ) -> list[ToolDefinition]:
        if self._runtime.tool_registry is None:
            return []
        definitions = self._runtime.tool_registry.list_enabled_definitions()
        return filter_tool_definitions_for_policy(
            definitions=definitions,
            policy=tool_execution_policy,
            sandbox_available=self._runtime.tool_sandbox_runner is not None,
        )

    def _get_chat_provider(self, provider_id: str) -> ChatProviderProtocol:
        provider = self._runtime.provider_manager.get(provider_id)
        chat = getattr(provider, "chat", None)
        if chat is None:
            raise UnsupportedError(f"Provider {provider_id} does not support chat")
        return cast(ChatProviderProtocol, provider)

    async def _chat_provider(
        self,
        provider: ChatProviderProtocol,
        request: ChatRequest,
    ) -> ChatResponse:
        plugin_manager = self._runtime.plugin_manager
        if plugin_manager is None:
            return await provider.chat(request)
        return await plugin_manager.execute_llm_middlewares(
            request,
            provider.chat,
        )

    async def _execute_tool_calls(
        self,
        request: ChatRequest,
        response: ChatResponse,
        *,
        tool_execution_policy: ToolExecutionPolicy,
    ) -> list[ToolResult]:
        if not response.tool_calls:
            return []

        if self._runtime.tool_manager is None:
            raise StateError("Provider returned tool calls but no tool manager is set")

        results: list[ToolResult] = []
        for call in response.tool_calls:
            with use_tool_execution_context(
                session_id=_optional_string(request.metadata.get("session_id")),
                provider_id=request.provider_id,
                model=request.model,
                metadata=request.metadata,
            ):
                results.append(
                    await self._runtime.tool_manager.execute(
                        call,
                        policy=tool_execution_policy,
                    )
                )
        return results

    async def _retrieve_memory_context(
        self,
        *,
        request: AgentRunRequest,
        plan: AgentPlan | None,
        tool_execution_policy: ToolExecutionPolicy,
    ) -> ContextSegment | None:
        config = request.memory_retrieval
        if config is None or not config.enabled:
            return None
        if self._runtime.tool_manager is None:
            raise StateError("Agent memory retrieval requires a tool manager")
        if self._runtime.tool_registry is None or not self._runtime.tool_registry.exists(
            "search_memory"
        ):
            raise StateError("Agent memory retrieval requires search_memory tool")

        query = _memory_query(
            request=request,
            config=config,
        )
        if query is None:
            return None

        arguments: dict[str, object] = {
            "query": query,
            "top_k": config.top_k,
        }
        if config.namespace is not None:
            arguments["namespace"] = config.namespace
        if config.min_score is not None:
            arguments["min_score"] = config.min_score

        call = ToolCall(
            id=f"agent-memory:{uuid4()}",
            name="search_memory",
            arguments=json.dumps(arguments, ensure_ascii=False, sort_keys=True),
        )
        with use_tool_execution_context(
            session_id=request.session_id,
            provider_id=request.provider_id,
            model=request.model,
            metadata={
                **request.metadata,
                "agent_memory_retrieval": True,
            },
        ):
            result = await self._runtime.tool_manager.execute(
                call,
                policy=tool_execution_policy,
            )

        segment = _memory_result_to_context_segment(
            request=request,
            query=query,
            result=result,
        )
        if plan is not None:
            plan.metadata["memory_match_count"] = len(segment.items)
        return segment


def _build_initial_messages(request: AgentRunRequest) -> list[Message]:
    messages: list[Message] = []
    if request.goal:
        messages.append(
            Message(
                role=MessageRole.USER,
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text=request.goal,
                    )
                ],
            )
        )
    messages.extend(request.messages)
    return messages


def _build_agent_plan(
    *,
    request: AgentRunRequest,
    tools: list[ToolDefinition],
) -> AgentPlan | None:
    planning = request.planning
    if not plan_enabled(planning):
        return None

    goal = request.goal or _messages_to_text(request.messages)
    objectives = _build_plan_objectives(
        goal=goal,
        planning=planning,
    )
    memory_query = (
        _memory_query(
            request=request,
            config=request.memory_retrieval,
        )
        if request.memory_retrieval is not None
        and request.memory_retrieval.enabled
        else None
    )
    return AgentPlan(
        goal=goal or None,
        objectives=objectives,
        selected_tool_names=[tool.name for tool in tools],
        memory_query=memory_query,
        instructions=planning.instructions if planning is not None else None,
        metadata={
            "planning_enabled": True,
            "planning_mode": "runtime_hint",
            "selected_tool_count": len(tools),
        },
    )


def _build_plan_objectives(
    *,
    goal: str,
    planning: AgentPlanningConfig | None,
) -> list[str]:
    max_objectives = planning.max_objectives if planning is not None else 4
    objectives = [
        "Understand the goal and relevant constraints.",
        "Use only selected tools when they reduce uncertainty or perform required work.",
        "Incorporate retrieved memory before deciding on a final answer.",
        "Return a concise final response when the goal is satisfied.",
    ]
    if goal:
        objectives.insert(0, f"Complete the user goal: {goal}")
    return objectives[:max_objectives]


def _build_provider_messages(
    *,
    context_window: ContextWindow,
    skill_bundle: SkillInstructionBundle | None,
    plan: AgentPlan | None,
) -> list[Message]:
    messages: list[Message] = []
    skill_message = _build_skill_message(skill_bundle)
    if skill_message is not None:
        messages.append(skill_message)
    planning_message = _build_planning_message(plan)
    if planning_message is not None:
        messages.append(planning_message)
    messages.extend(_context_window_to_messages(context_window))
    return messages


def _build_skill_message(
    skill_bundle: SkillInstructionBundle | None,
) -> Message | None:
    if skill_bundle is None or not skill_bundle.instructions:
        return None

    content = "\n\n".join(
        f"[{instruction.name}]\n{instruction.content}"
        for instruction in skill_bundle.instructions
    )
    return Message(
        role=MessageRole.SYSTEM,
        name="skills",
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text=content,
            )
        ],
    )


def _build_planning_message(plan: AgentPlan | None) -> Message | None:
    if plan is None:
        return None

    lines = ["Agent runtime hints:"]
    if plan.goal:
        lines.append(f"Goal: {plan.goal}")
    if plan.instructions:
        lines.append(f"Instructions: {plan.instructions}")
    if plan.objectives:
        lines.append("Hints:")
        lines.extend(f"- {objective}" for objective in plan.objectives)
    if plan.selected_tool_names:
        lines.append("Selected tools: " + ", ".join(plan.selected_tool_names))
    if plan.memory_query:
        lines.append(f"Memory query: {plan.memory_query}")

    return Message(
        role=MessageRole.SYSTEM,
        name="agent_plan",
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text="\n".join(lines),
            )
        ],
    )


def plan_enabled(planning: AgentPlanningConfig | None) -> bool:
    return planning is not None and planning.enabled


def _tool_constraint_names(
    *,
    skill_bundle: SkillInstructionBundle | None,
    request: AgentRunRequest,
) -> list[str] | None:
    constraints: list[list[str] | None] = []
    if skill_bundle is not None:
        constraints.append(skill_bundle.allowed_tools)
    if request.tool_selection is not None:
        constraints.append(request.tool_selection.allowed_tool_names)

    constrained: set[str] | None = None
    for names in constraints:
        if names is None:
            continue
        name_set = set(names)
        constrained = name_set if constrained is None else constrained & name_set
    if constrained is None:
        return None
    return sorted(constrained)


def _build_context_snapshot(
    *,
    request: AgentRunRequest,
    context_window: ContextWindow,
) -> ContextSnapshot:
    return ContextSnapshot(
        snapshot_id=str(uuid4()),
        session_id=request.session_id,
        window=context_window,
        metadata={
            **request.metadata,
            "provider_id": request.provider_id,
            "model": request.model,
            "agent_loop": "minimal",
        },
    )


def _memory_query(
    *,
    request: AgentRunRequest,
    config: AgentMemoryRetrievalConfig | None,
) -> str | None:
    if config is not None and config.query is not None and config.query.strip():
        return config.query.strip()
    if request.goal is not None and request.goal.strip():
        return request.goal.strip()
    text = _messages_to_text(request.messages).strip()
    if text:
        return text
    return None


def _memory_result_to_context_segment(
    *,
    request: AgentRunRequest,
    query: str,
    result: ToolResult,
) -> ContextSegment:
    payload = _parse_memory_result_payload(result)
    raw_matches = payload.get("matches", [])
    if not isinstance(raw_matches, list):
        raise ToolExecutionError("search_memory result matches must be an array")
    matches = cast(list[Any], raw_matches)

    items: list[ContextItem] = []
    for index, value in enumerate(matches):
        if not isinstance(value, dict):
            continue
        match = cast(dict[str, Any], value)
        content = match.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        memory_id = match.get("memory_id")
        score = match.get("score")
        metadata = match.get("metadata")
        item_metadata: dict[str, Any] = {
            "agent_memory_query": query,
        }
        if isinstance(memory_id, str):
            item_metadata["memory_id"] = memory_id
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            item_metadata["score"] = float(score)
        if isinstance(metadata, dict):
            item_metadata["memory_metadata"] = cast(dict[str, Any], metadata)

        items.append(
            ContextItem(
                item_id=f"{request.session_id}:agent-memory:{index}",
                type=ContextItemType.MEMORY,
                source=ContextItemSource.MEMORY,
                content=content,
                priority=_memory_priority(score),
                metadata=item_metadata,
            )
        )

    return ContextSegment(
        segment_id=f"{request.session_id}:agent-memory",
        role=ContextSegmentRole.MEMORY,
        items=items,
        metadata={
            "agent_memory_query": query,
            "tool_call_id": result.call_id,
            "tool_name": result.name,
            "match_count": len(items),
        },
    )


def _parse_memory_result_payload(result: ToolResult) -> dict[str, Any]:
    if result.content is None:
        return {}
    try:
        payload = json.loads(result.content)
    except json.JSONDecodeError as exc:
        raise ToolExecutionError(
            "search_memory result must be valid JSON",
            cause=exc,
        ) from exc
    if not isinstance(payload, dict):
        raise ToolExecutionError("search_memory result must be a JSON object")
    return cast(dict[str, Any], payload)


def _memory_priority(score: object) -> int:
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return int(float(score) * 1000)
    return 0


def _messages_to_text(messages: list[Message]) -> str:
    chunks: list[str] = []
    for message in messages:
        for part in message.content or []:
            if part.text:
                chunks.append(part.text)
    return "\n".join(chunks)


def _append_context_segments(
    context_window: ContextWindow,
    additional_segments: list[ContextSegment],
) -> ContextWindow:
    if not additional_segments:
        return context_window
    return context_window.model_copy(
        update={
            "segments": [
                *context_window.segments,
                *additional_segments,
            ]
        }
    )


def _append_agent_trace_segment(
    *,
    context_window: ContextWindow,
    steps: list[AgentStep],
) -> ContextWindow:
    trace_messages: list[Message] = []
    for step in steps:
        assistant_message = _response_to_assistant_message(step.response)
        if assistant_message is not None:
            trace_messages.append(assistant_message)
        trace_messages.extend(
            _tool_result_to_message(result)
            for result in step.tool_results
        )

    if not trace_messages:
        return context_window

    segment = ContextSegment(
        segment_id=f"{context_window.window_id}:agent-trace",
        role=ContextSegmentRole.WORKING,
        items=[
            ContextItem(
                item_id=f"{context_window.window_id}:agent-trace:{index}",
                type=(
                    ContextItemType.TOOL_TRACE
                    if message.role == MessageRole.TOOL
                    else ContextItemType.MESSAGE
                ),
                source=_map_message_role_to_context_item_source(message.role),
                message=message,
                metadata={
                    "agent_trace_index": index,
                },
            )
            for index, message in enumerate(trace_messages)
        ],
    )
    return context_window.model_copy(
        update={
            "segments": [
                *context_window.segments,
                segment,
            ]
        }
    )


def _append_tool_feedback_messages(
    *,
    request: ChatRequest,
    response: ChatResponse,
    tool_results: list[ToolResult],
) -> ChatRequest:
    messages = list(request.messages)
    assistant_message = _response_to_assistant_message(response)
    if assistant_message is not None:
        messages.append(assistant_message)
    messages.extend(_tool_result_to_message(result) for result in tool_results)
    return request.model_copy(update={"messages": messages})


def _build_max_steps_final_response_request(request: ChatRequest) -> ChatRequest:
    messages = [
        *request.messages,
        Message(
            role=MessageRole.SYSTEM,
            name="agent_max_steps",
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=(
                        "The agent reached max_steps after executing the available "
                        "tool results. Produce a concise final response from the "
                        "information already available. Do not call tools."
                    ),
                )
            ],
        ),
    ]
    return request.model_copy(
        update={
            "messages": messages,
            "tools": None,
            "tool_choice": None,
            "metadata": {
                **request.metadata,
                "agent_max_steps_finalization": True,
            },
        }
    )


def _ensure_max_steps_final_response(
    *,
    request: ChatRequest,
    response: ChatResponse,
) -> ChatResponse:
    if _response_has_text(response):
        return response.model_copy(update={"tool_calls": []})
    return ChatResponse(
        provider_id=response.provider_id or request.provider_id,
        model=response.model or request.model,
        message=Message(
            role=MessageRole.ASSISTANT,
            content=[
                ContentPart(
                    type=ContentPartType.TEXT,
                    text=(
                        "Agent stopped after reaching max_steps before producing "
                        "a final response."
                    ),
                )
            ],
        ),
        finish_reason=ChatFinishReason.STOP,
        raw=response.raw,
    )


def _response_has_text(response: ChatResponse) -> bool:
    message = response.message
    if message is None or not message.content:
        return False
    return any(
        bool(part.text)
        for part in message.content
        if part.type == ContentPartType.TEXT
    )


def _context_window_to_messages(context_window: ContextWindow) -> list[Message]:
    messages: list[Message] = []
    for segment in context_window.segments:
        for item in segment.items:
            message = _context_item_to_message(item, segment.role)
            if message is not None:
                messages.append(message)
    return messages


def _context_item_to_message(
    item: ContextItem,
    role: ContextSegmentRole,
) -> Message | None:
    if item.message is not None:
        return item.message
    if item.content is None:
        return None

    return Message(
        role=(
            _map_context_item_source_to_message_role(item.source)
            or _map_context_role_to_message_role(role)
        ),
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text=item.content,
            )
        ],
    )


def _map_context_item_source_to_message_role(
    source: ContextItemSource,
) -> MessageRole | None:
    if source == ContextItemSource.USER:
        return MessageRole.USER
    if source == ContextItemSource.ASSISTANT:
        return MessageRole.ASSISTANT
    if source == ContextItemSource.SYSTEM:
        return MessageRole.SYSTEM
    if source == ContextItemSource.TOOL:
        return MessageRole.TOOL
    return None


def _map_context_role_to_message_role(role: ContextSegmentRole) -> MessageRole:
    if role == ContextSegmentRole.HISTORY:
        return MessageRole.USER
    if role == ContextSegmentRole.TOOL_TRACE:
        return MessageRole.TOOL
    return MessageRole.SYSTEM


def _map_message_role_to_context_item_source(role: MessageRole) -> ContextItemSource:
    if role == MessageRole.USER:
        return ContextItemSource.USER
    if role == MessageRole.ASSISTANT:
        return ContextItemSource.ASSISTANT
    if role == MessageRole.SYSTEM:
        return ContextItemSource.SYSTEM
    if role == MessageRole.TOOL:
        return ContextItemSource.TOOL
    return ContextItemSource.UNKNOWN


def _response_to_assistant_message(response: ChatResponse) -> Message | None:
    if response.message is not None:
        return response.message
    if not response.tool_calls:
        return None
    return Message(
        role=MessageRole.ASSISTANT,
        tool_calls=list(response.tool_calls),
    )


def _tool_result_to_message(result: ToolResult) -> Message:
    content_text = result.content
    if content_text is None and result.error is not None:
        content_text = result.error
    if content_text is None:
        content_text = ""

    return Message(
        role=MessageRole.TOOL,
        name=result.name,
        tool_call_id=result.call_id,
        content=[
            ContentPart(
                type=ContentPartType.TEXT,
                text=content_text,
            )
        ],
    )


def _filter_tool_choice(
    *,
    tool_choice: ToolChoice | None,
    tools: list[ToolDefinition],
) -> ToolChoice | None:
    if tool_choice is None:
        return None
    if not tools:
        return None
    if tool_choice.mode != "tool":
        return tool_choice

    tool_names = {tool.name for tool in tools}
    if tool_choice.name not in tool_names:
        return None
    return tool_choice


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
