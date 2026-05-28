from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

from pydantic import Field

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.context.context_protocol import ContextBuilderProtocol
from cyreneAI.core.errors.base import StateError, UnsupportedError
from cyreneAI.core.errors.tool import ToolExecutionError
from cyreneAI.core.provider.provider_protocol import ChatProviderProtocol
from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.chat import ChatRequest, ChatResponse
from cyreneAI.core.schema.context import (
    ContextBudget,
    ContextBuildRequest,
    ContextBuildResult,
    ContextItem,
    ContextItemSource,
    ContextSegment,
    ContextSegmentRole,
    ContextSnapshot,
    ContextWindow,
)
from cyreneAI.core.schema.message import ContentPart, ContentPartType, Message, MessageRole
from cyreneAI.core.schema.skill import (
    SkillInstructionBundle,
    SkillSelectionRequest,
)
from cyreneAI.core.schema.tool import ToolChoice, ToolDefinition, ToolResult


class ApplicationChatRequest(CyreneAISchema):
    """
    应用聊天请求
    """

    session_id: str
    provider_id: str
    model: str
    messages: list[Message]

    context_budget: ContextBudget | None = None
    required_skill_names: list[str] = Field(default_factory=list)
    max_skills: int | None = None
    additional_context_segments: list[ContextSegment] = Field(default_factory=list)

    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    tool_choice: ToolChoice | None = None
    allowed_tool_names: list[str] | None = None
    max_tool_rounds: int = Field(default=1, ge=0)

    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationChatResult(CyreneAISchema):
    """
    应用聊天结果
    """

    response: ChatResponse
    context_snapshot: ContextSnapshot
    skill_bundle: SkillInstructionBundle | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


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
        context_result = await self._build_context(request)
        context_window = _append_context_segments(
            context_result.window,
            request.additional_context_segments,
        )
        context_snapshot = _build_context_snapshot(
            request=request,
            context_window=context_window,
        )
        if self._runtime.context_manager is not None:
            await self._runtime.context_manager.save(context_snapshot)

        skill_bundle = self._build_skill_bundle(request)
        allowed_tool_names = _resolve_allowed_tool_names(
            request_allowed_tool_names=request.allowed_tool_names,
            skill_bundle=skill_bundle,
        )
        provider_request = self._build_provider_request(
            request=request,
            context_window=context_window,
            skill_bundle=skill_bundle,
            allowed_tool_names=allowed_tool_names,
        )
        provider = self._get_chat_provider(request.provider_id)
        response = await provider.chat(provider_request)
        response, tool_results = await self._run_tool_feedback_loop(
            request=request,
            provider=provider,
            provider_request=provider_request,
            response=response,
            allowed_tool_names=allowed_tool_names,
        )

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
        allowed_tool_names: set[str] | None,
    ) -> tuple[ChatResponse, list[ToolResult]]:
        tool_results: list[ToolResult] = []
        current_request = provider_request
        current_response = response

        for _ in range(request.max_tool_rounds):
            if not current_response.tool_calls:
                break

            round_results = await self._execute_tool_calls(
                current_response,
                allowed_tool_names=allowed_tool_names,
            )
            tool_results.extend(round_results)
            current_request = _append_tool_feedback_messages(
                request=current_request,
                response=current_response,
                tool_results=round_results,
            )
            current_response = await provider.chat(current_request)

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

    async def _execute_tool_calls(
        self,
        response: ChatResponse,
        *,
        allowed_tool_names: set[str] | None,
    ) -> list[ToolResult]:
        if not response.tool_calls:
            return []

        if self._runtime.tool_manager is None:
            raise StateError("Provider returned tool calls but no tool manager is set")

        results: list[ToolResult] = []
        for call in response.tool_calls:
            if allowed_tool_names is not None and call.name not in allowed_tool_names:
                raise ToolExecutionError(
                    f"Tool {call.name} is not allowed for this chat request"
                )
            results.append(await self._runtime.tool_manager.execute(call))
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


def _resolve_allowed_tool_names(
    *,
    request_allowed_tool_names: list[str] | None,
    skill_bundle: SkillInstructionBundle | None,
) -> set[str] | None:
    allowed_tool_names = (
        set(request_allowed_tool_names)
        if request_allowed_tool_names is not None
        else None
    )
    if skill_bundle is None:
        return allowed_tool_names

    skill_allowed_tool_names = set(skill_bundle.allowed_tools)
    if allowed_tool_names is None:
        return skill_allowed_tool_names
    return allowed_tool_names & skill_allowed_tool_names


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
