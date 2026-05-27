# AGENTS.md

本文件是给 AI 协作者和自动化代理读取的项目执行规矩。

## 基本流程

1. 确认并遵守 `AGENTS.md`
2. 查看相关代码与现有结构
3. 按既有架构写代码
4. 验证，包括测试、编译检查、类型检查
5. 给出验收结论

## 分层原则

依赖方向固定：

```text
core -> infra
core/infra -> application
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
  只负责应用入口与业务流程编排。
```

## 严禁越界

`core` 严禁：

- import `openai`
- import `httpx`
- 读取 `.env`
- 创建外部 SDK client
- 写 provider 专属实现规则

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
