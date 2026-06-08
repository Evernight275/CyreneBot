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

cyreneAI.bootstrap
  默认 composition root，负责把 core / application / infra 总装成可运行 runtime。

application
  编排业务流程，例如 chat、embedding、indexing、retrieval、RAG chat 和 runtime 容器。
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
from cyreneAI.core.schema.application import ChunkStrategy

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
from cyreneAI.core.schema.application import RAGContextFormat

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

完整 runtime 示例面向源码仓库，或包含 `cyreneAI.bootstrap`、`application`、
`infra` 的运行时分发；当前 `cyreneai-plugin-sdk` 发布包只包含
`cyreneAI.api` 和 `cyreneAI.core`。在源码仓库中直接运行示例时，确保
`src` 在 Python import path 中，例如：

```bash
PYTHONPATH=src uv run python examples/rag_demo.py
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

from cyreneAI.bootstrap import build_cyrene_ai_runtime
from cyreneAI.application.knowledge.indexing_orchestrator import (
    IndexingOrchestrator,
)
from cyreneAI.application.chat.rag_orchestrator import (
    RAGChatOrchestrator,
)
from cyreneAI.core.schema.application import (
    ApplicationIndexingRequest,
    ApplicationRAGChatRequest,
    ChunkStrategy,
    RAGContextFormat,
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

`planning` 会启用独立 planner step。planner 会在主 Agent loop 前生成可审计的 `AgentPlan`，包含 `objectives`、`steps`、工具约束和 skill 约束；随后该计划会以 `agent_plan` system message 注入主 loop。计划 metadata 中的 `planning_mode` 为 `planner_step`。

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

## QQ 官方机器人接入准备

QQ channel 当前按“官方机器人 + Webhook/通用 channel webhook”路线准备，先支持文本消息映射和文本回复。申请与接入时按下面顺序推进：

1. 登录 QQ 开放平台，创建机器人应用。
2. 填写机器人名称、简介、头像等基础资料。
3. 在开发配置里记录 `AppID`、`AppSecret`，必要时记录平台提供的 `Token`。
4. 配置沙箱环境，先加入测试 QQ 群、测试用户或频道。
5. 配置消息事件权限，至少打开消息创建相关事件。
6. 准备公网 HTTPS 回调地址，例如 `https://bot.example.com/qq/webhook`。
7. 按平台要求配置服务器 IP 白名单。
8. 在沙箱里测试消息接收和文本回复。
9. 通过沙箱后再提交发布审核。

项目侧 QQ adapter 支持两种凭证形态：

```python
from cyreneAI.adapters.channels import create_qq_bot_channel

channel = create_qq_bot_channel(
    app_id="QQ_BOT_APP_ID",
    app_secret="QQ_BOT_APP_SECRET",
)
```

也可以直接传入已有 access token：

```python
channel = create_qq_bot_channel(token="QQ_BOT_ACCESS_TOKEN")
```

QQ channel 不会默认注册到 runtime，建议作为可选 channel 显式装配：

```python
from cyreneAI.core.bot.registry import BotChannelRegistry
from cyreneAI.infra.bootstrap.registrations.qq_bot_channel import (
    register_qq_bot_channel,
)

registry = BotChannelRegistry()
register_qq_bot_channel(
    registry,
    app_id="QQ_BOT_APP_ID",
    app_secret="QQ_BOT_APP_SECRET",
)
```

建议环境变量命名：

```text
QQ_BOT_APP_ID=...
QQ_BOT_APP_SECRET=...
QQ_BOT_ACCESS_TOKEN=...
QQ_BOT_BASE_URL=https://api.sgroup.qq.com
QQ_BOT_TOKEN_URL=https://bots.qq.com/app/getAppAccessToken
QQ_BOT_WEBHOOK_SECRET=...
QQ_BOT_MODE=websocket
QQ_BOT_PROVIDER_ID=openai-compatible
QQ_BOT_MODEL=...
QQ_BOT_WEBHOOK_URL=https://bot.example.com/qq/webhook
```

`QQ_BOT_WEBHOOK_SECRET` 用于 QQ 官方平台配置回调 URL 时的 `op=13`
签名校验；不配置时会回退使用 `QQ_BOT_APP_SECRET`。

`QQ_BOT_MODE=websocket` 会在服务启动时使用 QQ 官方 `botpy` 长连接接收事件，不需要公网域名，适合沙箱调试和域名备案/解析等待期。域名与 HTTPS 准备好后，可以切回 `QQ_BOT_MODE=webhook`，使用平台回调地址。

QQ 官方平台不接受裸公网 IP 作为回调地址，生产接入需要域名和 HTTPS。可以先把服务与反向代理准备好，等 DNS 生效后再把平台回调填为：

```text
https://bot.example.com/qq/webhook
```

例如 Caddy：

```caddy
bot.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

当前阶段只承诺最小文本链路：QQ update 映射为 `BotEvent`，`BotAction(SEND_MESSAGE)` 映射为 QQ 文本发送 payload。图片、引用回复、按钮、富媒体和更细的群/频道权限会在真实沙箱测试后再扩展。

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

## 真实链路 smoke

真实 provider 和 Telegram smoke 默认从 `.env` 读取配置，缺少环境变量时会 skip，不会让普通测试失败。

在 `.env` 或当前 shell 中配置需要的变量后，可以单独跑真实链路：

```bash
uv run pytest src/cyreneAI/tests/test_openai_compatible_real_chat.py -s
uv run pytest src/cyreneAI/tests/test_openai_compatible_real_agent_smoke.py -s
uv run pytest src/cyreneAI/tests/test_telegram_bot_real_smoke.py -s
```

最小 OpenAI-compatible 配置：

```bash
OPENAI_COMPATIBLE_API_KEY=...
OPENAI_COMPATIBLE_BASE_URL=https://...
OPENAI_COMPATIBLE_MODEL=...
```

如果使用默认 OpenAI endpoint，也可以使用 `OPENAI_API_KEY`、`OPENAI_MODEL` 和可选的 `OPENAI_BASE_URL`。
