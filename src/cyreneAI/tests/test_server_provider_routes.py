from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest
from fastapi import HTTPException

from cyreneAI.core.errors.provider import ProviderError
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.server.routes import providers as provider_routes


class _FailingProviderAdminService:
    def _raise(self) -> None:
        raise ProviderError("provider failed")

    def list_catalog(self) -> None:
        self._raise()

    async def list_configs(self) -> None:
        self._raise()

    async def list_statuses(self) -> None:
        self._raise()

    async def inspect(self, provider_id: str) -> None:
        self._raise()

    async def upsert_config(
        self,
        provider_id: str,
        body: ProviderConfig,
    ) -> None:
        self._raise()

    async def delete_config(self, provider_id: str) -> None:
        self._raise()

    async def start(self, provider_id: str) -> None:
        self._raise()

    async def stop(self, provider_id: str) -> None:
        self._raise()

    async def reload(self, provider_id: str) -> None:
        self._raise()

    async def check(self, provider_id: str) -> None:
        self._raise()


_ProviderRouteCall = Callable[[_FailingProviderAdminService], Awaitable[Any]]


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        provider_id="provider-1",
        provider_type=ProviderType.OPENAI_RESPONSES,
        timeout=timedelta(seconds=1),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call_route",
    [
        lambda service: provider_routes.list_provider_catalog(service=service),
        lambda service: provider_routes.list_provider_configs(service=service),
        lambda service: provider_routes.list_provider_statuses(service=service),
        lambda service: provider_routes.inspect_provider(
            "provider-1",
            service=service,
        ),
        lambda service: provider_routes.upsert_provider_config(
            "provider-1",
            _provider_config(),
            service=service,
        ),
        lambda service: provider_routes.delete_provider_config(
            "provider-1",
            service=service,
        ),
        lambda service: provider_routes.start_provider("provider-1", service=service),
        lambda service: provider_routes.stop_provider("provider-1", service=service),
        lambda service: provider_routes.reload_provider(
            "provider-1",
            service=service,
        ),
        lambda service: provider_routes.check_provider("provider-1", service=service),
    ],
)
async def test_provider_admin_routes_map_cyrene_errors_to_http_errors(
    call_route: _ProviderRouteCall,
) -> None:
    service = _FailingProviderAdminService()

    with pytest.raises(HTTPException) as exc_info:
        await call_route(service)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "provider failed"
