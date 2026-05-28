from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Response

from cyreneAI.server.auth import (
    clear_admin_session_cookie,
    set_admin_session_cookie,
    verify_admin_password,
)
from cyreneAI.server.config import ServerSettings
from cyreneAI.server.dependencies import get_server_settings, require_admin

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(
    response: Response,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    settings: ServerSettings = Depends(get_server_settings),
) -> dict[str, bool]:
    verify_admin_password(
        username=username,
        password=password,
        settings=settings,
    )
    set_admin_session_cookie(response, settings)
    return {"authenticated": True}


@router.post("/logout", dependencies=[Depends(require_admin)])
async def logout(
    response: Response,
    settings: ServerSettings = Depends(get_server_settings),
) -> dict[str, bool]:
    clear_admin_session_cookie(response, settings)
    return {"authenticated": False}
