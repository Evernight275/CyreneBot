from __future__ import annotations

import asyncio
import importlib
import json
import logging
from datetime import UTC, datetime
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from cyreneAI.api.cli import init_plugin_project
from cyreneAI.bootstrap import build_cyrene_ai_runtime
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
    PluginCommandRequest,
    PluginCommandResult,
    PluginDefinition,
    PluginEventDefinition,
    PluginEventType,
    PluginLifecycleStatus,
    PluginMiddlewareDefinition,
    PluginMiddlewareType,
    PluginScheduledTask,
    PluginStatusReport,
    PluginTaskDefinition,
    PluginTaskStatus,
)
from cyreneAI.core.schema.provider import (
    ProviderConfig,
    ProviderInfo,
    ProviderModel,
    ProviderType,
)
from cyreneAI.server import create_app
from cyreneAI.server.app import (
    _log_plugin_startup_state,
    create_app_with_runtime_builder,
)
from cyreneAI.server.config import (
    build_bot_admin_config_from_env,
    ServerSettings,
    build_bot_polling_state_database_path_from_env,
    build_context_database_path_from_env,
    build_controlled_shell_enabled_from_env,
    build_disabled_plugin_ids_from_env,
    build_plugin_paths_from_env,
    build_plugin_python_dependency_auto_install_from_env,
    build_plugin_python_dependency_install_timeout_seconds_from_env,
    build_plugin_python_environment_root_path_from_env,
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
    build_tool_sandbox_commands_from_env,
    build_tool_sandbox_mode_from_env,
    build_tool_sandbox_timeout_seconds_from_env,
    build_shell_command_policy_from_env,
    build_shell_cwd_root_path_from_env,
    build_shell_timeout_seconds_from_env,
    build_vector_database_path_from_env,
)


@pytest.mark.asyncio
async def test_server_main_imports_inside_running_event_loop() -> None:
    import cyreneAI.server.main as server_main

    importlib.reload(server_main)


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


async def _build_fake_runtime(*, channel_id: str = "fake") -> CyreneAIRuntime:
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


