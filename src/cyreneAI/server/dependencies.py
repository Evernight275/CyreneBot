from __future__ import annotations

from fastapi import Request

from cyreneAI.application.runtime import CyreneAIRuntime


def get_runtime(request: Request) -> CyreneAIRuntime:
    return request.app.state.runtime
