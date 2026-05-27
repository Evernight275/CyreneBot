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
from cyreneAI.core.schema.tool import ToolDefinition
from cyreneAI.infra.bootstrap.registrations.openai_compatible import (
    register_openai_compatible_provider,
)


def _skip(reason: str) -> None:
    print(f"openai-compatible real chat skipped: {reason}")
    pytest.skip(reason)


async def _run_real_chat() -> None:
    load_dotenv()

    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_COMPATIBLE_MODEL") or os.getenv("OPENAI_MODEL")

    if not api_key:
        pytest.skip("OPENAI_COMPATIBLE_API_KEY or OPENAI_API_KEY is required")
    if not model:
        pytest.skip("OPENAI_COMPATIBLE_MODEL or OPENAI_MODEL is required")

    registry = ProviderRegistry()
    factory = ProviderFactory()
    register_openai_compatible_provider(registry, factory)

    manager = ProviderManager(factory)
    config = ProviderConfig(
        provider_id="real-openai-compatible",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key=api_key,
        base_url=base_url,
        timeout=timedelta(seconds=30),
    )

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
        max_tokens=64,
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
        print("openai-compatible real chat response:")
        print(f"  model: {response.model}")
        print(f"  finish_reason: {response.finish_reason}")
        print(f"  usage: {response.usage}")
        print(f"  text: {response.message.content[0].text}")
    except ProviderError as exc:
        _skip(f"configured endpoint rejected the OpenAI-compatible request: {exc}")
    finally:
        await manager.close_all()


async def _run_real_chat_with_tool_calls() -> None:
    load_dotenv()

    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_COMPATIBLE_MODEL") or os.getenv("OPENAI_MODEL")

    if not api_key:
        pytest.skip("OPENAI_COMPATIBLE_API_KEY or OPENAI_API_KEY is required")
    if not model:
        pytest.skip("OPENAI_COMPATIBLE_MODEL or OPENAI_MODEL is required")

    registry = ProviderRegistry()
    factory = ProviderFactory()
    register_openai_compatible_provider(registry, factory)

    manager = ProviderManager(factory)
    config = ProviderConfig(
        provider_id="real-openai-compatible-tool-calls",
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        api_key=api_key,
        base_url=base_url,
        timeout=timedelta(seconds=30),
    )

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
    )

    try:
        instance = await manager.add(config)
        response = await instance.chat(request)

        assert response.provider_id == config.provider_id
        if response.finish_reason != ChatFinishReason.TOOL_CALLS:
            pytest.skip(
                f"{model} did not return tool_calls for the configured "
                "OpenAI-compatible endpoint"
            )
        assert response.tool_calls
        assert response.tool_calls[0].name == "lookup_order_status"
        assert response.tool_calls[0].arguments

        print()
        print("openai-compatible real tool call response:")
        print(f"  model: {response.model}")
        print(f"  finish_reason: {response.finish_reason}")
        print(f"  usage: {response.usage}")
        print(f"  tool_name: {response.tool_calls[0].name}")
        print(f"  tool_arguments: {response.tool_calls[0].arguments}")
    except ProviderError as exc:
        _skip(f"configured endpoint rejected OpenAI-compatible tool calls: {exc}")
    finally:
        await manager.close_all()


def test_openai_compatible_real_chat() -> None:
    asyncio.run(_run_real_chat())
    asyncio.run(_run_real_chat_with_tool_calls())
