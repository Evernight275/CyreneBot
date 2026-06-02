from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from cyreneAI.core.schema.base import CyreneAISchema
from cyreneAI.core.schema.agent import (
    AgentMemoryRetrievalConfig,
    AgentPlanningConfig,
    AgentRunResult,
    AgentToolSelectionConfig,
)
from cyreneAI.core.schema.bot import (
    BotAction,
    BotConversationState,
    BotEvent,
)
from cyreneAI.core.schema.chat import ChatResponse
from cyreneAI.core.schema.context import (
    ContextBudget,
    ContextSegment,
    ContextSnapshot,
)
from cyreneAI.core.schema.document import Document, DocumentChunk
from cyreneAI.core.schema.embedding import EmbeddingResponse
from cyreneAI.core.schema.image import ImageGenerationResponse
from cyreneAI.core.schema.message import Message
from cyreneAI.core.schema.skill import SkillInstructionBundle
from cyreneAI.core.schema.tool import ToolChoice, ToolExecutionPolicy, ToolResult
from cyreneAI.core.schema.vector import VectorRecord, VectorSearchResult


def _empty_context_segments() -> list[ContextSegment]:
    return []


def _empty_tool_results() -> list[ToolResult]:
    return []


def _empty_document_chunks() -> list[DocumentChunk]:
    return []


def _empty_vector_records() -> list[VectorRecord]:
    return []


def _empty_bot_actions() -> list[BotAction]:
    return []


def _empty_bot_dispatch_results() -> list["ApplicationBotDispatchResult"]:
    return []


def _empty_bot_events() -> list[BotEvent]:
    return []


def _empty_strings() -> list[str]:
    return []


class ChunkStrategy(StrEnum):
    """
    文档切块策略
    """

    CHARACTER = "character"
    PARAGRAPH = "paragraph"


class RAGContextFormat(StrEnum):
    """
    RAG 检索上下文格式
    """

    PLAIN = "plain"
    NUMBERED = "numbered"
    SOURCE_TAGGED = "source_tagged"
    COMPACT = "compact"


class BotMessageResponseMode(StrEnum):
    """
    普通 bot 消息触发后的响应模式。
    """

    CHAT = "chat"
    AGENT = "agent"


class BotMessageTriggerMode(StrEnum):
    """
    普通 bot 消息触发策略。
    """

    ALWAYS = "always"
    DIRECT = "direct"
    MENTION = "mention"
    KEYWORD = "keyword"
    DIRECT_OR_MENTION = "direct_or_mention"
    NEVER = "never"


