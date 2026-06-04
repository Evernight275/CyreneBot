from __future__ import annotations

import time
from typing import Any, cast

import httpx

from cyreneAI.core.errors.bot import BotConfigurationError
from cyreneAI.infra.adapters.channels.qq.errors import QQBotAPIError, raise_qq_error


class QQBotClient:
    """
    Minimal QQ Bot API client.
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        app_id: str | None = None,
        app_secret: str | None = None,
        base_url: str = "https://api.sgroup.qq.com",
        token_url: str = "https://bots.qq.com/app/getAppAccessToken",
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token and not (app_id and app_secret):
            raise BotConfigurationError("QQ bot token or app_id/app_secret is required")
        self._token = token
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = base_url.rstrip("/")
        self._token_url = token_url
        self._timeout = timeout
        self._client = client
        self._access_token: str | None = token
        self._access_token_expires_at = 0.0

    async def send_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Send a text message to the route encoded by the mapper.
        """
        route = payload.get("_route")
        route_id = payload.get("_route_id")
        if not isinstance(route, str) or not isinstance(route_id, str):
            raise QQBotAPIError("QQ send payload must include _route and _route_id")
        request_payload = {
            key: value for key, value in payload.items() if not key.startswith("_")
        }
        return await self.request(
            _send_message_path(route=route, route_id=route_id),
            request_payload,
        )

    async def download_attachment(
        self,
        url: str,
        *,
        max_bytes: int = 8 * 1024 * 1024,
    ) -> tuple[bytes, str | None]:
        """
        Download a QQ attachment URL with bot credentials.
        """
        try:
            response = await self._download(url)
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    parsed_content_length = int(content_length)
                except ValueError:
                    parsed_content_length = None
                if (
                    parsed_content_length is not None
                    and parsed_content_length > max_bytes
                ):
                    raise QQBotAPIError("QQ attachment exceeds maximum download size")

            data = response.content
            if len(data) > max_bytes:
                raise QQBotAPIError("QQ attachment exceeds maximum download size")
            return data, response.headers.get("content-type")
        except Exception as exc:
            raise_qq_error(exc)

    async def request(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        POST a request to the QQ API.
        """
        try:
            response = await self._request(path, payload or {})
            body = _parse_response_body(response)
            if response.status_code >= 400:
                response_body = body if isinstance(body, dict) else {"result": body}
                raise QQBotAPIError(
                    _qq_status_error_message(
                        response.status_code,
                        response_body,
                        path=path,
                    ),
                    error_code=response.status_code,
                    payload=cast(dict[str, Any], response_body),
                )
            if not isinstance(body, dict):
                return {"result": body}
            response_body = cast(dict[str, Any], body)
            code = response_body.get("code")
            if code not in {None, 0, "0"}:
                raise QQBotAPIError(
                    str(response_body.get("message") or "QQ request failed"),
                    error_code=cast(int | str | None, code),
                    payload=response_body,
                )
            return response_body
        except Exception as exc:
            raise_qq_error(exc)

    async def close(self) -> None:
        """
        Close the owned HTTP client, if any.
        """
        if self._client is not None:
            await self._client.aclose()

    async def _request(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        url = f"{self._base_url}/{path.lstrip('/')}"
        access_token = await self._get_access_token()
        headers = {
            "Authorization": f"QQBot {access_token}",
        }
        if self._client is not None:
            return await self._client.request(
                "POST",
                url,
                json=payload,
                headers=headers,
            )

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.request(
                "POST",
                url,
                json=payload,
                headers=headers,
            )

    async def _download(self, url: str) -> httpx.Response:
        access_token = await self._get_access_token()
        headers = {
            "Authorization": f"QQBot {access_token}",
        }
        if self._client is not None:
            return await self._client.request(
                "GET",
                url,
                headers=headers,
            )

        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
        ) as client:
            return await client.request(
                "GET",
                url,
                headers=headers,
            )

    async def _get_access_token(self) -> str:
        if self._token:
            return self._token
        if (
            self._access_token is not None
            and time.monotonic() < self._access_token_expires_at
        ):
            return self._access_token
        if not self._app_id or not self._app_secret:
            raise BotConfigurationError(
                "QQ app_id/app_secret is required to refresh access token"
            )

        payload = {
            "appId": self._app_id,
            "clientSecret": self._app_secret,
        }
        if self._client is not None:
            response = await self._client.request(
                "POST",
                self._token_url,
                json=payload,
            )
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    "POST",
                    self._token_url,
                    json=payload,
                )
        response.raise_for_status()
        body = _parse_response_body(response)
        if not isinstance(body, dict):
            raise QQBotAPIError("QQ access token response body must be an object")
        response_body = cast(dict[str, Any], body)
        access_token = response_body.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise QQBotAPIError("QQ access token response must include access_token")
        expires_in = response_body.get("expires_in")
        ttl = expires_in if isinstance(expires_in, int) else 3600
        self._access_token = access_token
        self._access_token_expires_at = time.monotonic() + max(ttl - 60, 1)
        return access_token


def _send_message_path(*, route: str, route_id: str) -> str:
    if route == "channel":
        return f"/channels/{route_id}/messages"
    if route == "dm":
        return f"/dms/{route_id}/messages"
    if route == "group":
        return f"/v2/groups/{route_id}/messages"
    if route == "user":
        return f"/v2/users/{route_id}/messages"
    raise QQBotAPIError(f"Unsupported QQ send route: {route}")


def _parse_response_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise QQBotAPIError("QQ response body must be JSON") from exc


def _qq_status_error_message(
    status_code: int,
    response_body: dict[str, Any],
    *,
    path: str,
) -> str:
    detail = (
        response_body.get("message")
        or response_body.get("msg")
        or response_body.get("error")
        or response_body.get("errmsg")
        or "QQ request failed"
    )
    code = response_body.get("code")
    prefix = f"QQ request failed with status {status_code}: path={path}"
    if code is None:
        return f"{prefix} message={detail}"
    return f"{prefix} code={code} message={detail}"
