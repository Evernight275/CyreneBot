from __future__ import annotations

import pytest

from cyreneAI.adapters.documents import CsvDocumentLoader
from cyreneAI.core.schema.document import Document


def test_csv_document_loader_loads_rows(tmp_path) -> None:
    file_path = tmp_path / "articles.csv"
    file_path.write_text(
        "id,text,title,url\n"
        "article-1,alpha,Alpha,https://example.com/a\n"
        "article-2,beta,Beta,https://example.com/b\n",
        encoding="utf-8",
    )

    documents = CsvDocumentLoader(
        file_path,
        content_field="text",
        id_field="id",
        metadata_fields=["title", "url"],
    ).load()

    assert documents == [
        Document(
            document_id="article-1",
            content="alpha",
            metadata={
                "source": "csv",
                "path": file_path.as_posix(),
                "filename": "articles.csv",
                "extension": ".csv",
                "row_index": 0,
                "title": "Alpha",
                "url": "https://example.com/a",
            },
        ),
        Document(
            document_id="article-2",
            content="beta",
            metadata={
                "source": "csv",
                "path": file_path.as_posix(),
                "filename": "articles.csv",
                "extension": ".csv",
                "row_index": 1,
                "title": "Beta",
                "url": "https://example.com/b",
            },
        ),
    ]


def test_csv_document_loader_skips_rows_without_content(tmp_path) -> None:
    file_path = tmp_path / "articles.csv"
    file_path.write_text(
        "id,text\n"
        "article-1,alpha\n"
        "article-2,\n",
        encoding="utf-8",
    )

    documents = CsvDocumentLoader(
        file_path,
        content_field="text",
        id_field="id",
    ).load()

    assert [document.document_id for document in documents] == ["article-1"]


def test_csv_document_loader_uses_fallback_document_ids(tmp_path) -> None:
    file_path = tmp_path / "articles.csv"
    file_path.write_text(
        "text\n"
        "alpha\n",
        encoding="utf-8",
    )

    documents = CsvDocumentLoader(file_path, content_field="text").load()

    assert documents[0].document_id == "articles.csv:0"


def test_csv_document_loader_supports_custom_delimiter(tmp_path) -> None:
    file_path = tmp_path / "articles.tsv"
    file_path.write_text(
        "id\ttext\n"
        "article-1\talpha\n",
        encoding="utf-8",
    )

    documents = CsvDocumentLoader(
        file_path,
        content_field="text",
        id_field="id",
        delimiter="\t",
    ).load()

    assert documents[0].document_id == "article-1"
    assert documents[0].content == "alpha"


def test_csv_document_loader_rejects_oversized_file(tmp_path) -> None:
    file_path = tmp_path / "articles.csv"
    file_path.write_text("text\nabcdef\n", encoding="utf-8")

    with pytest.raises(ValueError):
        CsvDocumentLoader(
            file_path,
            content_field="text",
            max_file_bytes=5,
        ).load()


def test_csv_document_loader_rejects_too_many_documents(tmp_path) -> None:
    file_path = tmp_path / "articles.csv"
    file_path.write_text("text\nalpha\nbeta\n", encoding="utf-8")

    with pytest.raises(ValueError):
        CsvDocumentLoader(
            file_path,
            content_field="text",
            max_documents=1,
        ).load()


def test_csv_document_loader_rejects_missing_path(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        CsvDocumentLoader(
            tmp_path / "missing.csv",
            content_field="text",
        ).load()


def test_csv_document_loader_rejects_directory_path(tmp_path) -> None:
    with pytest.raises(ValueError):
        CsvDocumentLoader(
            tmp_path,
            content_field="text",
        ).load()
