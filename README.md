# CyreneAI

CyreneAI 是一个分层的 AI runtime，用于组织 provider、context、skill、tool、embedding、vector store 与 RAG 编排。

## 当前能力

```text
provider lifecycle
chat orchestration
embedding orchestration
document indexing
retrieval orchestration
RAG chat orchestration
memory / SQLite vector store
context snapshot persistence
skill and tool orchestration
OpenAI-compatible / OpenAI Responses / Anthropic / Google GenAI adapters
```

## 架构边界

CyreneAI 的核心约束是让变化只发生在合适的层：

```text
core
  定义 schema、protocol、manager、registry、通用错误和规则。
  不 import provider SDK，不读取环境变量，不创建外部 client。

infra/provider_catalog
  只声明 provider info。

infra/adapters
  实现外部系统适配，例如 provider SDK、tool executor、skill loader、vector store。

adapters
  公共适配层，提供面向使用方的轻量 adapter 和稳定导出。

infra/bootstrap
  装配 provider info、adapter builder、registry、factory。

application
  编排业务流程，例如 chat、embedding、indexing、retrieval、RAG chat 和 runtime bootstrap。
```

这让新增业务策略时通常只需要改 application 层；只有接入新的外部系统时才进入 infra/adapters。

应用使用方优先从 `cyreneAI.adapters` 导入公共适配器：

```python
from cyreneAI.adapters.documents import FileSystemDocumentLoader
from cyreneAI.adapters.vector_stores import create_memory_vector_store
```

`cyreneAI.infra.adapters` 是重型外部系统实现落点，适合 provider SDK、外部 tool executor、持久化 vector store 等实现，不建议作为业务代码的长期依赖路径。

## RAG 主路径

当前 RAG 流程由 application 层组合完成：

```text
build runtime
  -> configure provider
  -> index documents
  -> embed chunks
  -> upsert vectors
  -> embed query
  -> vector search
  -> inject retrieved context
  -> chat provider
  -> close runtime
```

索引支持两种切块策略：

```python
from cyreneAI.application.indexing_orchestrator import ChunkStrategy

chunk_strategy=ChunkStrategy.CHARACTER
chunk_strategy=ChunkStrategy.PARAGRAPH
```

RAG 支持 collection 隔离：

```python
collection_id="project-docs"
```

索引时会写入 vector metadata；检索和 RAG chat 时会自动追加 vector filter，避免不同知识库混搜。

RAG context 注入支持多种格式：

```python
from cyreneAI.application.rag_chat_orchestrator import RAGContextFormat

retrieval_context_format=RAGContextFormat.PLAIN
retrieval_context_format=RAGContextFormat.NUMBERED
retrieval_context_format=RAGContextFormat.SOURCE_TAGGED
retrieval_context_format=RAGContextFormat.COMPACT
```

可以限制每条检索内容长度，也可以把来源元数据注入 prompt：

```python
max_retrieved_content_chars=1200
include_retrieval_metadata=True
```

## 最小内存 RAG 用例

下面示例演示完整流程：

```text
build runtime -> 配置 provider -> index documents -> RAG chat -> close runtime
```

需要环境变量：

```bash
export OPENAI_COMPATIBLE_API_KEY="..."
export OPENAI_COMPATIBLE_BASE_URL="https://..."
export OPENAI_COMPATIBLE_MODEL="..."
export OPENAI_COMPATIBLE_EMBEDDING_MODEL="..."
```

`OPENAI_COMPATIBLE_BASE_URL` 可选；如果使用默认 OpenAI endpoint，可以改用 `OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_EMBEDDING_MODEL`。

