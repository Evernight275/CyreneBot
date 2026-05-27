from __future__ import annotations

from fastapi import FastAPI

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.server.routes import chat, health, images, providers


def create_app(runtime: CyreneAIRuntime) -> FastAPI:
    app = FastAPI(title="CyreneBot API")
    app.state.runtime = runtime

    app.include_router(health.router)
    app.include_router(providers.router)
    app.include_router(chat.router)
    app.include_router(images.router)
    return app
