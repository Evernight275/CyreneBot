from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from cyreneAI.core.schema.document import Document


class CsvDocumentLoader:
    """
    CSV 文档加载器。
    """

    def __init__(
        self,
        path: str | Path,
        *,
        content_field: str,
        id_field: str | None = None,
        metadata_fields: list[str] | None = None,
        delimiter: str = ",",
        encoding: str = "utf-8",
        max_file_bytes: int = 10_485_760,
        max_documents: int = 1_000,
    ) -> None:
        self._path = Path(path)
        self._content_field = content_field
        self._id_field = id_field
        self._metadata_fields = metadata_fields or []
        self._delimiter = delimiter
        self._encoding = encoding
        self._max_file_bytes = max_file_bytes
        self._max_documents = max_documents

    def load(self) -> list[Document]:
        """
        加载 CSV 文件为 Document。
        """
        if not self._path.exists():
            raise FileNotFoundError(f"Document path does not exist: {self._path}")
        if not self._path.is_file():
            raise ValueError(f"Document path is not a file: {self._path}")

        _validate_file_size(path=self._path, max_file_bytes=self._max_file_bytes)
        documents: list[Document] = []
        with self._path.open("r", encoding=self._encoding, newline="") as file:
            reader = csv.DictReader(file, delimiter=self._delimiter)
            for row_index, row in enumerate(reader):
                document = self._row_to_document(row, row_index=row_index)
                if document is not None:
                    documents.append(document)
                    _validate_document_count(
                        count=len(documents),
                        max_documents=self._max_documents,
                    )
        return documents

    def _row_to_document(
        self,
        row: dict[str, Any],
        *,
        row_index: int,
    ) -> Document | None:
        content = row.get(self._content_field)
        if content is None:
            return None
        content_text = str(content)
        if not content_text:
            return None

        document_id = _document_id(
            row=row,
            id_field=self._id_field,
            fallback=f"{self._path.name}:{row_index}",
        )
        return Document(
            document_id=document_id,
            content=content_text,
            metadata={
                "source": "csv",
                "path": self._path.as_posix(),
                "filename": self._path.name,
                "extension": self._path.suffix.lower(),
                "row_index": row_index,
                **_metadata_from_fields(row, self._metadata_fields),
            },
        )


def _document_id(
    *,
    row: dict[str, Any],
    id_field: str | None,
    fallback: str,
) -> str:
    if id_field is None:
        return fallback
    value = row.get(id_field)
    if value is None or value == "":
        return fallback
    return str(value)


def _metadata_from_fields(
    row: dict[str, Any],
    fields: list[str],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for field in fields:
        value = row.get(field)
        if value is not None and value != "":
            metadata[field] = value
    return metadata


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
