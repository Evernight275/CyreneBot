from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cyreneAI.core.schema.document import Document


class JsonDocumentLoader:
    """
    JSON / JSONL 文档加载器。
    """

    def __init__(
        self,
        path: str | Path,
        *,
        content_field: str,
        id_field: str | None = None,
        metadata_fields: list[str] | None = None,
        root_path: list[str | int] | None = None,
        encoding: str = "utf-8",
        max_file_bytes: int = 10_485_760,
        max_documents: int = 1_000,
    ) -> None:
        self._path = Path(path)
        self._content_field = content_field
        self._id_field = id_field
        self._metadata_fields = metadata_fields or []
        self._root_path = root_path or []
        self._encoding = encoding
        self._max_file_bytes = max_file_bytes
        self._max_documents = max_documents

    def load(self) -> list[Document]:
        """
        加载 JSON / JSONL 文件为 Document。
        """
        if not self._path.exists():
            raise FileNotFoundError(f"Document path does not exist: {self._path}")
        if not self._path.is_file():
            raise ValueError(f"Document path is not a file: {self._path}")

        _validate_file_size(path=self._path, max_file_bytes=self._max_file_bytes)
        records = (
            self._load_jsonl_records()
            if self._path.suffix.lower() == ".jsonl"
            else self._load_json_records()
        )
        documents: list[Document] = []
        for index, record in enumerate(records):
            document = self._record_to_document(record, index=index)
            if document is not None:
                documents.append(document)
                _validate_document_count(
                    count=len(documents),
                    max_documents=self._max_documents,
                )
        return documents

    def _load_json_records(self) -> list[dict[str, Any]]:
        payload = json.loads(_read_text(self._path, encoding=self._encoding))
        payload = _resolve_root_path(payload, self._root_path)
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return [
                item
                for item in payload
                if isinstance(item, dict)
            ]
        raise ValueError("JSON document payload must be an object or list of objects")

    def _load_jsonl_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            _read_text(self._path, encoding=self._encoding).splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"JSONL line {line_number} must be an object")
            records.append(record)
        return records

    def _record_to_document(
        self,
        record: dict[str, Any],
        *,
        index: int,
    ) -> Document | None:
        content = _get_field(record, self._content_field)
        if content is None:
            return None
        content_text = str(content)
        if not content_text:
            return None

        document_id = _document_id(
            record=record,
            id_field=self._id_field,
            fallback=f"{self._path.name}:{index}",
        )
        return Document(
            document_id=document_id,
            content=content_text,
            metadata={
                "source": "json",
                "path": self._path.as_posix(),
                "filename": self._path.name,
                "extension": self._path.suffix.lower(),
                "record_index": index,
                **_metadata_from_fields(record, self._metadata_fields),
            },
        )


def _resolve_root_path(payload: Any, root_path: list[str | int]) -> Any:
    current = payload
    for part in root_path:
        if isinstance(current, dict) and isinstance(part, str):
            current = current[part]
            continue
        if isinstance(current, list) and isinstance(part, int):
            current = current[part]
            continue
        raise ValueError(f"Cannot resolve JSON root path at {part!r}")
    return current


def _get_field(record: dict[str, Any], field: str) -> Any:
    current: Any = record
    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _document_id(
    *,
    record: dict[str, Any],
    id_field: str | None,
    fallback: str,
) -> str:
    if id_field is None:
        return fallback
    value = _get_field(record, id_field)
    if value is None:
        return fallback
    return str(value)


def _metadata_from_fields(
    record: dict[str, Any],
    fields: list[str],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for field in fields:
        value = _get_field(record, field)
        if value is not None:
            metadata[field] = value
    return metadata


def _read_text(path: Path, *, encoding: str) -> str:
    return path.read_text(encoding=encoding)


def _validate_file_size(*, path: Path, max_file_bytes: int) -> None:
    if max_file_bytes < 0:
        return
    if path.stat().st_size > max_file_bytes:
        raise ValueError(f"Document file exceeds maximum size: {path}")


def _validate_document_count(*, count: int, max_documents: int) -> None:
    if max_documents < 0:
        return
    if count > max_documents:
        raise ValueError("Document load exceeded maximum document count")
