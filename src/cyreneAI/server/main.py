from __future__ import annotations

import asyncio

from cyreneAI.application.bootstrap import build_cyrene_ai_runtime
from cyreneAI.server.app import create_app
from cyreneAI.server.config import build_provider_configs_from_env


app = create_app(
    asyncio.run(
        build_cyrene_ai_runtime(
            provider_configs=build_provider_configs_from_env(),
        )
    )
)
