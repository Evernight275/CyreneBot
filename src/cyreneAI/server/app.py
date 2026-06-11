from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.server.auth import verify_admin_session
from cyreneAI.server.channel_polling import ChannelPollingRunner
from cyreneAI.server.channel_websocket import ChannelWebSocketRunner
from cyreneAI.server.config import ServerSettings, build_server_settings_from_env
from cyreneAI.server.logging_middleware import (
    DEFAULT_REQUEST_ID_HEADER,
    install_request_logging_middleware,
)
from cyreneAI.server.routes import (
    agents,
    auth,
    channels,
    chat,
    health,
    images,
    plugins,
    providers,
    qq,
    telegram,
)

logger = logging.getLogger("cyreneAI.server.startup")


def create_app(
    runtime: CyreneAIRuntime,
    settings: ServerSettings | None = None,
    telegram_webhook_secret: str | None = None,
    telegram_provider_id: str | None = None,
    telegram_model: str | None = None,
    qq_webhook_secret: str | None = None,
    qq_provider_id: str | None = None,
    qq_model: str | None = None,
    qq_websocket_enabled: bool = False,
    telegram_polling_enabled: bool = False,
    telegram_polling_interval_seconds: float = 1.0,
    telegram_polling_timeout_seconds: int = 30,
    telegram_polling_limit: int | None = None,
    request_logging_enabled: bool = True,
    request_id_header: str = DEFAULT_REQUEST_ID_HEADER,
    frontend_dist_path: str | Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _log_plugin_startup_state(runtime)
        polling_runner = _build_telegram_polling_runner(app)
        qq_websocket_runner = _build_qq_websocket_runner(app)
        app.state.telegram_polling_runner = polling_runner
        app.state.qq_websocket_runner = qq_websocket_runner
        if polling_runner is not None:
            polling_runner.start()
        if qq_websocket_runner is not None:
            qq_websocket_runner.start()
        app.state.runtime_ready = True
        try:
            yield
        finally:
            app.state.runtime_ready = False
            if qq_websocket_runner is not None:
                await qq_websocket_runner.stop()
            if polling_runner is not None:
                await polling_runner.stop()
            await runtime.close()

    app = FastAPI(title="CyreneBot API", lifespan=lifespan)
    install_request_logging_middleware(
        app,
        enabled=request_logging_enabled,
        request_id_header=request_id_header,
    )
    app.state.runtime = runtime
    app.state.runtime_ready = False
    app.state.server_settings = settings or build_server_settings_from_env()
    app.state.telegram_webhook_secret = telegram_webhook_secret
    app.state.telegram_provider_id = telegram_provider_id
    app.state.telegram_model = telegram_model
    app.state.qq_webhook_secret = qq_webhook_secret
    app.state.qq_provider_id = qq_provider_id
    app.state.qq_model = qq_model
    app.state.qq_websocket_enabled = qq_websocket_enabled
    app.state.qq_websocket_runner = None
    app.state.telegram_polling_enabled = telegram_polling_enabled
    app.state.telegram_polling_interval_seconds = telegram_polling_interval_seconds
    app.state.telegram_polling_timeout_seconds = telegram_polling_timeout_seconds
    app.state.telegram_polling_limit = telegram_polling_limit

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(providers.router)
    app.include_router(chat.router)
    app.include_router(agents.router)
    app.include_router(images.router)
    app.include_router(plugins.router)
    app.include_router(channels.router)
    app.include_router(telegram.router)
    app.include_router(qq.router)
    _install_frontend_routes(app, frontend_dist_path)
    return app


def create_app_with_runtime_builder(
    runtime_builder: Callable[[], Awaitable[CyreneAIRuntime]],
    settings: ServerSettings | None = None,
    telegram_webhook_secret: str | None = None,
    telegram_provider_id: str | None = None,
    telegram_model: str | None = None,
    qq_webhook_secret: str | None = None,
    qq_provider_id: str | None = None,
    qq_model: str | None = None,
    qq_websocket_enabled: bool = False,
    telegram_polling_enabled: bool = False,
    telegram_polling_interval_seconds: float = 1.0,
    telegram_polling_timeout_seconds: int = 30,
    telegram_polling_limit: int | None = None,
    request_logging_enabled: bool = True,
    request_id_header: str = DEFAULT_REQUEST_ID_HEADER,
    frontend_dist_path: str | Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = await runtime_builder()
        app.state.runtime = runtime
        _log_plugin_startup_state(runtime)
        polling_runner = _build_telegram_polling_runner(app)
        qq_websocket_runner = _build_qq_websocket_runner(app)
        app.state.telegram_polling_runner = polling_runner
        app.state.qq_websocket_runner = qq_websocket_runner
        if polling_runner is not None:
            polling_runner.start()
        if qq_websocket_runner is not None:
            qq_websocket_runner.start()
        app.state.runtime_ready = True
        try:
            yield
        finally:
            app.state.runtime_ready = False
            if qq_websocket_runner is not None:
                await qq_websocket_runner.stop()
            if polling_runner is not None:
                await polling_runner.stop()
            await runtime.close()

    app = FastAPI(title="CyreneBot API", lifespan=lifespan)
    install_request_logging_middleware(
        app,
        enabled=request_logging_enabled,
        request_id_header=request_id_header,
    )
    app.state.runtime = None
    app.state.runtime_ready = False
    app.state.server_settings = settings or build_server_settings_from_env()
    app.state.telegram_webhook_secret = telegram_webhook_secret
    app.state.telegram_provider_id = telegram_provider_id
    app.state.telegram_model = telegram_model
    app.state.qq_webhook_secret = qq_webhook_secret
    app.state.qq_provider_id = qq_provider_id
    app.state.qq_model = qq_model
    app.state.qq_websocket_enabled = qq_websocket_enabled
    app.state.qq_websocket_runner = None
    app.state.telegram_polling_enabled = telegram_polling_enabled
    app.state.telegram_polling_interval_seconds = telegram_polling_interval_seconds
    app.state.telegram_polling_timeout_seconds = telegram_polling_timeout_seconds
    app.state.telegram_polling_limit = telegram_polling_limit

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(providers.router)
    app.include_router(chat.router)
    app.include_router(agents.router)
    app.include_router(images.router)
    app.include_router(plugins.router)
    app.include_router(channels.router)
    app.include_router(telegram.router)
    app.include_router(qq.router)
    _install_frontend_routes(app, frontend_dist_path)
    return app


def _install_frontend_routes(
    app: FastAPI,
    frontend_dist_path: str | Path | None,
) -> None:
    settings = app.state.server_settings
    if settings.auth_enabled and (
        not settings.admin_username or not settings.admin_password
    ):
        logger.warning(
            "CyreneBot frontend disabled: admin auth is enabled but "
            "CYRENEAI_ADMIN_USERNAME or CYRENEAI_ADMIN_PASSWORD is missing"
        )
        app.state.frontend_dist_path = None
        return

    dist_path = _resolve_frontend_dist_path(frontend_dist_path)
    index_path = dist_path / "index.html"
    login_path = dist_path / "login.html"
    if not index_path.is_file():
        logger.info("CyreneBot frontend disabled: dist not found at %s", dist_path)
        app.state.frontend_dist_path = None
        return

    assets_path = dist_path / "assets"
    if not assets_path.is_dir():
        logger.info("CyreneBot frontend disabled: assets not found at %s", assets_path)
        app.state.frontend_dist_path = None
        return

    favicon_path = dist_path / "favicon.svg"
    icons_path = dist_path / "icons.svg"

    app.mount(
        "/console/assets",
        StaticFiles(directory=assets_path),
        name="frontend_assets",
    )

    @app.get("/console", include_in_schema=False, response_model=None)
    @app.get("/console/", include_in_schema=False, response_model=None)
    async def frontend_index(request: Request) -> Response:
        if not verify_admin_session(request, app.state.server_settings):
            return RedirectResponse("/console/login", status_code=303)
        return FileResponse(index_path)

    if login_path.is_file():

        @app.get("/console/login", include_in_schema=False)
        @app.get("/console/login.html", include_in_schema=False)
        async def frontend_login() -> FileResponse:
            return FileResponse(login_path)

    @app.get("/console/favicon.svg", include_in_schema=False)
    async def frontend_favicon() -> FileResponse:
        return FileResponse(favicon_path)

    @app.get("/console/icons.svg", include_in_schema=False)
    async def frontend_icons() -> FileResponse:
        return FileResponse(icons_path)

    app.state.frontend_dist_path = str(dist_path)
    logger.info("CyreneBot frontend enabled: dist=%s", dist_path)


def _resolve_frontend_dist_path(frontend_dist_path: str | Path | None) -> Path:
    if frontend_dist_path is not None:
        return Path(frontend_dist_path).resolve()
    return (Path(__file__).resolve().parents[3] / "frontend" / "dist").resolve()


def _log_plugin_startup_state(runtime: CyreneAIRuntime) -> None:
    plugin_manager = runtime.plugin_manager
    if plugin_manager is None:
        logger.info("CyreneBot plugins disabled: no plugin manager")
        return

    plugins = plugin_manager.list_plugins()
    commands = plugin_manager.list_commands()
    statuses = plugin_manager.list_statuses()
    plugin_items = [
        f"{plugin.plugin_id}@{plugin.version}" for plugin in plugins if plugin.enabled
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
        "(see DEBUG for command list)" if command_items else "(none)",
    )
    logger.debug(
        "CyreneBot command list: commands=%s",
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


def _build_qq_websocket_runner(app: FastAPI) -> ChannelWebSocketRunner | None:
    if not app.state.qq_websocket_enabled:
        return None
    if not app.state.qq_provider_id or not app.state.qq_model:
        raise RuntimeError("QQ websocket provider_id and model are required")
    registry = app.state.runtime.bot_channel_registry
    if registry is None or not registry.exists("qq"):
        raise RuntimeError("QQ websocket requires a registered qq channel")
    channel = registry.get_channel("qq")
    if not hasattr(channel, "run_websocket"):
        raise RuntimeError("QQ channel does not support websocket updates")
    return ChannelWebSocketRunner(
        runtime=app.state.runtime,
        channel_id="qq",
        provider_id=app.state.qq_provider_id,
        model=app.state.qq_model,
        metadata={
            "source": "qq_websocket",
        },
    )
