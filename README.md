# CyreneBot

CyreneBot 是一个分层的 AI bot framework，用于组织 channel、provider、context、skill、tool、embedding、vector store 与 RAG 编排。

当前代码包名仍保留为 `cyreneAI`，用于保护已有导入路径；对外项目定位和后续内核演进以 CyreneBot 为准。

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

CyreneBot 的核心约束是让变化只发生在合适的层：

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

## Agent 使用入口

Agent 可以从 HTTP、bot 自动回复和插件命名空间进入，三个入口最终都会构造同一个 `AgentRunRequest`，再交给 application 层的 `AgentOrchestrator` 执行。

### HTTP `/agents/run`

```json
{
  "provider_id": "openai-compatible",
  "model": "gpt-4o-mini",
  "goal": "查一下当前时间，并结合项目记忆给出下一步建议。",
  "messages": [
    {"role": "user", "content": "需要一版 agent smoke 结论"}
  ],
  "max_steps": 1,
  "required_skill_names": ["project_status"],
  "max_skills": 2,
  "planning": {
    "enabled": true,
    "instructions": "优先使用已注入 skill 和检索到的 memory。",
    "max_objectives": 3
  },
  "tool_selection": {
    "allowed_tool_names": ["get_current_time", "search_memory"],
    "denied_tool_names": []
  },
  "memory_retrieval": {
    "enabled": true,
    "query": "project agent smoke status",
    "namespace": "project",
    "top_k": 3
  },
  "temperature": 0,
  "max_tokens": 256
}
```

`required_skill_names` 会要求运行前选择指定 skill，`max_skills` 限制最多注入多少个 skill。`tool_selection` 用于限制运行期可见工具；如果配置了 skill 的工具白名单，最终可用工具还会继续受 skill policy 约束。`memory_retrieval` 会在首轮模型调用前检索记忆，并以 memory context 注入窗口。`max_steps=1` 时，如果模型产生工具调用，Agent 会执行工具后再发起一次 finalization 请求，让模型基于工具结果收束回答。

`planning` 当前是运行提示，也就是 `runtime_hint`：它会进入 Agent plan metadata 和 prompt 注入，帮助模型按目标行动；它还不是独立 planner。若后续需要真实规划，应新增独立 planner step，而不是继续扩展静态 plan 构造。

### bot `AGENT` 模式

channel webhook 和 channel event 可以把普通 bot 回复切到 Agent 模式：

```json
{
  "provider_id": "openai-compatible",
  "model": "gpt-4o-mini",
  "payload": {
    "text": "帮我查当前时间并参考项目记忆回复",
    "user_id": "u1",
    "chat_id": "c1"
  },
  "message_response_mode": "agent",
  "max_agent_steps": 1,
  "required_skill_names": ["project_status"],
  "max_skills": 2,
  "agent_planning": {
    "enabled": true,
    "instructions": "按 bot 消息目标给出直接回复。"
  },
  "agent_tool_selection": {
    "allowed_tool_names": ["get_current_time", "search_memory"]
  },
  "agent_memory_retrieval": {
    "enabled": true,
    "query": "bot project status",
    "namespace": "project",
    "top_k": 2
  }
}
```

bot 的字段名带 `agent_` 前缀，用于和普通 chat 参数区分；进入 application 后会被转换成同一份 Agent request。

### plugin `agent.chat/result`

插件可以通过受控 Agent 命名空间调用同一条 Agent 路径：

```python
from cyreneAI.core.schema.agent import (
    AgentMemoryRetrievalConfig,
    AgentPlanningConfig,
    AgentToolSelectionConfig,
)


async def handle(ctx) -> str:
    result = await ctx.agent.result(
        "查当前时间，并结合项目记忆总结状态。",
        max_steps=1,
        required_skill_names=["project_status"],
        max_skills=2,
        planning=AgentPlanningConfig(
            enabled=True,
            instructions="优先使用插件请求里的目标和 skill。",
        ),
        tool_selection=AgentToolSelectionConfig(
            allowed_tool_names=["get_current_time", "search_memory"],
        ),
        memory_retrieval=AgentMemoryRetrievalConfig(
            enabled=True,
            query="plugin agent project status",
            namespace="project",
            top_k=2,
        ),
    )
    return result
```

`ctx.agent.chat(...)` 返回 `Message`，`ctx.agent.result(...)` 返回文本结果；参数与 `/agents/run` 保持同语义。

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