```python
from __future__ import annotations

import asyncio
import os
from datetime import timedelta

from cyreneAI.application.bootstrap import build_cyrene_ai_runtime
from cyreneAI.application.indexing_orchestrator import (
    ApplicationIndexingRequest,
    ChunkStrategy,
    IndexingOrchestrator,
)
from cyreneAI.application.rag_chat_orchestrator import (
    ApplicationRAGChatRequest,
    RAGContextFormat,
    RAGChatOrchestrator,
)
from cyreneAI.adapters.documents import FileSystemDocumentLoader
from cyreneAI.adapters.vector_stores import create_memory_vector_store
from cyreneAI.core.schema.message import (
    ContentPart,
    ContentPartType,
    Message,
    MessageRole,
)
from cyreneAI.core.schema.provider import ProviderConfig, ProviderType


async def main() -> None:
    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY") or os.environ["OPENAI_API_KEY"]
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    chat_model = os.getenv("OPENAI_COMPATIBLE_MODEL") or os.environ["OPENAI_MODEL"]
    embedding_model = os.getenv("OPENAI_COMPATIBLE_EMBEDDING_MODEL") or os.environ[
        "OPENAI_EMBEDDING_MODEL"
    ]

    runtime = await build_cyrene_ai_runtime(
        provider_configs=[
            ProviderConfig(
                provider_id="openai-compatible",
                provider_type=ProviderType.OPENAI_COMPATIBLE,
                api_key=api_key,
                base_url=base_url,
                timeout=timedelta(seconds=30),
            )
        ],
        vector_store=create_memory_vector_store(),
    )

    try:
        documents = FileSystemDocumentLoader("docs").load()
        await IndexingOrchestrator(runtime).index(
            ApplicationIndexingRequest(
                provider_id="openai-compatible",
                model=embedding_model,
                documents=documents,
                chunk_size=500,
                chunk_strategy=ChunkStrategy.PARAGRAPH,
                collection_id="docs",
                metadata={"purpose": "readme-rag"},
            )
        )

        result = await RAGChatOrchestrator(runtime).chat(
            ApplicationRAGChatRequest(
                session_id="readme-session",
                provider_id="openai-compatible",
                model=chat_model,
                retrieval_provider_id="openai-compatible",
                retrieval_model=embedding_model,
                messages=[
                    Message(
                        role=MessageRole.USER,
                        content=[
                            ContentPart(
                                type=ContentPartType.TEXT,
                                text="Where should provider SDK calls live?",
                            )
                        ],
                    )
                ],
                retrieval_top_k=3,
                collection_id="docs",
                retrieval_context_format=RAGContextFormat.SOURCE_TAGGED,
                include_retrieval_metadata=True,
                temperature=0,
                max_tokens=128,
            )
        )

        message = result.chat_result.response.message
        if message is not None and message.content:
            print(message.content[0].text)
    finally:
        await runtime.close()


asyncio.run(main())
```

运行示例前，把要索引的 `.md` 或 `.txt` 文件放到 `docs/` 目录。

## 从文件加载文档

`cyreneAI.adapters.documents` 提供文件系统文档加载器，适合把本地 `.md` / `.txt` 文件转换为索引用的 `Document`：

```python
from cyreneAI.adapters.documents import FileSystemDocumentLoader

documents = FileSystemDocumentLoader("docs").load()
```

默认递归读取 `.md` 和 `.txt`，每个文档 metadata 会包含：

```text
source
path
relative_path
filename
extension
```

也可以从 JSON / JSONL / CSV 加载结构化文本：

```python
from cyreneAI.adapters.documents import CsvDocumentLoader, JsonDocumentLoader

json_documents = JsonDocumentLoader(
    "data/articles.jsonl",
    content_field="text",
    id_field="id",
    metadata_fields=["title", "url"],
).load()

csv_documents = CsvDocumentLoader(
    "data/articles.csv",
    content_field="text",
    id_field="id",
    metadata_fields=["title", "url"],
).load()
```

## SQLite 持久化 RAG

如果需要让索引后的向量跨进程保留，使用 `vector_database_path` 让 runtime 自动创建 SQLite 向量存储：

```python
runtime = await build_cyrene_ai_runtime(
    provider_configs=[
        ProviderConfig(
            provider_id="openai-compatible",
            provider_type=ProviderType.OPENAI_COMPATIBLE,
            api_key=api_key,
            base_url=base_url,
            timeout=timedelta(seconds=30),
        )
    ],
    vector_database_path="data/vectors.db",
)
```

其余索引和 RAG chat 流程与内存示例一致。关闭 runtime 时使用：

```python
await runtime.close()
```

## 定义 Python 工具

`cyreneAI.adapters.tools` 提供轻量工具 helper，只负责创建 `ToolDefinition` 和 executor；注册仍由 runtime 的 tool registry 完成：

```python
from cyreneAI.adapters.tools import define_python_tool


def lookup_order(args: dict) -> dict:
    return {"order_id": args["order_id"], "status": "shipped"}


definition, executor = define_python_tool(
    name="lookup_order",
    description="Lookup order status.",
    function=lookup_order,
    parameters_schema={
        "type": "object",
        "properties": {
            "order_id": {"type": "string"},
        },
        "required": ["order_id"],
    },
)

runtime.tool_registry.register(definition, executor)
```

## 验证

```bash
uv run python -m compileall src
uv run pytest src/cyreneAI/tests
```