class BotAdminConfig(CyreneAISchema):
    """
    Bot 管理员配置。
    """

    user_ids: list[str] = Field(default_factory=_empty_strings)


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
    additional_context_segments: list[ContextSegment] = Field(
        default_factory=_empty_context_segments
    )

    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    tool_choice: ToolChoice | None = None
    allowed_tool_names: list[str] | None = None
    tool_execution_policy: ToolExecutionPolicy | None = None
    max_tool_rounds: int = Field(default=1, ge=0)

    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationChatResult(CyreneAISchema):
    """
    应用聊天结果
    """

    response: ChatResponse
    context_snapshot: ContextSnapshot
    skill_bundle: SkillInstructionBundle | None = None
    tool_results: list[ToolResult] = Field(default_factory=_empty_tool_results)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationEmbeddingRequest(CyreneAISchema):
    """
    应用嵌入请求
    """

    provider_id: str
    model: str
    input: str | list[str]
    dimensions: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationEmbeddingResult(CyreneAISchema):
    """
    应用嵌入结果
    """

    response: EmbeddingResponse
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationImageGenerationRequest(CyreneAISchema):
    """
    应用图片生成请求
    """

    provider_id: str
    model: str
    prompt: str
    count: int = Field(default=1, ge=1)
    size: str | None = None
    quality: str | None = None
    response_format: Literal["url", "b64_json"] = "b64_json"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationImageGenerationResult(CyreneAISchema):
    """
    应用图片生成结果
    """

    response: ImageGenerationResponse
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationIndexingRequest(CyreneAISchema):
    """
    应用索引请求
    """

    provider_id: str
    model: str
    documents: list[Document] = Field(min_length=1)
    chunk_size: int = Field(default=1000, ge=1)
    chunk_overlap: int = Field(default=0, ge=0)
    chunk_strategy: ChunkStrategy = ChunkStrategy.CHARACTER
    dimensions: int | None = Field(default=None, ge=1)
    collection_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "ApplicationIndexingRequest":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class ApplicationIndexingResult(CyreneAISchema):
    """
    应用索引结果
    """

    chunks: list[DocumentChunk] = Field(default_factory=_empty_document_chunks)
    records: list[VectorRecord] = Field(default_factory=_empty_vector_records)
    embedding_response: EmbeddingResponse
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationRetrievalRequest(CyreneAISchema):
    """
    应用检索请求
    """

    provider_id: str
    model: str
    query: str
    dimensions: int | None = Field(default=None, ge=1)
    top_k: int = Field(default=5, ge=1)
    filters: dict[str, Any] = Field(default_factory=dict)
    min_score: float | None = None
    collection_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationRetrievalResult(CyreneAISchema):
    """
    应用检索结果
    """

    embedding_response: EmbeddingResponse
    search_result: VectorSearchResult
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationVectorUpsertRequest(CyreneAISchema):
    """
    应用向量写入请求
    """

    records: list[VectorRecord] = Field(default_factory=_empty_vector_records)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationVectorSearchRequest(CyreneAISchema):
    """
    应用向量检索请求
    """

    vector: list[float] = Field(min_length=1)
    top_k: int = Field(default=5, ge=1)
    filters: dict[str, Any] = Field(default_factory=dict)
    min_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationVectorSearchResult(CyreneAISchema):
    """
    应用向量检索结果
    """

    result: VectorSearchResult
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationVectorRecordResult(CyreneAISchema):
    """
    应用向量记录结果
    """

    record: VectorRecord
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationVectorWriteResult(CyreneAISchema):
    """
    应用向量写入结果
    """

    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationBotRequest(CyreneAISchema):
    """
    应用 bot 请求。
    """

    event: BotEvent
    provider_id: str
    model: str

    context_budget: ContextBudget | None = None
    required_skill_names: list[str] = Field(default_factory=list)
    max_skills: int | None = None

    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    tool_choice: ToolChoice | None = None
    allowed_tool_names: list[str] | None = None
    tool_execution_policy: ToolExecutionPolicy | None = None
    max_tool_rounds: int = Field(default=1, ge=0)
    max_agent_steps: int = Field(default=4, ge=1)
    agent_planning: AgentPlanningConfig | None = None
    agent_tool_selection: AgentToolSelectionConfig | None = None
    agent_memory_retrieval: AgentMemoryRetrievalConfig | None = None
    message_response_mode: BotMessageResponseMode = BotMessageResponseMode.CHAT
    message_trigger_mode: BotMessageTriggerMode = BotMessageTriggerMode.ALWAYS
    message_trigger_keywords: list[str] = Field(default_factory=_empty_strings)
    message_trigger_mentions: list[str] = Field(default_factory=_empty_strings)

    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationBotResult(CyreneAISchema):
    """
    应用 bot 结果。
    """

    actions: list[BotAction] = Field(default_factory=_empty_bot_actions)
    chat_result: ApplicationChatResult | None = None
    agent_result: AgentRunResult | None = None
    tool_results: list[ToolResult] = Field(default_factory=_empty_tool_results)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationBotDispatchResult(CyreneAISchema):
    """
    应用 bot 派发结果。
    """

    bot_result: ApplicationBotResult
    sent_actions: list[BotAction] = Field(default_factory=_empty_bot_actions)
    session_state: BotConversationState | None = None


