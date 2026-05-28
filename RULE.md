# RULE.md

本文件记录项目架构规则、合并标准与不可协商的边界。

## 总则

代码可以慢慢长，但职责不能乱。

本项目优先保证：

- 文件职责清晰
- 依赖方向稳定
- 外部 SDK 被隔离
- core 保持纯净
- infra 的脏活集中在 adapter
- 可验证、可拒收、可写进 CI

## 核心边界

```text
core
  定义规则、schema、protocol、通用错误

infra/provider_catalog
  声明身份

infra/adapters
  连接外部世界

infra/bootstrap
  装配 provider info、adapter builder、registry、factory

application
  编排应用 runtime 与业务流程

cyreneAI.bootstrap
  总装 core/application/infra，生成可运行 runtime
```

不允许为了方便跨层写代码。

## 依赖铁律

按“允许 import 谁”判定：

```text
core
  禁止 import infra/application/server。

infra
  可以 import core。
  adapter 内可以 import 外部 SDK。
  禁止 import application/server。

application
  可以 import core。
  禁止 import infra/server/外部 SDK。

cyreneAI.bootstrap
  是唯一默认 composition root。
  可以同时 import core/application/infra。

server
  可以调用 cyreneAI.bootstrap。
```

出现以下任意行为，该 PR 直接拒收：

- application import `cyreneAI.infra`
- application import `cyreneAI.server`
- infra import `cyreneAI.application`
- infra import `cyreneAI.server`
- core import `cyreneAI.infra`
- core import `cyreneAI.application`
- core import `cyreneAI.server`

## schema 铁律

`core/schema` 是唯一 schema 定义目录。

任何继承 `CyreneAISchema` 的类只能放在：

```text
src/cyreneAI/core/schema/
```

严禁在以下目录定义 `CyreneAISchema` 派生类：

```text
src/cyreneAI/application/
src/cyreneAI/infra/
src/cyreneAI/server/
```

应用层 request/result schema 也必须放在 `core/schema`，例如：

```text
ApplicationChatRequest
ApplicationChatResult
ApplicationBotRequest
ApplicationBotDispatchResult
ApplicationRAGChatRequest
ApplicationVectorSearchResult
```

application 只能 import 这些 schema 并编排流程，不能在 orchestrator 内定义 schema。

## application 铁律

application 只负责应用 runtime 容器与业务流程编排。

允许：

- import core schema/protocol/manager/error
- 调用 provider manager
- 调用 context/skill/tool/vector manager
- 编排 chat、RAG、bot、channel、indexing、retrieval 流程

禁止：

- import infra
- import server
- import 外部 SDK
- 读取 `.env`
- 读取环境变量
- 创建外部 SDK client
- 创建 sqlite/database store
- 创建 filesystem loader
- 注册 provider adapter
- 处理 provider 专属协议差异
- 定义 `CyreneAISchema` 派生类

## composition root 铁律

默认运行时总装只能放在：

```text
src/cyreneAI/bootstrap.py
```

`cyreneAI.bootstrap` 是唯一允许同时 import application 与 infra 的默认 composition root。

允许：

- 注册默认 provider
- 注册默认 bot channel
- 创建 sqlite context/vector store
- 创建 filesystem skill loader
- 调用 application bootstrap 生成 runtime

禁止：

- 写 provider 请求/响应 mapper
- 写 provider quirk
- 发真实请求
- 读取用户输入
- 承担业务流程编排

## provider catalog 目录铁律

`src/cyreneAI/infra/provider_catalog/` 只准放格式为 `{provider_name}_info.py` 的 py 文件。

允许：

```text
__init__.py
openai_compatible_info.py
deepseek_info.py
ollama_info.py
```

禁止：

```text
builder.py
instance.py
mapper.py
errors.py
register.py
setup.py
client.py
任何子目录
```

若出现其他文件，本人恕不接收该 pull request。

## adapter 规则

adapter 是唯一可以承担外部现实复杂度的地方。

允许 adapter：

- import 外部 SDK
- 创建和关闭 client
- 发真实请求
- 捕获外部异常
- 转换请求 payload
- 转换响应对象

adapter 必须把外部细节转换回 core 类型，不能把 SDK 类型向上传播到 application。

## mapper 规则

mapper 只做数据形状转换。

允许：

- `ChatRequest -> OpenAI-compatible payload`
- `ChatCompletion -> ChatResponse`
- `ToolDefinition -> tool payload`
- `finish_reason -> ChatFinishReason`
- `usage -> TokenUsage`

禁止：

- 创建 client
- 发请求
- 读取环境变量
- 注册 provider
- 捕获 SDK 异常

## errors 规则

errors 只做异常翻译。

```text
外部 SDK 异常 -> core provider 异常
```

禁止在 errors 层做：

- 重试
- 降级
- 日志系统绑定
- 业务判断

## instance 规则

instance 是 adapter 的运行对象。

允许：

- 持有 `ProviderConfig`
- 持有 `ProviderInfo`
- 持有外部 SDK client
- 实现 `close()`
- 实现 `chat()`

禁止：

- 声明 provider 身份常量
- 注册 factory
- 注册 registry
- 读取 `.env`

## infra/bootstrap 规则

`infra/bootstrap` 只负责 provider/channel 注册装配，不负责应用 runtime 总装。

允许：

- 把 `ProviderInfo` 注册到 `ProviderRegistry`
- 把 adapter builder 注册到 `ProviderFactory`
- 把 channel adapter 注册到 channel registry

禁止：

- 发请求
- 创建业务流程
- 读取用户输入
- import application
- 创建 `CyreneAIRuntime`

## ProviderConfig 规则

`ProviderConfig` 属于 core schema，只做通用配置形状约束。

允许：

- `provider_id` 形状
- `provider_type` 类型
- `timeout` 使用 `timedelta`
- 通用空值约束

禁止：

- 在 core 写某个 provider 专属规则
- 在 core 判断 OpenAI-compatible 是否必须有 api_key

provider 专属配置要求应在 adapter builder 或 instance 中处理。

## 验收标准

边界测试必须存在并通过：

```text
test_core_does_not_import_external_sdks_or_upper_layers
test_provider_catalog_imports_only_core_schema
test_provider_adapter_directories_have_expected_files
test_infra_does_not_import_application_or_server
test_application_does_not_import_infra_or_server
test_application_does_not_define_core_schema_classes
test_only_core_schema_defines_cyrene_ai_schema_subclasses
test_bootstrap_registrations_only_wire_core_catalog_and_adapters
```

任何分层、schema、provider、bootstrap、adapter 相关改动，必须跑完整测试。

基础验证：

```bash
uv run python -m compileall src
uv run pytest src\cyreneAI\tests
```

真实调用验证：

```bash
uv run pytest -s src\cyreneAI\tests\test_openai_compatible_real_chat.py
```

看到真实模型返回，并通过测试，才算 openai-compatible 实际链路验收完成。
