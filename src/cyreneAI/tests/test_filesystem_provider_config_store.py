from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest

from cyreneAI.core.errors.base import NotFoundError
from cyreneAI.core.schema.provider import ProviderConfig, ProviderModel, ProviderType
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


def test_filesystem_provider_config_store_loads_legacy_string_models(tmp_path) -> None:
    async def run() -> None:
        store_path = tmp_path / "providers.json"
        store_path.write_text(
            json.dumps(
                {
                    "provider-1": {
                        "provider_id": "provider-1",
                        "provider_type": "openai_compatible",
                        "models": [" custom-model ", "custom-model", ""],
                    }
                }
            ),
            encoding="utf-8",
        )
        store = FileSystemProviderConfigStore(store_path)

        loaded = await store.get_config("provider-1")

        assert loaded.models == [ProviderModel(model_id="custom-model")]

    asyncio.run(run())
