from __future__ import annotations

import asyncio
from datetime import timedelta

from fastapi.testclient import TestClient

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.schema.bot import (
    BotAction,
    BotChannelDefinition,
    BotEvent,
    BotEventType,
    BotMessage,
)
from cyreneAI.core.schema.chat import ChatFinishReason, ChatRequest, ChatResponse
from cyreneAI.core.schema.image import (
    GeneratedImage,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import (
    ProviderConfig,
    ProviderInfo,
    ProviderModel,
    ProviderType,
)
from cyreneAI.server import create_app
from cyreneAI.server.config import ServerSettings, build_provider_configs_from_env


class FakeServerProvider:
    info = ProviderInfo(
        provider_type=ProviderType.OPENAI_RESPONSES,
        name="fake",
        description="Fake provider.",
        models=["catalog-model"],
    )
    config = ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_RESPONSES,
        timeout=timedelta(seconds=1),
    )

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            provider_id=request.provider_id,
            model=request.model,
            message=Message(
                role=MessageRole.ASSISTANT,
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text="pong",
                    )
                ],
            ),
            finish_reason=ChatFinishReason.STOP,
        )

    async def generate_image(
        self,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResponse:
        return ImageGenerationResponse(
            provider_id=request.provider_id,
            model=request.model,
            images=[
                GeneratedImage(
                    index=0,
                    b64_json="aW1hZ2U=",
                    mime_type="image/png",
                )
            ],
        )

    async def list_models(self) -> list[ProviderModel]:
        return [ProviderModel(model_id="runtime-model")]

    async def close(self) -> None:
        pass


class FakeServerChannel:
    def __init__(self) -> None:
        self.actions: list[BotAction] = []

    def map_update(self, update: dict) -> BotEvent:
        return BotEvent(
            event_id=str(update["event_id"]),
            event_type=BotEventType.MESSAGE,
            channel_id="fake",
            session_id="fake:user-1",
            user_id="user-1",
            message=BotMessage(
                sender_id="user-1",
                content=[
                    ContentPart(
                        type=ContentPartType.TEXT,
                        text=str(update["text"]),
                    )
                ],
            ),
        )

    async def send(self, action: BotAction) -> None:
        self.actions.append(action)


def _client() -> TestClient:
    async def build_runtime() -> CyreneAIRuntime:
        provider = FakeServerProvider()
        channel = FakeServerChannel()
        bot_channel_registry = BotChannelRegistry()
        bot_channel_registry.register(
            BotChannelDefinition(
                channel_id="fake",
                name="Fake",
            ),
            channel,
        )
        factory = ProviderFactory()

        async def build_provider(config: ProviderConfig) -> FakeServerProvider:
            return provider

        factory.register(ProviderType.OPENAI_RESPONSES, build_provider)
        manager = ProviderManager(factory)
        await manager.add(provider.config)
        return CyreneAIRuntime(
            provider_manager=manager,
            context_builder=ContextWindowBuilder(),
            bot_channel_registry=bot_channel_registry,
        )

    return TestClient(
        create_app(
            asyncio.run(build_runtime()),
            settings=ServerSettings(auth_enabled=False),
        )
    )


def test_server_health() -> None:
    response = _client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_server_lists_providers_and_models() -> None:
    client = _client()

    providers = client.get("/providers")
    models = client.get("/providers/provider-1/models")

    assert providers.status_code == 200
    assert providers.json()["providers"][0]["name"] == "fake"
    assert models.status_code == 200
    assert models.json()["models"][0]["model_id"] == "runtime-model"


def test_server_chat() -> None:
    response = _client().post(
        "/chat",
        json={
            "provider_id": "provider-1",
            "model": "chat-model",
            "messages": [
                {
                    "role": "user",
                    "content": "ping",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["response"]["message"]["content"][0]["text"] == "pong"


def test_server_generates_images() -> None:
    response = _client().post(
        "/images/generate",
        json={
            "provider_id": "provider-1",
            "model": "image-model",
            "prompt": "A small robot.",
        },
    )

    assert response.status_code == 200
    assert response.json()["response"]["images"][0]["b64_json"] == "aW1hZ2U="


def test_server_channel_webhook_sends_bot_reply() -> None:
    response = _client().post(
        "/channels/fake/webhook",
        json={
            "provider_id": "provider-1",
            "model": "chat-model",
            "payload": {
                "event_id": "event-1",
                "text": "ping",
            },
        },
    )

    assert response.status_code == 200
    sent_actions = response.json()["sent_actions"]
    assert len(sent_actions) == 1
    assert sent_actions[0]["message"]["content"][0]["text"] == "pong"


def test_server_builds_provider_configs_from_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "compatible-key")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://compatible.example/v1")
    monkeypatch.setenv("OPENAI_RESPONSES_API_KEY", "openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("GOOGLE_GENAI_API_KEY", "google-key")

    configs = build_provider_configs_from_env()

    assert [config.provider_type for config in configs] == [
        ProviderType.OPENAI_COMPATIBLE,
        ProviderType.OPENAI_RESPONSES,
        ProviderType.ANTHROPIC,
        ProviderType.GOOGLE,
    ]
    assert configs[0].base_url == "https://compatible.example/v1"