class ApplicationChannelEventsRequest(CyreneAISchema):
    """
    应用 channel 事件批处理请求。
    """

    events: list[BotEvent] = Field(default_factory=_empty_bot_events)
    provider_id: str
    model: str

    context_budget: ContextBudget | None = None
    required_skill_names: list[str] = Field(default_factory=list)
    max_skills: int | None = None

    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    tool_choice: ToolChoice | None = None
    allowed_tool_names: list[str] | None = None
    tool_execution_policy: ToolExecutionPolicy | None = None
    max_tool_rounds: int = Field(default=1, ge=0)
    max_agent_steps: int = Field(default=4, ge=1)
    agent_planning: AgentPlanningConfig | None = None
    agent_tool_selection: AgentToolSelectionConfig | None = None
    agent_memory_retrieval: AgentMemoryRetrievalConfig | None = None
    message_response_mode: BotMessageResponseMode = BotMessageResponseMode.CHAT
    message_trigger_mode: BotMessageTriggerMode = BotMessageTriggerMode.ALWAYS
    message_trigger_keywords: list[str] = Field(default_factory=_empty_strings)
    message_trigger_mentions: list[str] = Field(default_factory=_empty_strings)

    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationChannelEventsResult(CyreneAISchema):
    """
    应用 channel 事件批处理结果。
    """

    dispatch_results: list[ApplicationBotDispatchResult] = Field(
        default_factory=_empty_bot_dispatch_results
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationChannelWebhookRequest(CyreneAISchema):
    """
    应用 channel webhook 请求。
    """

    channel_id: str
    payload: dict[str, Any]
    provider_id: str
    model: str

    context_budget: ContextBudget | None = None
    required_skill_names: list[str] = Field(default_factory=list)
    max_skills: int | None = None

    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    tool_choice: ToolChoice | None = None
    allowed_tool_names: list[str] | None = None
    tool_execution_policy: ToolExecutionPolicy | None = None
    max_tool_rounds: int = Field(default=1, ge=0)
    max_agent_steps: int = Field(default=4, ge=1)
    agent_planning: AgentPlanningConfig | None = None
    agent_tool_selection: AgentToolSelectionConfig | None = None
    agent_memory_retrieval: AgentMemoryRetrievalConfig | None = None
    message_response_mode: BotMessageResponseMode = BotMessageResponseMode.CHAT
    message_trigger_mode: BotMessageTriggerMode = BotMessageTriggerMode.ALWAYS
    message_trigger_keywords: list[str] = Field(default_factory=_empty_strings)
    message_trigger_mentions: list[str] = Field(default_factory=_empty_strings)

    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationRAGChatRequest(CyreneAISchema):
    """
    应用 RAG 聊天请求
    """

    session_id: str
    provider_id: str
    model: str
    messages: list[Message]

    retrieval_provider_id: str
    retrieval_model: str
    retrieval_query: str | None = None
    retrieval_dimensions: int | None = Field(default=None, ge=1)
    retrieval_top_k: int = Field(default=5, ge=1)
    retrieval_filters: dict[str, Any] = Field(default_factory=dict)
    retrieval_min_score: float | None = None
    collection_id: str | None = None
    retrieval_context_format: RAGContextFormat = RAGContextFormat.PLAIN
    max_retrieved_content_chars: int | None = Field(default=None, ge=1)
    include_retrieval_metadata: bool = False

    context_budget: ContextBudget | None = None
    required_skill_names: list[str] = Field(default_factory=list)
    max_skills: int | None = None

    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    tool_choice: ToolChoice | None = None
    allowed_tool_names: list[str] | None = None
    tool_execution_policy: ToolExecutionPolicy | None = None
    max_tool_rounds: int = Field(default=1, ge=0)

    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationRAGChatResult(CyreneAISchema):
    """
    应用 RAG 聊天结果
    """

    chat_result: ApplicationChatResult
    retrieval_result: ApplicationRetrievalResult
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ApplicationBotDispatchResult",
    "ApplicationBotRequest",
    "ApplicationBotResult",
    "ApplicationChannelEventsRequest",
    "ApplicationChannelEventsResult",
    "ApplicationChannelWebhookRequest",
    "ApplicationChatRequest",
    "ApplicationChatResult",
    "ApplicationEmbeddingRequest",
    "ApplicationEmbeddingResult",
    "ApplicationImageGenerationRequest",
    "ApplicationImageGenerationResult",
    "ApplicationIndexingRequest",
    "ApplicationIndexingResult",
    "ApplicationRAGChatRequest",
    "ApplicationRAGChatResult",
    "ApplicationRetrievalRequest",
    "ApplicationRetrievalResult",
    "ApplicationVectorRecordResult",
    "ApplicationVectorSearchRequest",
    "ApplicationVectorSearchResult",
    "ApplicationVectorUpsertRequest",
    "ApplicationVectorWriteResult",
    "BotAdminConfig",
    "BotMessageResponseMode",
    "BotMessageTriggerMode",
    "ChunkStrategy",
    "RAGContextFormat",
]
