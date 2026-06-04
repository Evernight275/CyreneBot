# PR 审查材料

本 PR 不是只提交代码，必须提交可审查材料。描述空洞、证据缺失、章节留空、只写“已测试/见代码/暂无”的 PR 会被直接拒绝。

## 设计目的

必须回答：

- 这个改动解决什么真实问题？
- 为什么这个问题值得进主线，而不是留在插件、配置、文档或外部脚本里？
- 为什么当前方案比更小的改动更合理？
- 本 PR 明确拒绝了哪些错误方向？

## 架构审查

必须回答：

- 本 PR 触碰了哪些层：core、application、infra、server、bootstrap、api、tests？
- 每个关键逻辑为什么属于当前层？
- 是否新增抽象？如果新增，它禁止了哪些错误调用路径？
- 是否影响 provider、adapter、plugin、skill、bot channel 的边界？

## import 审查

必须列出新增或关键 import，并说明：

- core 没有 import infra/application/server/外部 SDK/env。
- application 没有 import infra/server/外部 SDK/env，也没有定义公开 DTO/schema。
- infra 没有 import application/server。
- server 没有手写 provider/adapter 装配细节。

## 函数审查

必须列出新增或修改的关键函数，并回答：

- 这个函数表达的是业务规则、平台适配、协议映射，还是应用编排？
- 参数是否把平台差异泄漏到上层？
- 失败路径在哪里翻译，是否被吞掉？
- 哪些函数最值得 reviewer 逐行看？

## 验收证据

必须提供可点击、可复核证据。只写“已测试”无效。

必须包含至少一种：

- GitHub Actions run 链接，格式必须是 `https://github.com/<owner>/<repo>/actions/runs/<id>`。
- GitHub 上传附件链接，例如终端截图、功能截图、录屏。

涉及用户可见行为、bot 行为、server API、plugin API、provider/adapter 行为时，还必须提供功能证据：

- 终端输出截图或原始日志，必须能看到命令和结果。
- 请求/响应样例，必须能看到输入、输出和状态。
- UI/运行截图或录屏，必须能证明关键路径跑通。

Actions run:

功能证据:

## 风险与回滚

必须回答：

- 最可能坏在哪里？
- 哪些测试覆盖了失败路径？
- 如何回滚？
- 有没有迁移、兼容性、平台能力边界变化？
- 如果 reviewer 只能看三个文件，应该看哪三个？为什么？
