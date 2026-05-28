# AGENTS.md

本文件是给 AI 协作者和自动化代理读取的项目执行规矩。

## 基本流程

1. 确认并遵守 `AGENTS.md`
2. 查看相关代码与现有结构
3. 按既有架构写代码
4. 验证，包括测试、编译检查、类型检查
5. 给出验收结论

## 分层原则

依赖边界固定，按“允许 import 谁”理解：

```text
core
  只能依赖 Python 标准库与项目无关的轻量基础库。

infra
  可以依赖 core。
  可以在 adapter 内依赖外部 SDK。
  禁止依赖 application、server。

application
  可以依赖 core。
  禁止依赖 infra、server、外部 SDK。

cyreneAI.bootstrap
  是唯一默认 composition root。
  可以同时依赖 core、infra、application。

server
  可以依赖 cyreneAI.bootstrap、application runtime、server 自身模块。
```

实际含义：

```text
core
  只定义规则、schema、protocol、通用错误。

infra/provider_catalog
  只放 provider 注册信息。

infra/adapters
  只放外部系统适配实现，例如 SDK client、请求映射、响应映射、异常翻译。

infra/bootstrap
  只负责把 provider info、adapter builder、registry、factory 装配起来。

application
  只负责应用 runtime 容器与业务流程编排。
  (
    不允许schema定义！！！
    不允许schema定义！！！
    不允许schema定义！！！
    哪怕@dataclass也不行，一律滚去core/schema目录
  )

cyreneAI.bootstrap
  只负责把 core/application/infra 总装成可运行 runtime。
```

## 严禁越界

`core` 严禁：

- import `openai`
- import `httpx`
- 读取 `.env`
- 创建外部 SDK client
- 写 provider 专属实现规则
- import `cyreneAI.infra`
- import `cyreneAI.application`
- import `cyreneAI.server`

`application` 严禁：

- import `cyreneAI.infra`
- import `cyreneAI.server`
- import 外部 SDK，例如 `openai`、`httpx`、`anthropic`、`google`
- 读取 `.env`
- 读取环境变量
- 创建外部 SDK client
- 创建 database store
- 创建 filesystem loader
- 注册 provider adapter
- 处理 provider 专属协议差异
- 定义继承 `CyreneAISchema` 的 schema 类
- 定义公开 `@dataclass` DTO

`infra/provider_catalog` 严禁：

- 放 `builder.py`
- 放 `instance.py`
- 放 `mapper.py`
- 放 `errors.py`
- 放 `setup.py`
- 放子目录
- import 外部 SDK

`infra/adapters` 可以：

- import 外部 SDK
- 创建 client
- 调用外部 API
- 做 schema 映射
- 翻译外部异常

`infra` 整体严禁：

- import `cyreneAI.application`
- import `cyreneAI.server`

## schema 规则

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

应用层 request/result schema 也属于 core schema，例如：

```text
ApplicationChatRequest
ApplicationChatResult
ApplicationBotRequest
ApplicationRAGChatRequest
```

这些类型只能定义在 `core/schema`，application 只能 import 并使用。

严禁用 `@dataclass` 绕过 schema 边界，在 application 定义公开 DTO。
application 只允许私有算法 helper dataclass，例如 `_ParagraphSpan`；公开 runtime 容器需要明确白名单。

## composition root 规则

默认运行时总装只能放在：

```text
src/cyreneAI/bootstrap.py
```

`cyreneAI.bootstrap` 可以同时 import application 与 infra，因为它是 composition root。

除 `cyreneAI.bootstrap` 外：

- `application` 不准装配 infra 具体实现
- `infra` 不准装配 application runtime
- `server` 不准手写 provider adapter 注册细节，只调用 composition root

## provider 信息目录规则

`src/cyreneAI/infra/provider_catalog/` 只准放：

```text
__init__.py
{provider_name}_info.py
```

任何其他文件都视为架构越界。

## OpenAI-Compatible 规则

`openai_compatible` 是协议适配器，不是具体厂商身份。

```text
src/cyreneAI/infra/provider_catalog/openai_compatible_info.py
  只声明 OPENAI_COMPATIBLE_PROVIDER_INFO

src/cyreneAI/infra/adapters/providers/openai_compatible/
  实现 OpenAI-compatible 协议调用

src/cyreneAI/infra/bootstrap/registrations/openai_compatible.py
  装配 provider info 与 adapter builder
```

### 供应商差异处理原则

OpenAI-compatible 供应商差异只在 infra adapter 内翻译：

1. 标准字段默认走 mapper 基础路径。
2. 非标准请求或响应字段只在 `infra/adapters/providers/openai_compatible` 内处理。
3. 是否启用 quirk 由 instance 根据 `ProviderConfig` 判断。
4. `core` 不出现具体供应商名称。
5. `application` 不处理供应商协议差异。
6. 能力失败后的降级由 manager 或 application 处理，不放进 mapper。
7. 每个 quirk 必须有 mapper 或 instance 单测。

## 测试要求

边界规则必须由测试守住，至少包括：

```text
test_core_does_not_import_external_sdks_or_upper_layers
test_provider_catalog_imports_only_core_schema
test_provider_adapter_directories_have_expected_files
test_infra_does_not_import_application_or_server
test_application_does_not_import_infra_or_server
test_application_does_not_define_core_schema_classes
test_application_does_not_define_public_dataclass_dtos
test_only_core_schema_defines_cyrene_ai_schema_subclasses
test_bootstrap_registrations_only_wire_core_catalog_and_adapters
```

若改动分层、schema、provider、bootstrap 或 adapter，必须运行完整边界测试和项目测试。

改动 infra provider/adapter/bootstrap 时，至少运行：

```bash
uv run python -m compileall src
uv run pytest src\cyreneAI\tests
```

真实 API 验证使用环境变量：

```text
OPENAI_COMPATIBLE_API_KEY 或 OPENAI_API_KEY
OPENAI_COMPATIBLE_BASE_URL 或 OPENAI_BASE_URL
OPENAI_COMPATIBLE_MODEL 或 OPENAI_MODEL
```

真实测试没有环境变量时必须 skip，不能失败。
