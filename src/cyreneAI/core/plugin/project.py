from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError as PydanticValidationError

from cyreneAI.core.errors.plugin import PluginInputError
from cyreneAI.core.schema.plugin import (
    PluginIsolationMode,
    PluginManifest,
    PluginSignatureStatus,
    PluginSourceInfo,
    PluginSourceType,
)

PLUGIN_SIGNATURE_FILENAME = ".cyreneai-plugin-signature.json"


def resolve_plugin_project_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_file():
        if candidate.name != "plugin.json":
            raise PluginInputError(f"plugin file {candidate} must be named plugin.json")
        return candidate.parent
    if not candidate.exists():
        raise PluginInputError(f"plugin path {candidate} does not exist")
    if not candidate.is_dir():
        raise PluginInputError(f"plugin path {candidate} must be a directory")
    if not (candidate / "plugin.json").is_file():
        raise PluginInputError(f"plugin path {candidate} must contain plugin.json")
    return candidate


def load_plugin_manifest(path: Path) -> PluginManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise PluginInputError(
            f"plugin manifest {path} must contain valid JSON",
            cause=exc,
        ) from exc

    try:
        return PluginManifest.model_validate(payload)
    except PydanticValidationError as exc:
        raise PluginInputError(
            f"plugin manifest {path} contains invalid plugin metadata",
            cause=exc,
        ) from exc


def resolve_plugin_entrypoint(
    project_path: Path,
    manifest: PluginManifest,
) -> Path:
    project_root = project_path.resolve()
    entrypoint = (project_path / manifest.entrypoint).resolve()
    if entrypoint != project_root and not entrypoint.is_relative_to(project_root):
        raise PluginInputError(
            f"plugin {manifest.plugin_id} entrypoint cannot escape plugin project"
        )
    if not entrypoint.is_file():
        raise PluginInputError(
            f"plugin {manifest.plugin_id} entrypoint {entrypoint} does not exist"
        )
    return entrypoint


def plugin_project_content_hash(project_path: Path) -> str:
    project_root = project_path.resolve()
    digest = hashlib.sha256()
    for path in hashable_plugin_project_files(project_root):
        relative_path = path.relative_to(project_root).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def hashable_plugin_project_files(project_path: Path) -> list[Path]:
    project_root = project_path.resolve()
    ignored_suffixes = {
        ".pyc",
        ".pyo",
    }
    files: list[Path] = []
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts:
            continue
        if path.name == PLUGIN_SIGNATURE_FILENAME or path.suffix in ignored_suffixes:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(project_root).as_posix())


def validate_plugin_project_signature(
    project_path: Path,
    content_hash: str | None = None,
) -> dict[str, Any]:
    project_root = project_path.resolve()
    resolved_content_hash = content_hash or plugin_project_content_hash(project_root)
    signature_path = project_root / PLUGIN_SIGNATURE_FILENAME
    if not signature_path.is_file():
        return {
            "status": PluginSignatureStatus.UNSIGNED,
            "content_hash": resolved_content_hash,
        }

    try:
        payload = json.loads(signature_path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise PluginInputError(
            f"plugin signature {signature_path} must contain valid JSON",
            cause=exc,
        ) from exc

    algorithm = str(payload.get("algorithm", "")).lower()
    expected_hash = payload.get("content_hash")
    signed_by = payload.get("signed_by")
    base: dict[str, Any] = {
        "path": str(signature_path.resolve()),
        "content_hash": resolved_content_hash,
        "signed_by": signed_by if isinstance(signed_by, str) else None,
    }
    if algorithm != "sha256":
        return {
            **base,
            "status": PluginSignatureStatus.UNSUPPORTED,
            "error": f"unsupported signature algorithm: {algorithm or '(missing)'}",
        }
    if expected_hash != resolved_content_hash:
        return {
            **base,
            "status": PluginSignatureStatus.INVALID,
            "error": "signature content_hash does not match plugin content",
        }
    return {
        **base,
        "status": PluginSignatureStatus.VALID,
    }


def build_filesystem_plugin_source_info(
    project_path: Path,
    manifest: PluginManifest,
    entrypoint: Path,
    *,
    loaded_at: datetime | None = None,
) -> PluginSourceInfo:
    project_root = project_path.resolve()
    content_hash = plugin_project_content_hash(project_root)
    signature = validate_plugin_project_signature(project_root, content_hash)
    return PluginSourceInfo(
        plugin_id=manifest.plugin_id,
        source_type=PluginSourceType.FILESYSTEM,
        path=str(project_root),
        manifest_path=str((project_path / "plugin.json").resolve()),
        entrypoint=str(entrypoint),
        version=manifest.version,
        content_hash=content_hash,
        loaded_at=loaded_at or datetime.now(UTC),
        isolation_mode=plugin_manifest_isolation_mode(manifest),
        signature_status=signature["status"],
        signature_path=signature.get("path"),
        signed_by=signature.get("signed_by"),
        signature_error=signature.get("error"),
    )


def plugin_manifest_isolation_mode(
    manifest: PluginManifest,
) -> PluginIsolationMode:
    value: object = manifest.metadata.get("isolation")
    if isinstance(value, dict):
        value = cast(object, value.get("mode"))
    if isinstance(value, str):
        with suppress(ValueError):
            return PluginIsolationMode(value)
    return PluginIsolationMode.IN_PROCESS


__all__ = [
    "PLUGIN_SIGNATURE_FILENAME",
    "build_filesystem_plugin_source_info",
    "hashable_plugin_project_files",
    "load_plugin_manifest",
    "plugin_manifest_isolation_mode",
    "plugin_project_content_hash",
    "resolve_plugin_entrypoint",
    "resolve_plugin_project_path",
    "validate_plugin_project_signature",
]
