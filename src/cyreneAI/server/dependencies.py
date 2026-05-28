from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from cyreneAI.application.runtime import CyreneAIRuntime
from cyreneAI.server.auth import verify_admin_credentials, verify_admin_session
from cyreneAI.server.config import ServerSettings


_admin_basic = HTTPBasic(auto_error=False)


def get_runtime(request: Request) -> CyreneAIRuntime:
    return request.app.state.runtime


def get_server_settings(request: Request) -> ServerSettings:
    return request.app.state.server_settings


def require_admin(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_admin_basic)],
    settings: ServerSettings = Depends(get_server_settings),
) -> None:
    if verify_admin_session(request, settings):
        return
    verify_admin_credentials(credentials, settings)
