from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from cyreneAI.core.errors.base import NotFoundError
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType
from cyreneAI.infra.adapters.provider_config_stores import FileSystemProviderConfigStore


def test_filesystem_provider_config_store_round_trips_configs(tmp_path) -> None:
    async def run() -> None:
        store = FileSystemProviderConfigStore(tmp_path / "providers.json")
        config = ProviderConfig(
            provider_id="provider-1",
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            api_key="secret",
            base_url="https://example.test",
            timeout=timedelta(seconds=3),
            metadata={"vendor": "example"},
        )

        await store.upsert_config(config)
        loaded = await store.get_config("provider-1")
        listed = await store.list_configs()

        assert loaded == config
        assert listed == [config]

    asyncio.run(run())


def test_filesystem_provider_config_store_deletes_configs(tmp_path) -> None:
    async def run() -> None:
        store = FileSystemProviderConfigStore(tmp_path / "providers.json")
        config = ProviderConfig(
            provider_id="provider-1",
            provider_type=ProviderType.OPENAI_COMPATIBLE,
        )

        await store.upsert_config(config)
        await store.delete_config("provider-1")

        assert await store.list_configs() == []
        with pytest.raises(NotFoundError):
            await store.get_config("provider-1")

    asyncio.run(run())
