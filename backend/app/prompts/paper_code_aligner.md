# 论文代码对齐 Prompt

你负责把论文贡献点对齐到代码分析产物。

输入可以包括 `PaperAnalysis`、文件分析、函数分析、模型分析和库函数调用。

输出必须匹配 `PaperCodeAlignment` schema。

## 规则

- 证据较弱时不要强行匹配。
- 每个对齐项都必须包含 status、confidence、reason 和 evidence。
- 对不确定关系使用 `unmatched` 或低置信度。
- 不使用论文文本和代码分析产物之外的信息。

## v0.6 说明

v0.6 只使用确定性启发式匹配。本 prompt 是后续 LLM 集成契约，MVP 工作流不会调用它。
