from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.server.channel_polling import ChannelPollingRunner
from cyreneAI.server.config import ServerSettings, build_server_settings_from_env
from cyreneAI.server.routes import (
    auth,
    channels,
    chat,
    health,
    images,
    plugins,
    providers,
)
from cyreneAI.server.routes import telegram


logger = logging.getLogger("uvicorn.error")


def create_app(
    runtime: CyreneAIRuntime,
    settings: ServerSettings | None = None,
    telegram_webhook_secret: str | None = None,
    telegram_provider_id: str | None = None,
    telegram_model: str | None = None,
    telegram_polling_enabled: bool = False,
    telegram_polling_interval_seconds: float = 1.0,
    telegram_polling_timeout_seconds: int = 30,
    telegram_polling_limit: int | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _log_plugin_startup_state(runtime)
        polling_runner = _build_telegram_polling_runner(app)
        app.state.telegram_polling_runner = polling_runner
        if polling_runner is not None:
            polling_runner.start()
        try:
            yield
        finally:
            if polling_runner is not None:
                await polling_runner.stop()
            await runtime.close()

    app = FastAPI(title="CyreneBot API", lifespan=lifespan)
    app.state.runtime = runtime
    app.state.server_settings = settings or build_server_settings_from_env()
    app.state.telegram_webhook_secret = telegram_webhook_secret
    app.state.telegram_provider_id = telegram_provider_id
    app.state.telegram_model = telegram_model
    app.state.telegram_polling_enabled = telegram_polling_enabled
    app.state.telegram_polling_interval_seconds = telegram_polling_interval_seconds
    app.state.telegram_polling_timeout_seconds = telegram_polling_timeout_seconds
    app.state.telegram_polling_limit = telegram_polling_limit

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(providers.router)
    app.include_router(chat.router)
    app.include_router(images.router)
    app.include_router(plugins.router)
    app.include_router(channels.router)
    app.include_router(telegram.router)
    return app


def _log_plugin_startup_state(runtime: CyreneAIRuntime) -> None:
    plugin_manager = runtime.plugin_manager
    if plugin_manager is None:
        logger.info("CyreneBot plugins disabled: no plugin manager")
        return

    plugins = plugin_manager.list_plugins()
    commands = plugin_manager.list_commands()
    statuses = plugin_manager.list_statuses()
    plugin_items = [
        f"{plugin.plugin_id}@{plugin.version}"
        for plugin in plugins
        if plugin.enabled
    ]
    command_items = [
        _format_plugin_command(command.name, command.usage, command.aliases)
        for command in commands
        if command.enabled
    ]

    logger.info(
        "CyreneBot plugins loaded: count=%s plugins=%s",
        len(plugin_items),
        ", ".join(plugin_items) or "(none)",
    )
    logger.info(
        "CyreneBot commands loaded: count=%s commands=%s",
        len(command_items),
        ", ".join(command_items) or "(none)",
    )
    status_items = [
        f"{status.plugin_id}:{status.status}"
        + (f" reason={status.reason}" if status.reason else "")
        for status in statuses
    ]
    logger.info(
        "CyreneBot plugin statuses: count=%s statuses=%s",
        len(status_items),
        ", ".join(status_items) or "(none)",
    )


def _format_plugin_command(
    name: str,
    usage: str | None,
    aliases: list[str],
) -> str:
    command = usage or f"/{name}"
    if not aliases:
        return command
    return f"{command} aliases={','.join(aliases)}"


def _build_telegram_polling_runner(app: FastAPI) -> ChannelPollingRunner | None:
    if not app.state.telegram_polling_enabled:
        return None
    if not app.state.telegram_provider_id or not app.state.telegram_model:
        raise RuntimeError("Telegram polling provider_id and model are required")
    registry = app.state.runtime.bot_channel_registry
    if registry is None or not registry.exists("telegram"):
        raise RuntimeError("Telegram polling requires a registered telegram channel")
    channel = registry.get_channel("telegram")
    if not hasattr(channel, "poll_events"):
        raise RuntimeError("Telegram channel does not support polling")
    return ChannelPollingRunner(
        runtime=app.state.runtime,
        channel_id="telegram",
        provider_id=app.state.telegram_provider_id,
        model=app.state.telegram_model,
        interval_seconds=app.state.telegram_polling_interval_seconds,
        timeout_seconds=app.state.telegram_polling_timeout_seconds,
        limit=app.state.telegram_polling_limit,
        allowed_updates=["message"],
        metadata={
            "source": "telegram_polling",
        },
    )
