from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from fastapi.testclient import TestClient

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.core.context.builder import ContextWindowBuilder
from cyreneAI.core.plugin.manager import PluginManager
from cyreneAI.core.plugin.registry import PluginRegistry
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
from cyreneAI.core.schema.plugin import (
    PluginCommandArgumentDefinition,
    PluginCommandArgumentKind,
    PluginCommandDefinition,
    PluginDefinition,
    PluginEventDefinition,
    PluginEventType,
    PluginLifecycleStatus,
    PluginStatusReport,
    PluginTaskDefinition,
)
from cyreneAI.core.schema.provider import (
    ProviderConfig,
    ProviderInfo,
    ProviderModel,
    ProviderType,
)
from cyreneAI.server import create_app
from cyreneAI.server.app import _log_plugin_startup_state
from cyreneAI.server.config import (
    ServerSettings,
    build_bot_polling_state_database_path_from_env,
    build_context_database_path_from_env,
    build_disabled_plugin_ids_from_env,
    build_plugin_paths_from_env,
    build_plugin_storage_path_from_env,
    build_plugin_task_database_path_from_env,
    build_provider_configs_from_env,
    build_telegram_bot_token_from_env,
    build_telegram_polling_enabled_from_env,
    build_telegram_polling_interval_seconds_from_env,
    build_telegram_polling_limit_from_env,
    build_telegram_polling_timeout_seconds_from_env,
    build_telegram_webhook_model_from_env,
    build_telegram_webhook_provider_id_from_env,
    build_telegram_webhook_secret_from_env,
)


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
    def __init__(self, *, channel_id: str = "fake") -> None:
        self.channel_id = channel_id
        self.actions: list[BotAction] = []

    def map_update(self, update: dict) -> BotEvent:
        return BotEvent(
            event_id=str(update["event_id"]),
            event_type=BotEventType.MESSAGE,
            channel_id=self.channel_id,
            session_id=f"{self.channel_id}:user-1",
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


def _client(
    *,
    channel_id: str = "fake",
    settings: ServerSettings | None = None,
    telegram_webhook_secret: str | None = None,
    telegram_provider_id: str | None = None,
    telegram_model: str | None = None,
    telegram_polling_enabled: bool = False,
) -> TestClient:
    async def build_runtime() -> CyreneAIRuntime:
        provider = FakeServerProvider()
        channel = FakeServerChannel(channel_id=channel_id)
        bot_channel_registry = BotChannelRegistry()
        bot_channel_registry.register(
            BotChannelDefinition(
                channel_id=channel_id,
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
            settings=settings or ServerSettings(auth_enabled=False),
            telegram_webhook_secret=telegram_webhook_secret,
            telegram_provider_id=telegram_provider_id,
            telegram_model=telegram_model,
            telegram_polling_enabled=telegram_polling_enabled,
        )
    )


def _plugin_client() -> TestClient:
    registry = PluginRegistry()
    registry.register(
        PluginDefinition(
            plugin_id="demo.hello",
            name="Demo Hello",
            description="Demo plugin.",
            version="0.1.0",
            commands=[
                PluginCommandDefinition(
                    name="hello",
                    description="Say hello.",
                    usage="/hello <name>",
                    arguments=[
                        PluginCommandArgumentDefinition(
                            name="name",
                            kind=PluginCommandArgumentKind.POSITIONAL,
                        )
                    ],
                )
            ],
            events=[
                PluginEventDefinition(
                    event_type=PluginEventType.MESSAGE,
                    description="Observe messages.",
                )
            ],
            tasks=[
                PluginTaskDefinition(
                    name="follow_up",
                    description="Follow up later.",
                )
            ],
        )
    )
    registry.record_status(
        PluginStatusReport(
            plugin_id="demo.disabled",
            status=PluginLifecycleStatus.DISABLED,
            reason="disabled_by_config",
        )
    )
    runtime = CyreneAIRuntime(
        provider_manager=ProviderManager(ProviderFactory()),
        context_builder=ContextWindowBuilder(),
        plugin_manager=PluginManager(registry),
    )
    return TestClient(
        create_app(
            runtime,
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


def test_server_telegram_webhook_sends_bot_reply_without_admin_auth() -> None:
    response = _client(
        channel_id="telegram",
        settings=ServerSettings(
            auth_enabled=True,
            admin_username="admin",
            admin_password="password",
            session_secret="secret",
        ),
        telegram_webhook_secret="webhook-secret",
        telegram_provider_id="provider-1",
        telegram_model="chat-model",
    ).post(
        "/telegram/webhook",
        headers={
            "X-Telegram-Bot-Api-Secret-Token": "webhook-secret",
        },
        json={
            "event_id": "event-1",
            "text": "ping",
        },
    )

    assert response.status_code == 200
    sent_actions = response.json()["sent_actions"]
    assert len(sent_actions) == 1
    assert sent_actions[0]["channel_id"] == "telegram"
    assert sent_actions[0]["message"]["content"][0]["text"] == "pong"


def test_server_telegram_webhook_rejects_invalid_secret() -> None:
    response = _client(
        channel_id="telegram",
        telegram_webhook_secret="webhook-secret",
        telegram_provider_id="provider-1",
        telegram_model="chat-model",
    ).post(
        "/telegram/webhook",
        headers={
            "X-Telegram-Bot-Api-Secret-Token": "wrong",
        },
        json={
            "event_id": "event-1",
            "text": "ping",
        },
    )

    assert response.status_code == 401


def test_server_telegram_webhook_requires_provider_and_model() -> None:
    response = _client(
        channel_id="telegram",
    ).post(
        "/telegram/webhook",
        json={
            "event_id": "event-1",
            "text": "ping",
        },
    )

    assert response.status_code == 400


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


def test_server_builds_telegram_webhook_config_from_env(monkeypatch) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_SECRET_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_SECRET_TOKEN", "webhook-secret")
    monkeypatch.setenv("TELEGRAM_BOT_PROVIDER_ID", "provider-1")
    monkeypatch.setenv("TELEGRAM_BOT_MODEL", "bot-model")

    assert build_telegram_bot_token_from_env() == "bot-token"
    assert build_telegram_webhook_secret_from_env() == "webhook-secret"
    assert build_telegram_webhook_provider_id_from_env() == "provider-1"
    assert build_telegram_webhook_model_from_env() == "bot-model"


def test_server_builds_telegram_webhook_config_from_provider_fallbacks(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_PROVIDER_ID", "")
    monkeypatch.setenv("OPENAI_COMPATIBLE_PROVIDER_ID", "")
    monkeypatch.setenv("OPENAI_RESPONSES_PROVIDER_ID", "")
    monkeypatch.setenv("OPENAI_PROVIDER_ID", "")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "compatible-key")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL", "chat-model")

    assert build_telegram_webhook_provider_id_from_env() == "openai-compatible"
    assert build_telegram_webhook_model_from_env() == "chat-model"


def test_server_builds_telegram_polling_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_BOT_POLLING_STATE_DATABASE_PATH", "data/bot_polling.db")
    monkeypatch.setenv("TELEGRAM_BOT_MODE", "polling")
    monkeypatch.setenv("TELEGRAM_BOT_POLL_INTERVAL_SECONDS", "0.5")
    monkeypatch.setenv("TELEGRAM_BOT_POLL_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("TELEGRAM_BOT_POLL_LIMIT", "10")

    assert build_telegram_polling_enabled_from_env() is True
    assert build_telegram_polling_interval_seconds_from_env() == 0.5
    assert build_telegram_polling_timeout_seconds_from_env() == 20
    assert build_telegram_polling_limit_from_env() == 10
    assert build_bot_polling_state_database_path_from_env() == "data/bot_polling.db"


def test_server_builds_context_database_path_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_CONTEXT_DATABASE_PATH", "data/context.db")

    assert build_context_database_path_from_env() == "data/context.db"


def test_server_uses_default_context_database_path(monkeypatch) -> None:
    monkeypatch.delenv("CYRENEAI_CONTEXT_DATABASE_PATH", raising=False)

    assert build_context_database_path_from_env() == "data/context.db"


def test_server_builds_plugin_paths_from_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "CYRENEAI_PLUGIN_PATH",
        "plugins/demo_hello;plugins/demo_status",
    )

    assert build_plugin_paths_from_env() == [
        "plugins/demo_hello",
        "plugins/demo_status",
    ]


def test_server_disables_plugin_paths_by_default(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_PLUGIN_PATH", "")

    assert build_plugin_paths_from_env() == []


def test_server_builds_plugin_storage_path_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_PLUGIN_STORAGE_PATH", "data/plugin_storage")

    assert build_plugin_storage_path_from_env() == "data/plugin_storage"


def test_server_builds_plugin_task_database_path_from_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "CYRENEAI_PLUGIN_TASK_DATABASE_PATH",
        "data/plugin_tasks.db",
    )

    assert build_plugin_task_database_path_from_env() == "data/plugin_tasks.db"


def test_server_builds_disabled_plugin_ids_from_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "CYRENEAI_DISABLED_PLUGINS",
        "demo.hello;demo.status, demo.extra",
    )

    assert build_disabled_plugin_ids_from_env() == [
        "demo.hello",
        "demo.status",
        "demo.extra",
    ]


def test_server_lists_plugins_commands_events_tasks_and_statuses() -> None:
    client = _plugin_client()

    plugins = client.get("/plugins")
    commands = client.get("/plugins/commands")
    events = client.get("/plugins/events")
    tasks = client.get("/plugins/tasks")
    statuses = client.get("/plugins/statuses")

    assert plugins.status_code == 200
    assert plugins.json()["plugins"][0]["plugin_id"] == "demo.hello"
    assert commands.json()["commands"][0]["name"] == "hello"
    assert commands.json()["commands"][0]["arguments"][0]["name"] == "name"
    assert commands.json()["commands"][0]["arguments"][0]["kind"] == "positional"
    assert events.json()["events"][0]["event_type"] == "message"
    assert tasks.json()["tasks"][0]["name"] == "follow_up"
    assert statuses.json()["statuses"][0]["plugin_id"] == "demo.hello"
    assert statuses.json()["statuses"][1]["status"] == "disabled"


def test_server_lists_plugin_runtime_capabilities() -> None:
    response = _plugin_client().get("/plugins/runtime-capabilities")

    assert response.status_code == 200
    permissions = {
        item["permission"]: item
        for item in response.json()["permissions"]
    }
    assert permissions["llm"]["status"] == "supported"
    assert permissions["llm"]["dependencies"] == ["llm"]
    assert permissions["chat"]["status"] == "reserved"
    assert permissions["tool"]["status"] == "supported"
    assert permissions["tool"]["setup_apis"] == ["register_tool"]
    assert permissions["rag"]["status"] == "reserved"
    assert permissions["provider_write"]["status"] == "reserved"
    dependencies = {
        item["name"]: item
        for item in response.json()["dependencies"]
    }
    assert dependencies["llm"]["permission"] == "llm"
    assert dependencies["storage"]["permission"] == "storage"


def test_server_logs_loaded_plugins_and_commands(caplog) -> None:
    registry = PluginRegistry()
    registry.register(
        PluginDefinition(
            plugin_id="demo.hello",
            name="Demo Hello",
            description="Demo plugin.",
            version="0.1.0",
            commands=[
                PluginCommandDefinition(
                    name="hello",
                    description="Say hello.",
                    usage="/hello <name>",
                    aliases=["hi"],
                )
            ],
        )
    )
    runtime = CyreneAIRuntime(
        provider_manager=ProviderManager(ProviderFactory()),
        context_builder=ContextWindowBuilder(),
        plugin_manager=PluginManager(registry),
    )

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        _log_plugin_startup_state(runtime)

    assert "CyreneBot plugins loaded: count=1 plugins=demo.hello@0.1.0" in caplog.text
    assert (
        "CyreneBot commands loaded: count=1 commands=/hello <name> aliases=hi"
        in caplog.text
    )


def test_server_logs_when_plugin_manager_is_missing(caplog) -> None:
    runtime = CyreneAIRuntime(
        provider_manager=ProviderManager(ProviderFactory()),
        context_builder=ContextWindowBuilder(),
    )

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        _log_plugin_startup_state(runtime)

    assert "CyreneBot plugins disabled: no plugin manager" in caplog.text


def test_server_disables_telegram_polling_by_default(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_MODE", "")
    monkeypatch.setenv("TELEGRAM_BOT_POLL_LIMIT", "")

    assert build_telegram_polling_enabled_from_env() is False
    assert build_telegram_polling_limit_from_env() is None


def test_server_telegram_polling_requires_registered_channel() -> None:
    client = _client(
        telegram_provider_id="provider-1",
        telegram_model="chat-model",
        telegram_polling_enabled=True,
    )

    try:
        with client:
            pass
    except RuntimeError as exc:
        assert str(exc) == "Telegram polling requires a registered telegram channel"
    else:
        raise AssertionError("Expected RuntimeError")
