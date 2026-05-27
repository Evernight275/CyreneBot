# Public Adapters

`cyreneAI.adapters` 是公共适配器层，面向使用方提供稳定、轻量、可直接组合到 application 流程里的 adapter。

## 允许

```text
读取本地文件
把外部输入转换为 core schema
提供轻量 factory
从 cyreneAI.infra.adapters 重导出稳定 adapter
```

## 禁止

```text
创建外部 SDK client
读取环境变量
放 provider mapper / instance / errors
写业务编排
复制 provider 内部实现
```

重型外部系统实现仍然属于：

```text
cyreneAI.infra.adapters
```

`cyreneAI.adapters` 的职责是给应用使用方提供短路径、稳定路径，并防止业务代码直接依赖过深的 infra 内部文件结构。provider 相关实现不放在这里，继续由 `provider_catalog`、`infra/adapters/providers` 和 `infra/bootstrap/registrations` 治理。
