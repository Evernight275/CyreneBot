from __future__ import annotations

from google.genai.types import GenerateContentResponse

from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.tool import ToolChoice, ToolDefinition
from cyreneAI.infra.adapters.providers.google_genai.mapper import (
    map_google_genai_request,
    map_google_genai_response,
)


def test_map_google_genai_request_builds_payload() -> None:
    request = ChatRequest(
        provider_id="provider-1",
        model="gemini-test",
        messages=[
            Message(
                role=MessageRole.USER,
                content=[ContentPart(type=ContentPartType.TEXT, text="hello")],
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

    payload = map_google_genai_request(request)

    assert payload["model"] == "gemini-test"
    assert payload["contents"] == [
        {
            "role": "user",
            "parts": [{"text": "hello"}],
        }
    ]
    assert payload["config"]["temperature"] == 0
    assert payload["config"]["max_output_tokens"] == 16
    assert payload["config"]["tools"] == [
        {
            "function_declarations": [
                {
                    "name": "lookup",
                    "description": "Lookup a value.",
                    "parameters_json_schema": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                        },
                    },
                }
            ]
        }
    ]
    assert payload["config"]["tool_config"] == {
        "function_calling_config": {
            "mode": "ANY",
            "allowed_function_names": ["lookup"],
        }
    }


def test_map_google_genai_response_builds_core_response() -> None:
    google_response = GenerateContentResponse.model_validate(
        {
            "model_version": "gemini-test",
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {"text": "pong"},
                            {
                                "function_call": {
                                    "name": "lookup",
                                    "args": {"key": "value"},
                                }
                            },
                        ],
                    },
                    "finish_reason": "STOP",
                }
            ],
            "usage_metadata": {
                "prompt_token_count": 3,
                "candidates_token_count": 4,
                "total_token_count": 7,
            },
        }
    )

    response = map_google_genai_response("provider-1", google_response)

    assert response.provider_id == "provider-1"
    assert response.model == "gemini-test"
    assert response.finish_reason == ChatFinishReason.TOOL_CALLS
    assert response.usage is not None
    assert response.usage.prompt_tokens == 3
    assert response.usage.completion_tokens == 4
    assert response.usage.total_tokens == 7
    assert response.message is not None
    assert response.message.content is not None
    assert response.message.content[0].text == "pong"
    assert response.tool_calls[0].id == "lookup"
    assert response.tool_calls[0].name == "lookup"
    assert response.tool_calls[0].arguments == "{\"key\": \"value\"}"
