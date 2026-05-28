from __future__ import annotations

from fastapi import FastAPI

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.server.config import ServerSettings, build_server_settings_from_env
from cyreneAI.server.routes import auth, channels, chat, health, images, providers


def create_app(
    runtime: CyreneAIRuntime,
    settings: ServerSettings | None = None,
) -> FastAPI:
    app = FastAPI(title="CyreneBot API")
    app.state.runtime = runtime
    app.state.server_settings = settings or build_server_settings_from_env()

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(providers.router)
    app.include_router(chat.router)
    app.include_router(images.router)
    app.include_router(channels.router)
    return app
