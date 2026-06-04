from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from cyreneAI.core.errors.plugin import PluginInputError


class FileSystemPluginStorage:
    """
    文件系统插件托管存储。
    """

    def __init__(self, root_path: str | Path) -> None:
        self._root_path = Path(root_path)
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def namespace(self, plugin_id: str) -> "FileSystemPluginStorageNamespace":
        return FileSystemPluginStorageNamespace(
            root_path=self._root_path,
            namespace=_safe_name(plugin_id, label="plugin_id"),
            locks=self._locks,
        )

    async def close(self) -> None:
        self._locks.clear()


class FileSystemPluginStorageNamespace:
    """
    单个插件的文件系统存储命名空间。
    """

    def __init__(
        self,
        *,
        root_path: Path,
        namespace: str,
        locks: dict[tuple[str, str], asyncio.Lock],
    ) -> None:
        self._root_path = root_path
        self._namespace = namespace
        self._locks = locks

    async def get(self, key: str, default: Any = None) -> Any:
        key_name = _safe_name(key, label="storage key")
        async with self._lock(key_name):
            return self._read(key_name, default)

    async def set(self, key: str, value: Any) -> None:
        key_name = _safe_name(key, label="storage key")
        async with self._lock(key_name):
            self._write(key_name, value)

    async def delete(self, key: str) -> None:
        key_name = _safe_name(key, label="storage key")
        async with self._lock(key_name):
            self._path(key_name).unlink(missing_ok=True)

    async def list_keys(self) -> list[str]:
        namespace_path = self._root_path / self._namespace
        if not namespace_path.exists():
            return []
        return sorted(
            path.stem for path in namespace_path.glob("*.json") if path.is_file()
        )

    async def update(
        self,
        key: str,
        updater: Callable[[Any], Any | Awaitable[Any]],
        default: Any = None,
    ) -> Any:
        key_name = _safe_name(key, label="storage key")
        async with self._lock(key_name):
            current = self._read(key_name, default)
            updated = updater(current)
            if isawaitable(updated):
                updated = await updated
            self._write(key_name, updated)
            return updated

    def _read(self, key_name: str, default: Any) -> Any:
        path = self._path(key_name)
        if not path.exists():
            return default

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except JSONDecodeError as exc:
            raise PluginInputError(
                f"Plugin storage file {path} must contain valid JSON",
                cause=exc,
            ) from exc

    def _write(self, key_name: str, value: Any) -> None:
        path = self._path(key_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        try:
            payload = json.dumps(value, ensure_ascii=False, indent=2)
        except TypeError as exc:
            raise PluginInputError(
                f"Plugin storage key {key_name} must be JSON serializable",
                cause=exc,
            ) from exc
        temporary_path.write_text(payload, encoding="utf-8")
        temporary_path.replace(path)

    def _path(self, key_name: str) -> Path:
        return self._root_path / self._namespace / f"{key_name}.json"

    def _lock(self, key_name: str) -> asyncio.Lock:
        return self._locks.setdefault((self._namespace, key_name), asyncio.Lock())


def _safe_name(value: str, *, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise PluginInputError(f"Plugin {label} cannot be empty")
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", normalized)
