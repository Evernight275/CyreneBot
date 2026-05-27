from __future__ import annotations

import json

import pytest

from cyreneAI.adapters.documents import JsonDocumentLoader
from cyreneAI.core.schema.document import Document


def test_json_document_loader_loads_json_array(tmp_path) -> None:
    file_path = tmp_path / "articles.json"
    file_path.write_text(
        json.dumps(
            [
                {
                    "id": "article-1",
                    "text": "alpha",
                    "title": "Alpha",
                    "meta": {"url": "https://example.com/a"},
                },
                {
                    "id": "article-2",
                    "text": "beta",
                    "title": "Beta",
                    "meta": {"url": "https://example.com/b"},
                },
            ]
        ),
        encoding="utf-8",
    )

    documents = JsonDocumentLoader(
        file_path,
        content_field="text",
        id_field="id",
        metadata_fields=["title", "meta.url"],
    ).load()

    assert documents == [
        Document(
            document_id="article-1",
            content="alpha",
            metadata={
                "source": "json",
                "path": file_path.as_posix(),
                "filename": "articles.json",
                "extension": ".json",
                "record_index": 0,
                "title": "Alpha",
                "meta.url": "https://example.com/a",
            },
        ),
        Document(
            document_id="article-2",
            content="beta",
            metadata={
                "source": "json",
                "path": file_path.as_posix(),
                "filename": "articles.json",
                "extension": ".json",
                "record_index": 1,
                "title": "Beta",
                "meta.url": "https://example.com/b",
            },
        ),
    ]


def test_json_document_loader_supports_root_path(tmp_path) -> None:
    file_path = tmp_path / "payload.json"
    file_path.write_text(
        json.dumps(
            {
                "data": {
                    "items": [
                        {
                            "id": "article-1",
                            "body": {"text": "alpha"},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    documents = JsonDocumentLoader(
        file_path,
        content_field="body.text",
        id_field="id",
        root_path=["data", "items"],
    ).load()

    assert len(documents) == 1
    assert documents[0].document_id == "article-1"
    assert documents[0].content == "alpha"


def test_json_document_loader_loads_jsonl(tmp_path) -> None:
    file_path = tmp_path / "articles.jsonl"
    file_path.write_text(
        "\n".join(
            [
                json.dumps({"id": "article-1", "text": "alpha"}),
                "",
                json.dumps({"id": "article-2", "text": "beta"}),
            ]
        ),
        encoding="utf-8",
    )

    documents = JsonDocumentLoader(
        file_path,
        content_field="text",
        id_field="id",
    ).load()

    assert [document.document_id for document in documents] == [
        "article-1",
        "article-2",
    ]
    assert [document.content for document in documents] == ["alpha", "beta"]


def test_json_document_loader_skips_records_without_content(tmp_path) -> None:
    file_path = tmp_path / "articles.json"
    file_path.write_text(
        json.dumps(
            [
                {"id": "article-1", "text": "alpha"},
                {"id": "article-2"},
                {"id": "article-3", "text": ""},
            ]
        ),
        encoding="utf-8",
    )

    documents = JsonDocumentLoader(
        file_path,
        content_field="text",
        id_field="id",
    ).load()

    assert [document.document_id for document in documents] == ["article-1"]


def test_json_document_loader_uses_fallback_document_ids(tmp_path) -> None:
    file_path = tmp_path / "articles.json"
    file_path.write_text(
        json.dumps([{"text": "alpha"}]),
        encoding="utf-8",
    )

    documents = JsonDocumentLoader(file_path, content_field="text").load()

    assert documents[0].document_id == "articles.json:0"


def test_json_document_loader_rejects_oversized_file(tmp_path) -> None:
    file_path = tmp_path / "articles.json"
    file_path.write_text(json.dumps([{"text": "abcdef"}]), encoding="utf-8")

    with pytest.raises(ValueError):
        JsonDocumentLoader(
            file_path,
            content_field="text",
            max_file_bytes=5,
        ).load()


def test_json_document_loader_rejects_too_many_documents(tmp_path) -> None:
    file_path = tmp_path / "articles.json"
    file_path.write_text(
        json.dumps([{"text": "alpha"}, {"text": "beta"}]),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        JsonDocumentLoader(
            file_path,
            content_field="text",
            max_documents=1,
        ).load()


def test_json_document_loader_rejects_missing_path(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        JsonDocumentLoader(
            tmp_path / "missing.json",
            content_field="text",
        ).load()


def test_json_document_loader_rejects_invalid_json_shape(tmp_path) -> None:
    file_path = tmp_path / "payload.json"
    file_path.write_text(json.dumps("invalid"), encoding="utf-8")

    with pytest.raises(ValueError):
        JsonDocumentLoader(file_path, content_field="text").load()


def test_json_document_loader_rejects_invalid_jsonl_line(tmp_path) -> None:
    file_path = tmp_path / "payload.jsonl"
    file_path.write_text(json.dumps(["invalid"]), encoding="utf-8")

    with pytest.raises(ValueError):
        JsonDocumentLoader(file_path, content_field="text").load()
