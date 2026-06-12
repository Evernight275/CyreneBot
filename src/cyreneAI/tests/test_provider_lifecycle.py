from __future__ import annotations

import asyncio

import pytest

from cyreneAI.core.errors.base import ConflictError, NotFoundError, StateError
from cyreneAI.core.errors.provider import ProviderError, ProviderNotFoundError
from cyreneAI.core.provider.factory import ProviderFactory
from cyreneAI.core.provider.manager import ProviderManager
from cyreneAI.core.provider.registry import ProviderRegistry
from cyreneAI.core.schema.provider import (
    ProviderCapability,
    ProviderConfig,
    ProviderInfo,
    ProviderModel,
    ProviderType,
)


def _config(
    provider_id: str = "provider-1",
    provider_type: ProviderType = ProviderType.OPENAI_COMPATIBLE,
) -> ProviderConfig:
    return ProviderConfig(
        provider_id=provider_id,
        provider_type=provider_type,
        api_key="test-key",
    )


def _info(
    provider_type: ProviderType = ProviderType.OPENAI_COMPATIBLE,
    *,
    capabilities: list[ProviderCapability] | None = None,
    models: list[str] | None = None,
) -> ProviderInfo:
    return ProviderInfo(
        provider_type=provider_type,
        name=f"{provider_type} test",
        description="test provider",
        models=models,
        capabilities=capabilities,
    )


class _FakeProviderInstance:
    def __init__(
        self,
        config: ProviderConfig,
        *,
        close_error: Exception | None = None,
    ) -> None:
        self.config = config
        self.info = _info(config.provider_type)
        self.closed = False
        self.close_error = close_error

    async def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class _FakeModelListingProviderInstance(_FakeProviderInstance):
    def __init__(
        self,
        config: ProviderConfig,
        *,
        models: list[ProviderModel] | None = None,
        list_error: Exception | None = None,
    ) -> None:
        super().__init__(config)
        self.info = _info(config.provider_type, models=["catalog-model"])
        self.models = models or []
        self.list_error = list_error

    async def list_models(self) -> list[ProviderModel]:
        if self.list_error is not None:
            raise self.list_error
        return self.models


async def _build_instance(config: ProviderConfig) -> _FakeProviderInstance:
    return _FakeProviderInstance(config)


def test_provider_registry_gets_lists_filters_and_unregisters() -> None:
    registry = ProviderRegistry()
    chat_info = _info(
        ProviderType.OPENAI_COMPATIBLE,
        capabilities=[ProviderCapability.CHAT],
    )
    image_info = _info(
        ProviderType.GOOGLE,
        capabilities=[ProviderCapability.IMAGE],
    )

    registry.register_provider(chat_info)
    registry.register_provider(image_info)

    assert registry.get(ProviderType.OPENAI_COMPATIBLE) is chat_info
    assert registry.get_all() == [chat_info, image_info]
    assert registry.list_by_capability(ProviderCapability.CHAT) == [chat_info]
    assert registry.list_by_capability(ProviderCapability.TTS) == []

    registry.unregister_provider(ProviderType.GOOGLE)

    assert not registry.exists(ProviderType.GOOGLE)


def test_provider_registry_raises_for_missing_provider() -> None:
    registry = ProviderRegistry()

    with pytest.raises(ProviderNotFoundError):
        registry.get(ProviderType.OPENAI_COMPATIBLE)

    with pytest.raises(ProviderNotFoundError):
        registry.unregister_provider(ProviderType.OPENAI_COMPATIBLE)


def test_provider_factory_creates_and_unregisters_builders() -> None:
    async def run() -> None:
        factory = ProviderFactory()
        config = _config()

        factory.register(ProviderType.OPENAI_COMPATIBLE, _build_instance)

        assert factory.exists(ProviderType.OPENAI_COMPATIBLE)
        assert (await factory.create(config)).config is config

        factory.unregister(ProviderType.OPENAI_COMPATIBLE)

        assert not factory.exists(ProviderType.OPENAI_COMPATIBLE)

    asyncio.run(run())


def test_provider_factory_raises_for_missing_builder() -> None:
    async def run() -> None:
        factory = ProviderFactory()

        with pytest.raises(ProviderNotFoundError):
            factory.unregister(ProviderType.OPENAI_COMPATIBLE)

        with pytest.raises(ProviderNotFoundError):
            await factory.create(_config())

    asyncio.run(run())


