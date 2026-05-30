from __future__ import annotations

from typing import cast
from uuid import uuid4

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.application.tools.execution_context import use_tool_execution_context
from cyreneAI.core.errors.base import StateError, UnsupportedError
from cyreneAI.core.provider.provider_protocol import ChatProviderProtocol
from cyreneAI.core.schema.agent import (
    AgentRunRequest,
    AgentRunResult,
    AgentStep,
    AgentStopReason,
)
from cyreneAI.core.schema.chat import ChatRequest, ChatResponse
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
from cyreneAI.core.schema.tool import (
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
        allowed_tool_names = (
            set(request.allowed_tool_names)
            if request.allowed_tool_names is not None
            else None
        )
        initial_messages = _build_initial_messages(request)
        context_result = await self._build_context(
            request=request,
            messages=initial_messages,
        )
        context_window = _append_context_segments(
            context_result.window,
            request.additional_context_segments,
        )
        current_request = self._build_provider_request(
            request=request,
            messages=_context_window_to_messages(context_window),
            allowed_tool_names=allowed_tool_names,
        )
        steps: list[AgentStep] = []
        response: ChatResponse | None = None

        for index in range(request.max_steps):
            response = await self._chat_provider(provider, current_request)
            tool_calls = list(response.tool_calls)
            tool_results = await self._execute_tool_calls(
                current_request,
                response,
                allowed_tool_names=allowed_tool_names,
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

    def _build_provider_request(
        self,
        *,
        request: AgentRunRequest,
        messages: list[Message],
        allowed_tool_names: set[str] | None,
    ) -> ChatRequest:
        tools = self._list_tool_definitions(allowed_tool_names=allowed_tool_names)
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
            },
        )

    def _list_tool_definitions(
        self,
        *,
        allowed_tool_names: set[str] | None,
    ) -> list[ToolDefinition]:
        if self._runtime.tool_registry is None:
            return []
        definitions = self._runtime.tool_registry.list_definitions()
        if allowed_tool_names is None:
            return definitions
        return [
            definition
            for definition in definitions
            if definition.name in allowed_tool_names
        ]

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
        allowed_tool_names: set[str] | None,
    ) -> list[ToolResult]:
        if not response.tool_calls:
            return []

        if self._runtime.tool_manager is None:
            raise StateError("Provider returned tool calls but no tool manager is set")

        results: list[ToolResult] = []
        policy = _build_tool_execution_policy(allowed_tool_names)
        for call in response.tool_calls:
            with use_tool_execution_context(
                session_id=_optional_string(request.metadata.get("session_id")),
                provider_id=request.provider_id,
                model=request.model,
                metadata=request.metadata,
            ):
                results.append(
                    await self._runtime.tool_manager.execute(call, policy=policy)
                )
        return results


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


def _build_tool_execution_policy(
    allowed_tool_names: set[str] | None,
) -> ToolExecutionPolicy:
    return ToolExecutionPolicy(
        allowed_tool_names=(
            sorted(allowed_tool_names)
            if allowed_tool_names is not None
            else None
        )
    )


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
