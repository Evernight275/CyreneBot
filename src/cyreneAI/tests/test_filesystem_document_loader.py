from __future__ import annotations

import pytest

from cyreneAI.adapters.documents import FileSystemDocumentLoader
from cyreneAI.core.schema.document import Document


def test_filesystem_document_loader_loads_supported_files_recursively(tmp_path) -> None:
    docs_path = tmp_path / "docs"
    nested_path = docs_path / "nested"
    nested_path.mkdir(parents=True)
    (docs_path / "alpha.md").write_text("alpha", encoding="utf-8")
    (nested_path / "beta.txt").write_text("beta", encoding="utf-8")
    (docs_path / "ignored.json").write_text("{}", encoding="utf-8")
    (docs_path / "empty.md").write_text("", encoding="utf-8")

    documents = FileSystemDocumentLoader(docs_path).load()

    assert documents == [
        Document(
            document_id="alpha.md",
            content="alpha",
            metadata={
                "source": "filesystem",
                "path": (docs_path / "alpha.md").as_posix(),
                "relative_path": "alpha.md",
                "filename": "alpha.md",
                "extension": ".md",
            },
        ),
        Document(
            document_id="nested/beta.txt",
            content="beta",
            metadata={
                "source": "filesystem",
                "path": (nested_path / "beta.txt").as_posix(),
                "relative_path": "nested/beta.txt",
                "filename": "beta.txt",
                "extension": ".txt",
            },
        ),
    ]


def test_filesystem_document_loader_can_load_single_file(tmp_path) -> None:
    file_path = tmp_path / "alpha.md"
    file_path.write_text("alpha", encoding="utf-8")

    documents = FileSystemDocumentLoader(file_path).load()

    assert len(documents) == 1
    assert documents[0].document_id == "alpha.md"
    assert documents[0].content == "alpha"


def test_filesystem_document_loader_supports_custom_extensions(tmp_path) -> None:
    docs_path = tmp_path / "docs"
    docs_path.mkdir()
    (docs_path / "alpha.rst").write_text("alpha", encoding="utf-8")
    (docs_path / "beta.md").write_text("beta", encoding="utf-8")

    documents = FileSystemDocumentLoader(
        docs_path,
        extensions={"rst"},
    ).load()

    assert [document.document_id for document in documents] == ["alpha.rst"]


def test_filesystem_document_loader_can_disable_recursion(tmp_path) -> None:
    docs_path = tmp_path / "docs"
    nested_path = docs_path / "nested"
    nested_path.mkdir(parents=True)
    (docs_path / "alpha.md").write_text("alpha", encoding="utf-8")
    (nested_path / "beta.md").write_text("beta", encoding="utf-8")

    documents = FileSystemDocumentLoader(
        docs_path,
        recursive=False,
    ).load()

    assert [document.document_id for document in documents] == ["alpha.md"]


def test_filesystem_document_loader_rejects_oversized_file(tmp_path) -> None:
    file_path = tmp_path / "alpha.md"
    file_path.write_text("abcdef", encoding="utf-8")

    with pytest.raises(ValueError):
        FileSystemDocumentLoader(file_path, max_file_bytes=5).load()


def test_filesystem_document_loader_rejects_too_many_documents(tmp_path) -> None:
    docs_path = tmp_path / "docs"
    docs_path.mkdir()
    (docs_path / "alpha.md").write_text("alpha", encoding="utf-8")
    (docs_path / "beta.md").write_text("beta", encoding="utf-8")

    with pytest.raises(ValueError):
        FileSystemDocumentLoader(docs_path, max_documents=1).load()


def test_filesystem_document_loader_rejects_missing_path(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        FileSystemDocumentLoader(tmp_path / "missing").load()
