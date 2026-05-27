from __future__ import annotations

from pathlib import Path

from cyreneAI.adapters.bot_sessions import (
    InMemoryBotSessionStore,
    create_memory_bot_session_store,
)
from cyreneAI.adapters.channels import (
    InMemoryBotChannel,
    create_memory_bot_channel,
)
from cyreneAI.adapters.documents import (
    CsvDocumentLoader,
    FileSystemDocumentLoader,
    JsonDocumentLoader,
)
from cyreneAI.adapters.skills import FileSystemSkillLoader
from cyreneAI.adapters.tools import (
    HttpToolExecutor,
    PythonCallableToolExecutor,
    SubprocessToolExecutor,
    define_python_tool,
)
from cyreneAI.adapters.vector_stores import (
    InMemoryVectorStore,
    SQLiteVectorStore,
    create_memory_vector_store,
    create_sqlite_vector_store,
)


def test_public_adapters_facade_exports_supported_adapters() -> None:
    assert CsvDocumentLoader.__name__ == "CsvDocumentLoader"
    assert FileSystemDocumentLoader.__name__ == "FileSystemDocumentLoader"
    assert JsonDocumentLoader.__name__ == "JsonDocumentLoader"
    assert InMemoryVectorStore.__name__ == "InMemoryVectorStore"
    assert SQLiteVectorStore.__name__ == "SQLiteVectorStore"
    assert create_memory_vector_store.__name__ == "create_memory_vector_store"
    assert create_sqlite_vector_store.__name__ == "create_sqlite_vector_store"
    assert HttpToolExecutor.__name__ == "HttpToolExecutor"
    assert PythonCallableToolExecutor.__name__ == "PythonCallableToolExecutor"
    assert SubprocessToolExecutor.__name__ == "SubprocessToolExecutor"
    assert define_python_tool.__name__ == "define_python_tool"
    assert FileSystemSkillLoader.__name__ == "FileSystemSkillLoader"
    assert InMemoryBotChannel.__name__ == "InMemoryBotChannel"
    assert create_memory_bot_channel.__name__ == "create_memory_bot_channel"
    assert InMemoryBotSessionStore.__name__ == "InMemoryBotSessionStore"
    assert (
        create_memory_bot_session_store.__name__
        == "create_memory_bot_session_store"
    )


def test_public_adapters_facade_does_not_contain_provider_implementations() -> None:
    adapters_path = Path(__file__).parents[1] / "adapters"
    forbidden_names = {
        "builder.py",
        "instance.py",
        "mapper.py",
        "errors.py",
    }

    assert not any(
        path.name in forbidden_names
        for path in adapters_path.rglob("*.py")
    )
    assert not (adapters_path / "providers").exists()


def test_public_adapters_facade_does_not_depend_on_forbidden_layers() -> None:
    adapters_path = Path(__file__).parents[1] / "adapters"
    forbidden_patterns = [
        "cyreneAI.application",
        "cyreneAI.infra.bootstrap",
        "cyreneAI.infra.provider_catalog",
        "load_dotenv",
        "os.getenv",
        "os.environ",
    ]

    for path in adapters_path.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(pattern in source for pattern in forbidden_patterns), path
