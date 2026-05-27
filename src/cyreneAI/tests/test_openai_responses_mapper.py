from __future__ import annotations

from openai.types.responses import Response

from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.tool import ToolChoice, ToolDefinition
from cyreneAI.infra.adapters.providers.openai_responses.mapper import (
    map_responses_request,
    map_responses_response,
)


def test_map_responses_request_builds_payload() -> None:
    request = ChatRequest(
        provider_id="provider-1",
        model="test-model",
        messages=[
            Message(
                role=MessageRole.USER,
                content=[
                    ContentPart(type=ContentPartType.TEXT, text="hello"),
                    ContentPart(type=ContentPartType.IMAGE, text="ignored"),
                ],
            )
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

    payload = map_responses_request(request)

    assert payload["model"] == "test-model"
    assert payload["input"] == [
        {
            "role": "user",
            "content": "hello",
        }
    ]
    assert payload["temperature"] == 0
    assert payload["max_output_tokens"] == 16
    assert payload["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "Lookup a value.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                },
            },
            "strict": None,
        }
    ]
    assert payload["tool_choice"] == {
        "type": "function",
        "name": "lookup",
    }


def test_map_responses_response_builds_core_response() -> None:
    response = Response(
        id="resp-test",
        created_at=1,
        model="test-model",
        object="response",
        output=[
            {
                "id": "msg-1",
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "pong",
                        "annotations": [],
                    }
                ],
                "status": "completed",
            },
            {
                "type": "function_call",
                "call_id": "call-1",
                "name": "lookup",
                "arguments": "{\"key\":\"value\"}",
            },
        ],
        parallel_tool_calls=True,
        tool_choice="auto",
        tools=[],
        status="completed",
        usage={
            "input_tokens": 3,
            "input_tokens_details": {
                "cached_tokens": 0,
            },
            "output_tokens": 4,
            "output_tokens_details": {
                "reasoning_tokens": 0,
            },
            "total_tokens": 7,
        },
    )

    mapped = map_responses_response("provider-1", response)

    assert mapped.provider_id == "provider-1"
    assert mapped.model == "test-model"
    assert mapped.finish_reason == ChatFinishReason.TOOL_CALLS
    assert mapped.usage is not None
    assert mapped.usage.prompt_tokens == 3
    assert mapped.usage.completion_tokens == 4
    assert mapped.usage.total_tokens == 7
    assert mapped.message is not None
    assert mapped.message.content is not None
    assert mapped.message.content[0].text == "pong"
    assert mapped.tool_calls[0].id == "call-1"
    assert mapped.tool_calls[0].name == "lookup"
    assert mapped.tool_calls[0].arguments == "{\"key\":\"value\"}"
