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
from cyreneAI.infra.bootstrap.registrations.google_genai import (
    register_google_genai_provider,
)


def _skip(reason: str) -> None:
    print(f"google-genai real chat skipped: {reason}")
    pytest.skip(reason)


def _real_config() -> ProviderConfig:
    load_dotenv()

    api_key = os.getenv("GOOGLE_GENAI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    base_url = os.getenv("GOOGLE_GENAI_BASE_URL") or os.getenv("GOOGLE_BASE_URL")
    model = os.getenv("GOOGLE_GENAI_MODEL") or os.getenv("GOOGLE_MODEL")

    if not api_key:
        _skip("GOOGLE_GENAI_API_KEY or GOOGLE_API_KEY is required")
    if not model:
        _skip("GOOGLE_GENAI_MODEL or GOOGLE_MODEL is required")

    return ProviderConfig(
        provider_id="real-google-genai",
        provider_type=ProviderType.GOOGLE,
        api_key=api_key,
        base_url=base_url,
        timeout=timedelta(seconds=30),
        metadata={
            "model": model,
        },
    )


async def _run_real_chat() -> None:
    config = _real_config()
    model = config.metadata["model"]

    registry = ProviderRegistry()
    factory = ProviderFactory()
    register_google_genai_provider(registry, factory)

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
        print("google-genai real chat response:")
        print(f"  model: {response.model}")
        print(f"  finish_reason: {response.finish_reason}")
        print(f"  usage: {response.usage}")
        print(f"  text: {response.message.content[0].text}")
    except ProviderError as exc:
        _skip(f"configured endpoint rejected the Google GenAI request: {exc}")
    finally:
        await manager.close_all()


def test_google_genai_real_chat() -> None:
    asyncio.run(_run_real_chat())
