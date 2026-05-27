from __future__ import annotations

from anthropic.types import Message as AnthropicMessage

from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.tool import ToolChoice, ToolDefinition
from cyreneAI.infra.adapters.providers.anthropic.mapper import (
    map_anthropic_request,
    map_anthropic_response,
)


def test_map_anthropic_request_builds_payload() -> None:
    request = ChatRequest(
        provider_id="provider-1",
        model="claude-test",
        messages=[
            Message(
                role=MessageRole.SYSTEM,
                content=[ContentPart(type=ContentPartType.TEXT, text="be brief")],
            ),
            Message(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text="hello")],
            ),
        ],
        temperature=0,
        max_tokens=16,
        tools=[
            ToolDefinition(
                name="lookup",
                description="Lookup a value.",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                    },
                },
            )
        ],
        tool_choice=ToolChoice(mode="tool", name="lookup"),
    )

    payload = map_anthropic_request(request)

    assert payload["model"] == "claude-test"
    assert payload["system"] == "be brief"
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert payload["temperature"] == 0
    assert payload["max_tokens"] == 16
    assert payload["tools"] == [
        {
            "name": "lookup",
            "description": "Lookup a value.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                },
            },
        }
    ]
    assert payload["tool_choice"] == {"type": "tool", "name": "lookup"}


def test_map_anthropic_response_builds_core_response() -> None:
    anthropic_response = AnthropicMessage.model_validate(
        {
            "id": "msg-1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [
                {
                    "type": "text",
                    "text": "pong",
                },
                {
                    "type": "tool_use",
                    "id": "toolu-1",
                    "name": "lookup",
                    "input": {"key": "value"},
                },
            ],
            "stop_reason": "tool_use",
            "usage": {
                "input_tokens": 3,
                "output_tokens": 4,
            },
        }
    )

    response = map_anthropic_response("provider-1", anthropic_response)

    assert response.provider_id == "provider-1"
    assert response.model == "claude-test"
    assert response.finish_reason == ChatFinishReason.TOOL_CALLS
    assert response.usage is not None
    assert response.usage.prompt_tokens == 3
    assert response.usage.completion_tokens == 4
    assert response.usage.total_tokens == 7
    assert response.message is not None
    assert response.message.content is not None
    assert response.message.content[0].text == "pong"
    assert response.tool_calls[0].id == "toolu-1"
    assert response.tool_calls[0].name == "lookup"
    assert response.tool_calls[0].arguments == "{\"key\": \"value\"}"