def test_provider_manager_rejects_duplicate_add_and_missing_lookup() -> None:
    async def run() -> None:
        factory = ProviderFactory()
        factory.register(ProviderType.OPENAI_COMPATIBLE, _build_instance)
        manager = ProviderManager(factory)
        config = _config()

        await manager.add(config)

        with pytest.raises(ConflictError):
            await manager.add(config)

        with pytest.raises(NotFoundError):
            manager.get("missing")

        with pytest.raises(NotFoundError):
            await manager.remove("missing")

        await manager.close_all()

    asyncio.run(run())


def test_provider_manager_lists_removes_and_reloads_instances() -> None:
    async def run() -> None:
        factory = ProviderFactory()
        factory.register(ProviderType.OPENAI_COMPATIBLE, _build_instance)
        manager = ProviderManager(factory)
        config = _config()

        first = await manager.add(config)

        assert manager.get("provider-1") is first
        assert manager.list_running() == [first.info]

        second = await manager.reload(config)

        assert second is not first
        assert first.closed is True
        assert manager.get("provider-1") is second

        await manager.remove("provider-1")

        assert second.closed is True
        assert not manager.exists("provider-1")

    asyncio.run(run())


def test_provider_manager_close_all_collects_close_errors() -> None:
    async def run() -> None:
        failure = RuntimeError("close failed")

        async def build(config: ProviderConfig) -> _FakeProviderInstance:
            return _FakeProviderInstance(config, close_error=failure)

        factory = ProviderFactory()
        factory.register(ProviderType.OPENAI_COMPATIBLE, build)
        manager = ProviderManager(factory)

        await manager.add(_config())

        with pytest.raises(StateError) as caught:
            await manager.close_all()

        assert caught.value.cause is failure
        assert not manager.exists("provider-1")

    asyncio.run(run())


def test_provider_manager_lists_models_from_instance() -> None:
    async def run() -> None:
        async def build(config: ProviderConfig) -> _FakeModelListingProviderInstance:
            return _FakeModelListingProviderInstance(
                config,
                models=[ProviderModel(model_id="runtime-model")],
            )

        factory = ProviderFactory()
        factory.register(ProviderType.OPENAI_COMPATIBLE, build)
        manager = ProviderManager(factory)
        await manager.add(_config())

        assert await manager.list_models("provider-1") == [
            ProviderModel(model_id="runtime-model")
        ]

    asyncio.run(run())


def test_provider_manager_falls_back_to_catalog_models_when_runtime_models_empty() -> (
    None
):
    async def run() -> None:
        async def build(config: ProviderConfig) -> _FakeModelListingProviderInstance:
            return _FakeModelListingProviderInstance(config)

        factory = ProviderFactory()
        factory.register(ProviderType.OPENAI_COMPATIBLE, build)
        manager = ProviderManager(factory)
        await manager.add(_config())

        assert await manager.list_models("provider-1") == [
            ProviderModel(model_id="catalog-model")
        ]

    asyncio.run(run())


def test_provider_manager_propagates_runtime_model_listing_errors() -> None:
    async def run() -> None:
        failure = ProviderError("model listing failed")

        async def build(config: ProviderConfig) -> _FakeModelListingProviderInstance:
            return _FakeModelListingProviderInstance(
                config.model_copy(
                    update={"models": [ProviderModel(model_id="custom-model")]}
                ),
                list_error=failure,
            )

        factory = ProviderFactory()
        factory.register(ProviderType.OPENAI_COMPATIBLE, build)
        manager = ProviderManager(factory)
        await manager.add(_config())

        with pytest.raises(ProviderError) as caught:
            await manager.list_models("provider-1")

        assert caught.value is failure

    asyncio.run(run())


def test_provider_manager_falls_back_to_config_models_when_runtime_models_empty() -> (
    None
):
    async def run() -> None:
        async def build(config: ProviderConfig) -> _FakeModelListingProviderInstance:
            return _FakeModelListingProviderInstance(config)

        factory = ProviderFactory()
        factory.register(ProviderType.OPENAI_COMPATIBLE, build)
        manager = ProviderManager(factory)
        await manager.add(
            _config().model_copy(
                update={
                    "models": [
                        ProviderModel(model_id="custom-model"),
                        ProviderModel(model_id=" custom-model "),
                        ProviderModel(model_id=""),
                    ],
                    "metadata": {"model": "metadata-model"},
                }
            )
        )

        assert await manager.list_models("provider-1") == [
            ProviderModel(model_id="custom-model"),
            ProviderModel(model_id="metadata-model"),
        ]

    asyncio.run(run())
