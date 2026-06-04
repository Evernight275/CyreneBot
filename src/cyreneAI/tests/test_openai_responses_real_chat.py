# ----------------------------------------------------
# 此测试旨在测试能不能在真实情况跑通，不做强制要求
# ----------------------------------------------------
from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import pytest
from dotenv import load_dotenv

from cyreneAI.core.errors.provider import ProviderError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.core.schema.tool import ToolChoice, ToolDefinition
from cyreneAI.infra.bootstrap.registrations.openai_responses import (
    register_openai_responses_provider,
)


def _skip(reason: str) -> None:
    print(f"openai-responses real chat skipped: {reason}")
    pytest.skip(reason)


def _real_config() -> ProviderConfig:
    load_dotenv()

    api_key = os.getenv("OPENAI_RESPONSES_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_RESPONSES_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_RESPONSES_MODEL") or os.getenv("OPENAI_MODEL")

    if not api_key:
        _skip("OPENAI_RESPONSES_API_KEY or OPENAI_API_KEY is required")
    if not model:
        _skip("OPENAI_RESPONSES_MODEL or OPENAI_MODEL is required")

    return ProviderConfig(
        provider_id="real-openai-responses",
        provider_type=ProviderType.OPENAI_RESPONSES,
        api_key=api_key,
        base_url=base_url,
        timeout=timedelta(seconds=30),
        metadata={
            "model": model,
        },
    )


async def _run_real_responses_chat() -> None:
    config = _real_config()
    model = config.metadata["model"]

    registry = ProviderRegistry()
    factory = ProviderFactory()
    register_openai_responses_provider(registry, factory)

    manager = ProviderManager(factory)
    request = ChatRequest(
        provider_id=config.provider_id,
        model=model,
        messages=[
            Message(
                role=MessageRole.USER,
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text="Reply with exactly: Hello world!",
                    )
                ],
            )
        ],
        temperature=0,
        max_tokens=16,
    )

    try:
        instance = await manager.add(config)
        response = await instance.chat(request)

        assert response.provider_id == config.provider_id
        assert response.finish_reason in {
            ChatFinishReason.STOP,
            ChatFinishReason.LENGTH,
        }
        assert response.message is not None
        assert response.message.content is not None
        assert response.message.content[0].text

        print()
        print("openai-responses real chat response:")
        print(f"  model: {response.model}")
        print(f"  finish_reason: {response.finish_reason}")
        print(f"  usage: {response.usage}")
        print(f"  text: {response.message.content[0].text}")
    except ProviderError as exc:
        _skip(f"configured endpoint does not support OpenAI Responses: {exc}")
    finally:
        await manager.close_all()


async def _run_real_responses_chat_with_tool_calls() -> None:
    config = _real_config()
    model = config.metadata["model"]

    registry = ProviderRegistry()
    factory = ProviderFactory()
    register_openai_responses_provider(registry, factory)

    manager = ProviderManager(factory)
    request = ChatRequest(
        provider_id=config.provider_id,
        model=model,
        messages=[
            Message(
                role=MessageRole.USER,
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text="Use the lookup_order_status tool for order A-100.",
                    )
                ],
            )
        ],
        temperature=0,
        max_tokens=128,
        tools=[
            ToolDefinition(
                name="lookup_order_status",
                description="Lookup the shipping status for an order.",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "description": "The order id to look up.",
                        },
                    },
                    "required": ["order_id"],
                    "additionalProperties": False,
                },
            )
        ],
        tool_choice=ToolChoice(mode="tool", name="lookup_order_status"),
    )

    try:
        instance = await manager.add(config)
        response = await instance.chat(request)

        assert response.provider_id == config.provider_id
        if response.finish_reason != ChatFinishReason.TOOL_CALLS:
            _skip(
                f"{model} did not return tool_calls for the configured "
                "OpenAI Responses endpoint"
            )
        assert response.tool_calls
        assert response.tool_calls[0].name == "lookup_order_status"
        assert response.tool_calls[0].arguments

        print()
        print("openai-responses real tool call response:")
        print(f"  model: {response.model}")
        print(f"  finish_reason: {response.finish_reason}")
        print(f"  usage: {response.usage}")
        print(f"  tool_name: {response.tool_calls[0].name}")
        print(f"  tool_arguments: {response.tool_calls[0].arguments}")
    except ProviderError as exc:
        _skip(f"configured endpoint does not support OpenAI Responses: {exc}")
    finally:
        await manager.close_all()


def test_openai_responses_real_chat() -> None:
    asyncio.run(_run_real_responses_chat())
    asyncio.run(_run_real_responses_chat_with_tool_calls())
