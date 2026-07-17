# 评测说明

v1.4.0 仍处于确定性结构化索引阶段，不包含 Hybrid RAG、向量检索或动态 Research Agent。当前评测目标是验证索引事实的稳定性、完整性、幂等性和旧流程兼容性，而不是回答生成质量。

## 固定基线

- 示例输入：`examples/small_pytorch_project.zip`
- v1.3.5 基线 commit：`5073f9f899e83759a6e21ec1ea56a7ae282f84eb`
- 30 个固定基础问题及规则结果：[evaluation_baseline_v1.3.5.md](evaluation_baseline_v1.3.5.md)
- 基线不启用 LLM/VLM，不访问网络，以旧 JSON 事实作为判定来源。

## v1.4 自动评测

`tests/indexing/` 验证：

- Entity/Edge/repo/content/input ID 与 hash 稳定性；
- module root、跨平台路径、重复和条件符号；
- import alias、from import、relative/circular import 与继承；
- local call、`self.method()`、`self.module(x) → forward`、实例化和 unresolved call；
- `indexed_files`、`symbol_chunks`、迁移、幂等、删除、修改和事务回滚；
- 同/不同输入并发、不同仓库并发、lease、busy/临时 I/O 重试和状态机；
- feature flag 开关，以及旧 JSON 和报告的 Schema 与规范化语义兼容。

## 后续 RAG 对比规则

后续版本必须复用同一问题集和示例输入，并至少记录答案命中、证据命中、unresolved/ambiguous 数量、端到端延迟和失败类型。不得把 LLM 自述正确当作事实命中；答案必须回指实体、关系或旧规则事实证据。
