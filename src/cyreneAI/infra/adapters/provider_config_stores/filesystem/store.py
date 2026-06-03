from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError as PydanticValidationError

from cyreneAI.core.errors.base import NotFoundError, StateError
from cyreneAI.core.schema.provider import ProviderConfig


class FileSystemProviderConfigStore:
    """
    JSON 文件 provider 配置存储。
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    async def list_configs(self) -> list[ProviderConfig]:
        data = self._load()
        return [
            ProviderConfig.model_validate(item)
            for item in data.values()
        ]

    async def get_config(self, provider_id: str) -> ProviderConfig:
        data = self._load()
        item = data.get(provider_id)
        if item is None:
            raise NotFoundError(f"Provider config not found: {provider_id}")
        return ProviderConfig.model_validate(item)

    async def upsert_config(self, config: ProviderConfig) -> ProviderConfig:
        data = self._load()
        data[config.provider_id] = cast(
            dict[str, Any],
            config.model_dump(mode="json"),
        )
        self._save(data)
        return config

    async def delete_config(self, provider_id: str) -> None:
        data = self._load()
        if provider_id not in data:
            raise NotFoundError(f"Provider config not found: {provider_id}")
        data.pop(provider_id)
        self._save(data)

    async def close(self) -> None:
        return None

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError(
                f"Failed to load provider config store: {self._path}",
                cause=exc,
            ) from exc
        if not isinstance(raw, dict):
            raise StateError("Provider config store must contain a JSON object")

        data: dict[str, dict[str, Any]] = {}
        try:
            for provider_id, item in cast(dict[str, Any], raw).items():
                if not isinstance(provider_id, str) or not isinstance(item, dict):
                    raise StateError("Provider config store entries must be objects")
                config = ProviderConfig.model_validate(item)
                if config.provider_id != provider_id:
                    raise StateError(
                        "Provider config store key must match provider_id"
                    )
                data[provider_id] = cast(dict[str, Any], item)
        except PydanticValidationError as exc:
            raise StateError("Provider config store contains invalid config", cause=exc) from exc
        return data

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            raise StateError(
                f"Failed to save provider config store: {self._path}",
                cause=exc,
            ) from exc
