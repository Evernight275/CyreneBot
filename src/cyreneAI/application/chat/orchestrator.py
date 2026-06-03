from __future__ import annotations

import json
from typing import cast
from uuid import uuid4

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.application.tools.execution_policy import (
    build_effective_tool_execution_policy,
    filter_tool_definitions_for_policy,
)
from cyreneAI.application.tools.execution_context import use_tool_execution_context
from cyreneAI.core.context.context_protocol import ContextBuilderProtocol
from cyreneAI.core.errors.base import StateError, UnsupportedError
from cyreneAI.core.errors.tool import ToolExecutionError
from cyreneAI.core.provider.provider_protocol import ChatProviderProtocol
from cyreneAI.core.schema.application import ApplicationChatRequest, ApplicationChatResult
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
from cyreneAI.core.schema.skill import SkillInstructionBundle, SkillSelectionRequest
from cyreneAI.core.schema.tool import (
    ToolCall,
    ToolChoice,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolResult,
)


class ChatOrchestrator:
    """
    应用聊天编排器
    """

    def __init__(self, runtime: CyreneAIRuntime) -> None:
        self._runtime = runtime

    async def chat(self, request: ApplicationChatRequest) -> ApplicationChatResult:
        """
        编排一次聊天请求
        """
        history_messages = await self._load_session_history_messages(
            request.session_id
        )
        context_request = request.model_copy(
            update={
                "messages": [
                    *history_messages,
                    *request.messages,
                ]
            }
        )
        context_result = await self._build_context(context_request)
        context_window = _append_context_segments(
            context_result.window,
            request.additional_context_segments,
        )
        skill_bundle = self._build_skill_bundle(request)
        tool_execution_policy = build_effective_tool_execution_policy(
            policy=request.tool_execution_policy,
            allowed_tool_names=request.allowed_tool_names,
            constrained_tool_names=(
                skill_bundle.allowed_tools
                if skill_bundle is not None
                else None
            ),
        )
        provider_request = self._build_provider_request(
            request=request,
            context_window=context_window,
            skill_bundle=skill_bundle,
            tool_execution_policy=tool_execution_policy,
        )
        provider = self._get_chat_provider(request.provider_id)
        response = await self._chat_provider(provider, provider_request)
        response, tool_results = await self._run_tool_feedback_loop(
            request=request,
            provider=provider,
            provider_request=provider_request,
            response=response,
            tool_execution_policy=tool_execution_policy,
        )

        saved_context_window = _append_response_message(
            context_window,
            response.message,
        )
        context_snapshot = _build_context_snapshot(
            request=request,
            context_window=saved_context_window,
        )
        if self._runtime.context_manager is not None:
            await self._runtime.context_manager.save(context_snapshot)

        return ApplicationChatResult(
            response=response,
            context_snapshot=context_snapshot,
            skill_bundle=skill_bundle,
            tool_results=tool_results,
            metadata={
                "dropped_context_items": [
                    item.item_id for item in context_result.dropped_items
                ],
            },
        )

    async def _run_tool_feedback_loop(
        self,
        *,
        request: ApplicationChatRequest,
        provider: ChatProviderProtocol,
        provider_request: ChatRequest,
        response: ChatResponse,
        tool_execution_policy: ToolExecutionPolicy,
    ) -> tuple[ChatResponse, list[ToolResult]]:
        tool_results: list[ToolResult] = []
        current_request = provider_request
        current_response = response

        for _ in range(request.max_tool_rounds):
            if not current_response.tool_calls:
                break

            round_results = await self._execute_tool_calls(
                current_request,
                current_response,
                tool_execution_policy=tool_execution_policy,
            )
            tool_results.extend(round_results)
            current_request = _append_tool_feedback_messages(
                request=current_request,
                response=current_response,
                tool_results=round_results,
            )
            current_response = await self._chat_provider(provider, current_request)

        return current_response, tool_results

    async def _build_context(
        self,
        request: ApplicationChatRequest,
    ) -> ContextBuildResult:
        builder: ContextBuilderProtocol = self._runtime.context_builder
        return await builder.build(
            ContextBuildRequest(
                session_id=request.session_id,
                messages=request.messages,
                budget=request.context_budget,
                metadata=request.metadata.copy(),
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
        request: ApplicationChatRequest,
    ) -> SkillInstructionBundle | None:
        if self._runtime.skill_manager is None:
            return None

        return self._runtime.skill_manager.build_instruction_bundle(
            SkillSelectionRequest(
                text=_messages_to_text(request.messages),
                required_skill_names=request.required_skill_names,
                max_skills=request.max_skills,
                metadata=request.metadata.copy(),
            )
        )

    def _build_provider_request(
        self,
        *,
        request: ApplicationChatRequest,
        context_window: ContextWindow,
        skill_bundle: SkillInstructionBundle | None,
        tool_execution_policy: ToolExecutionPolicy,
    ) -> ChatRequest:
        tools = self._list_tool_definitions(tool_execution_policy=tool_execution_policy)
        tool_choice = _filter_tool_choice(
            tool_choice=request.tool_choice,
            tools=tools,
        )
        return ChatRequest(
            provider_id=request.provider_id,
            model=request.model,
            messages=_build_provider_messages(
                context_window=context_window,
                skill_bundle=skill_bundle,
            ),
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=request.stream,
            tools=tools or None,
            tool_choice=tool_choice,
            metadata={
                **request.metadata,
                "session_id": request.session_id,
                "context_window_id": context_window.window_id,
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
                try:
                    result = await self._runtime.tool_manager.execute(
                        call,
                        policy=tool_execution_policy,
                    )
                except ToolExecutionError as exc:
                    result = _tool_execution_error_result(call, exc)
                results.append(result)
        return results


def _build_context_snapshot(
    *,
    request: ApplicationChatRequest,
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


def _append_response_message(
    context_window: ContextWindow,
    message: Message | None,
) -> ContextWindow:
    if message is None:
        return context_window
    if message.tool_calls:
        return context_window

    segments = list(context_window.segments)
    history_index = next(
        (
            index
            for index, segment in enumerate(segments)
            if segment.role == ContextSegmentRole.HISTORY
        ),
        None,
    )
    message_index = len(_context_window_to_messages(context_window))
    response_item = ContextItem(
        item_id=f"{context_window.window_id}:assistant:{message_index}",
        type=ContextItemType.MESSAGE,
        source=ContextItemSource.ASSISTANT,
        message=message,
    )
    if history_index is None:
        segments.append(
            ContextSegment(
                segment_id=f"{context_window.window_id}:history",
                role=ContextSegmentRole.HISTORY,
                items=[response_item],
            )
        )
    else:
        history = segments[history_index]
        segments[history_index] = history.model_copy(
            update={
                "items": [
                    *history.items,
                    response_item,
                ],
                "token_count": None,
            }
        )
    return context_window.model_copy(update={"segments": segments})


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


def _build_provider_messages(
    *,
    context_window: ContextWindow,
    skill_bundle: SkillInstructionBundle | None,
) -> list[Message]:
    messages: list[Message] = []
    skill_message = _build_skill_message(skill_bundle)
    if skill_message is not None:
        messages.append(skill_message)
    messages.extend(_context_window_to_messages(context_window))
    return messages


def _append_tool_feedback_messages(
    *,
    request: ChatRequest,
    response: ChatResponse,
    tool_results: list[ToolResult],
) -> ChatRequest:
    messages = list(request.messages)
    if response.message is not None:
        messages.append(response.message)
    messages.extend(_tool_result_to_message(result) for result in tool_results)
    return request.model_copy(update={"messages": messages})


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


def _tool_execution_error_result(call: ToolCall, error: ToolExecutionError) -> ToolResult:
    error_type = error.__class__.__name__
    message = str(error)
    return ToolResult(
        call_id=call.id,
        name=call.name,
        content=json.dumps(
            {
                "success": False,
                "error": message,
                "error_type": error_type,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        success=False,
        error=message,
        metadata={
            "error_type": error_type,
        },
    )


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


def _messages_to_text(messages: list[Message]) -> str:
    chunks: list[str] = []
    for message in messages:
        for part in message.content or []:
            if part.text:
                chunks.append(part.text)
    return "\n".join(chunks)


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