def _client(
    *,
    channel_id: str = "fake",
    settings: ServerSettings | None = None,
    telegram_webhook_secret: str | None = None,
    telegram_provider_id: str | None = None,
    telegram_model: str | None = None,
    telegram_polling_enabled: bool = False,
) -> TestClient:
    return TestClient(
        create_app(
            asyncio.run(_build_fake_runtime(channel_id=channel_id)),
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
                            choices=["Cyrene", "world"],
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
            middlewares=[
                PluginMiddlewareDefinition(
                    middleware_type=PluginMiddlewareType.LLM,
                    description="Trace LLM calls.",
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


class FakePluginExecutor:
    async def execute(self, request: PluginCommandRequest) -> PluginCommandResult:
        return PluginCommandResult(metadata={"command": request.command.name})


def _managed_plugin_client() -> TestClient:
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
                    usage="/hello",
                )
            ],
        ),
        FakePluginExecutor(),
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


class FakePluginTaskScheduler:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.canceled: list[str] = []
        self.tasks = [
            PluginScheduledTask(
                task_id="task-1",
                plugin_id="demo.hello",
                task_name="follow_up",
                run_at=now,
                payload={"session_id": "s1"},
                key="follow:s1",
                status=PluginTaskStatus.FAILED,
                last_error="boom",
                created_at=now,
                updated_at=now,
            )
        ]

    async def list_tasks(
        self,
        *,
        plugin_id=None,
        task_name=None,
        statuses=None,
    ):
        tasks = list(self.tasks)
        if plugin_id is not None:
            tasks = [task for task in tasks if task.plugin_id == plugin_id]
        if task_name is not None:
            tasks = [task for task in tasks if task.task_name == task_name]
        if statuses is not None:
            tasks = [task for task in tasks if task.status in statuses]
        return tasks

    async def cancel_task(self, task_id: str) -> None:
        self.canceled.append(task_id)

    async def retry_task(self, task_id: str) -> str:
        return f"{task_id}:retry"

    def unregister_plugin(self, plugin_id: str) -> None:
        return None

    async def shutdown(self) -> None:
        pass


def _plugin_task_client() -> TestClient:
    runtime = CyreneAIRuntime(
        provider_manager=ProviderManager(ProviderFactory()),
        context_builder=ContextWindowBuilder(),
        plugin_task_scheduler=FakePluginTaskScheduler(),
    )
    return TestClient(
        create_app(
            runtime,
            settings=ServerSettings(auth_enabled=False),
        )
    )


class FakePluginStorageNamespace:
    def __init__(self) -> None:
        self.values = {"state": {"ready": True}, "count": 2}

    async def get(self, key: str, default=None):
        return self.values.get(key, default)

    async def set(self, key: str, value) -> None:
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def list_keys(self) -> list[str]:
        return sorted(self.values)


class FakePluginStorage:
    def __init__(self) -> None:
        self.namespace_value = FakePluginStorageNamespace()

    def namespace(self, plugin_id: str) -> FakePluginStorageNamespace:
        return self.namespace_value

    async def close(self) -> None:
        pass


def _plugin_storage_client() -> TestClient:
    registry = PluginRegistry()
    registry.register(
        PluginDefinition(
            plugin_id="demo.hello",
            name="Demo Hello",
            description="Demo plugin.",
        )
    )
    runtime = CyreneAIRuntime(
        provider_manager=ProviderManager(ProviderFactory()),
        context_builder=ContextWindowBuilder(),
        plugin_manager=PluginManager(registry),
        plugin_storage=FakePluginStorage(),
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


def test_server_readiness_requires_lifespan_startup() -> None:
    response = _client().get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_server_readiness_reports_lifespan_runtime_ready() -> None:
    client = _client()

    with client:
        response = client.get("/ready")

        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
        assert client.app.state.runtime_ready is True

    assert client.app.state.runtime_ready is False


def test_server_readiness_waits_for_runtime_builder_lifespan() -> None:
    async def build_runtime() -> CyreneAIRuntime:
        return await _build_fake_runtime()

    cold_client = TestClient(
        create_app_with_runtime_builder(
            build_runtime,
            settings=ServerSettings(auth_enabled=False),
        )
    )
    ready_client = TestClient(
        create_app_with_runtime_builder(
            build_runtime,
            settings=ServerSettings(auth_enabled=False),
        )
    )

    cold_response = cold_client.get("/ready")

    assert cold_response.status_code == 503
    assert cold_response.json() == {"status": "not_ready"}

    with ready_client:
        ready_response = ready_client.get("/ready")

        assert ready_response.status_code == 200
        assert ready_response.json() == {"status": "ready"}
        assert ready_client.app.state.runtime is not None

    assert ready_client.app.state.runtime_ready is False


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


def test_server_runs_agent() -> None:
    response = _client().post(
        "/agents/run",
        json={
            "provider_id": "provider-1",
            "model": "chat-model",
            "goal": "ping",
            "metadata": {
                "session_id": "agent-session",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["completed"] is True
    assert data["stop_reason"] == "final_response"
    assert data["metadata"]["session_id"] == "agent-session"
    assert data["response"]["message"]["content"][0]["text"] == "pong"
    assert data["steps"][0]["request"]["messages"][0]["content"][0]["text"] == "ping"


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


def test_server_builds_bot_admin_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_BOT_ADMIN_USER_IDS", "123456789, 987654321;42")

    config = build_bot_admin_config_from_env()

    assert config is not None
    assert config.user_ids == ["123456789", "987654321", "42"]


def test_server_disables_bot_admin_config_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CYRENEAI_BOT_ADMIN_USER_IDS", raising=False)

    assert build_bot_admin_config_from_env() is None


def test_server_builds_context_database_path_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_CONTEXT_DATABASE_PATH", "data/context.db")

    assert build_context_database_path_from_env() == "data/context.db"


def test_server_uses_default_context_database_path(monkeypatch) -> None:
    monkeypatch.delenv("CYRENEAI_CONTEXT_DATABASE_PATH", raising=False)

    assert build_context_database_path_from_env() == "data/context.db"


def test_server_builds_vector_database_path_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_VECTOR_DATABASE_PATH", "data/vector.db")

    assert build_vector_database_path_from_env() == "data/vector.db"


def test_server_uses_default_vector_database_path(monkeypatch) -> None:
    monkeypatch.delenv("CYRENEAI_VECTOR_DATABASE_PATH", raising=False)

    assert build_vector_database_path_from_env() == "data/vector.db"


def test_server_builds_tool_sandbox_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_TOOL_SANDBOX_MODE", "subprocess")
    monkeypatch.setenv(
        "CYRENEAI_TOOL_SANDBOX_COMMANDS_JSON",
        '{"lookup":["python","tool.py"]}',
    )
    monkeypatch.setenv("CYRENEAI_TOOL_SANDBOX_TIMEOUT_SECONDS", "10")

    assert build_tool_sandbox_mode_from_env() == "subprocess"
    assert build_tool_sandbox_commands_from_env() == {
        "lookup": ["python", "tool.py"],
    }
    assert build_tool_sandbox_timeout_seconds_from_env() == 10


def test_server_disables_tool_sandbox_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CYRENEAI_TOOL_SANDBOX_MODE", raising=False)
    monkeypatch.delenv("CYRENEAI_TOOL_SANDBOX_COMMANDS_JSON", raising=False)
    monkeypatch.delenv("CYRENEAI_TOOL_SANDBOX_TIMEOUT_SECONDS", raising=False)

    assert build_tool_sandbox_mode_from_env() is None
    assert build_tool_sandbox_commands_from_env() is None
    assert build_tool_sandbox_timeout_seconds_from_env() is None


def test_server_rejects_invalid_tool_sandbox_mode(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_TOOL_SANDBOX_MODE", "docker")

    with pytest.raises(ValueError):
        build_tool_sandbox_mode_from_env()


def test_server_rejects_invalid_tool_sandbox_commands(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_TOOL_SANDBOX_COMMANDS_JSON", '{"lookup":[]}')

    with pytest.raises(ValueError):
        build_tool_sandbox_commands_from_env()


def test_server_builds_controlled_shell_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("CYRENEAI_CONTROLLED_SHELL_ENABLED", "true")
    monkeypatch.setenv(
        "CYRENEAI_SHELL_COMMAND_POLICY_JSON",
        json.dumps(
            {
                "rules": [
                    {
                        "command": "echo",
                        "decision": "allow",
                    }
                ],
                "default_decision": "deny",
            }
        ),
    )
    monkeypatch.setenv("CYRENEAI_SHELL_CWD_ROOT_PATH", "D:/workspace")
    monkeypatch.setenv("CYRENEAI_SHELL_TIMEOUT_SECONDS", "15")

    policy = build_shell_command_policy_from_env()

    assert build_controlled_shell_enabled_from_env() is True
    assert policy is not None
    assert policy.rules[0].command == "echo"
    assert policy.rules[0].decision == "allow"
    assert build_shell_cwd_root_path_from_env() == "D:/workspace"
    assert build_shell_timeout_seconds_from_env() == 15


def test_server_disables_controlled_shell_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CYRENEAI_CONTROLLED_SHELL_ENABLED", raising=False)
    monkeypatch.delenv("CYRENEAI_SHELL_COMMAND_POLICY_JSON", raising=False)
    monkeypatch.delenv("CYRENEAI_SHELL_CWD_ROOT_PATH", raising=False)
    monkeypatch.delenv("CYRENEAI_SHELL_TIMEOUT_SECONDS", raising=False)

    assert build_controlled_shell_enabled_from_env() is False
    assert build_shell_command_policy_from_env() is None
    assert build_shell_cwd_root_path_from_env() is None
    assert build_shell_timeout_seconds_from_env() == 10


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


def test_server_builds_plugin_python_environment_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "CYRENEAI_PLUGIN_PYTHON_ENVIRONMENT_ROOT_PATH",
        "data/plugin_envs",
    )
    monkeypatch.setenv("CYRENEAI_PLUGIN_PYTHON_AUTO_INSTALL", "false")
    monkeypatch.setenv("CYRENEAI_PLUGIN_PYTHON_INSTALL_TIMEOUT_SECONDS", "120")

    assert build_plugin_python_environment_root_path_from_env() == "data/plugin_envs"
    assert build_plugin_python_dependency_auto_install_from_env() is False
    assert build_plugin_python_dependency_install_timeout_seconds_from_env() == 120


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
    middlewares = client.get("/plugins/middlewares")
    plugin_detail = client.get("/plugins/demo.hello")
    plugin_commands = client.get("/plugins/demo.hello/commands")
    plugin_events = client.get("/plugins/demo.hello/events")
    plugin_tasks = client.get("/plugins/demo.hello/tasks")
    plugin_middlewares = client.get("/plugins/demo.hello/middlewares")
    plugin_status = client.get("/plugins/demo.hello/status")

    assert plugins.status_code == 200
    assert plugins.json()["plugins"][0]["plugin_id"] == "demo.hello"
    assert commands.json()["commands"][0]["name"] == "hello"
    assert commands.json()["commands"][0]["arguments"][0]["name"] == "name"
    assert commands.json()["commands"][0]["arguments"][0]["kind"] == "positional"
    assert commands.json()["commands"][0]["arguments"][0]["choices"] == [
        "Cyrene",
        "world",
    ]
    assert events.json()["events"][0]["event_type"] == "message"
    assert tasks.json()["tasks"][0]["name"] == "follow_up"
    assert middlewares.json()["middlewares"][0]["middleware_type"] == "llm"
    assert statuses.json()["statuses"][0]["plugin_id"] == "demo.hello"
    assert statuses.json()["statuses"][1]["status"] == "disabled"
    assert plugin_detail.status_code == 200
    assert plugin_detail.json()["plugin_id"] == "demo.hello"
    assert plugin_commands.status_code == 200
    assert plugin_commands.json()["commands"][0]["name"] == "hello"
    assert plugin_events.status_code == 200
    assert plugin_events.json()["events"][0]["event_type"] == "message"
    assert plugin_tasks.status_code == 200
    assert plugin_tasks.json()["tasks"][0]["name"] == "follow_up"
    assert plugin_middlewares.status_code == 200
    assert plugin_middlewares.json()["middlewares"][0]["middleware_type"] == "llm"
    assert plugin_status.status_code == 200
    assert plugin_status.json()["plugin_id"] == "demo.hello"


def test_server_inspects_enables_and_disables_plugin() -> None:
    client = _managed_plugin_client()

    inspect_response = client.get("/plugins/demo.hello/inspect")
    disable_response = client.post("/plugins/demo.hello/disable")
    disabled_commands = client.get("/plugins/commands")
    enable_response = client.post("/plugins/demo.hello/enable")

    assert inspect_response.status_code == 200
    assert inspect_response.json()["definition"]["plugin_id"] == "demo.hello"
    assert inspect_response.json()["commands"][0]["name"] == "hello"
    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False
    assert disabled_commands.json()["commands"] == []
    assert enable_response.status_code == 200
    assert enable_response.json()["enabled"] is True


def test_server_reload_requires_source_tracking() -> None:
    response = _managed_plugin_client().post("/plugins/demo.hello/reload")

    assert response.status_code == 503


def test_server_installs_and_reloads_filesystem_plugin(tmp_path) -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime(register_builtin_plugins=False)
        client = TestClient(
            create_app(runtime, settings=ServerSettings(auth_enabled=False))
        )
        project_path = init_plugin_project(tmp_path / "my_plugin")

        try:
            install_response = client.post(
                "/plugins/install-path",
                json={"path": str(project_path)},
            )

            manifest_path = project_path / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["version"] = "0.2.0"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            reload_response = client.post("/plugins/my_plugin/reload")
            inspect_response = client.get("/plugins/my_plugin/inspect")

            assert install_response.status_code == 200
            assert install_response.json()["installed"][0]["plugin_id"] == "my_plugin"
            assert install_response.json()["sources"][0]["source_type"] == "filesystem"
            assert reload_response.status_code == 200
            assert reload_response.json()["metadata"]["version"] == "0.2.0"
            assert reload_response.json()["metadata"]["reload_audit"][
                "previous_version"
            ] == "0.1.0"
            assert reload_response.json()["metadata"]["reload_audit"][
                "version_changed"
            ] is True
            assert inspect_response.json()["source"]["version"] == "0.2.0"
            assert inspect_response.json()["source"]["metadata"]["reload_audit"][
                "version"
            ] == "0.2.0"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_server_validates_plugin_path(tmp_path) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin")

    response = _plugin_client().post(
        "/plugins/validate-path",
        json={"path": str(project_path)},
    )

    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["plugin_id"] == "my_plugin"


def test_server_validate_path_reports_duplicate_plugin_id(tmp_path) -> None:
    project_path = init_plugin_project(
        tmp_path / "demo_hello",
        plugin_id="demo.hello",
    )

    response = _plugin_client().post(
        "/plugins/validate-path",
        json={"path": str(project_path)},
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "already installed" in response.json()["errors"][0]


def test_server_rejects_duplicate_plugin_install(tmp_path) -> None:
    async def run() -> None:
        runtime = await build_cyrene_ai_runtime(register_builtin_plugins=False)
        client = TestClient(
            create_app(runtime, settings=ServerSettings(auth_enabled=False))
        )
        project_path = init_plugin_project(tmp_path / "my_plugin")

        try:
            first_response = client.post(
                "/plugins/install-path",
                json={"path": str(project_path)},
            )
            second_response = client.post(
                "/plugins/install-path",
                json={"path": str(project_path)},
            )

            assert first_response.status_code == 200
            assert second_response.status_code == 409
            assert "already installed" in second_response.json()["detail"]
        finally:
            await runtime.close()

    asyncio.run(run())


def test_server_rejects_unsupported_plugin_isolation(tmp_path) -> None:
    project_path = init_plugin_project(tmp_path / "my_plugin")
    manifest_path = project_path / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["metadata"]["isolation"]["mode"] = "subprocess"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    response = _plugin_client().post(
        "/plugins/validate-path",
        json={"path": str(project_path)},
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "isolation mode subprocess is not supported" in response.json()["errors"][0]


def test_server_reports_invalid_plugin_path(tmp_path) -> None:
    response = _plugin_client().post(
        "/plugins/validate-path",
        json={"path": str(tmp_path / "missing")},
    )

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["errors"]


def test_server_manages_plugin_task_instances() -> None:
    client = _plugin_task_client()

    list_response = client.get(
        "/plugins/tasks/instances",
        params={"plugin_id": "demo.hello", "status": "failed"},
    )
    cancel_response = client.post("/plugins/tasks/task-1/cancel")
    retry_response = client.post("/plugins/tasks/task-1/retry")

    assert list_response.status_code == 200
    assert list_response.json()["tasks"][0]["task_id"] == "task-1"
    assert cancel_response.status_code == 200
    assert cancel_response.json()["action"] == "cancel_task"
    assert retry_response.status_code == 200
    assert retry_response.json()["metadata"]["new_task_id"] == "task-1:retry"


def test_server_debugs_plugin_storage() -> None:
    client = _plugin_storage_client()

    keys_response = client.get("/plugins/demo.hello/storage")
    value_response = client.get("/plugins/demo.hello/storage/state")
    delete_response = client.delete("/plugins/demo.hello/storage/count")
    cleared_response = client.delete("/plugins/demo.hello/storage")

    assert keys_response.status_code == 200
    assert keys_response.json()["keys"] == ["count", "state"]
    assert value_response.status_code == 200
    assert value_response.json()["value"] == {"ready": True}
    assert delete_response.status_code == 200
    assert delete_response.json()["metadata"]["key"] == "count"
    assert cleared_response.status_code == 200
    assert cleared_response.json()["metadata"]["deleted_keys"] == ["state"]


def test_server_returns_404_for_missing_plugin_detail() -> None:
    response = _plugin_client().get("/plugins/missing.plugin")

    assert response.status_code == 404


def test_server_lists_plugin_runtime_capabilities() -> None:
    response = _plugin_client().get("/plugins/runtime-capabilities")

    assert response.status_code == 200
    permissions = {
        item["permission"]: item
        for item in response.json()["permissions"]
    }
    assert permissions["llm"]["status"] == "supported"
    assert permissions["llm"]["dependencies"] == ["llm", "agent"]
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
    assert dependencies["agent"]["permission"] == "llm"
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
