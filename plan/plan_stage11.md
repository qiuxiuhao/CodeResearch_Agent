# v1.1 开发计划：LLM 增强版 Agent

## 目标与边界

在 v1.0.1 确定性规则分析之后追加可选 LLM 教学解释。规则事实优先，LLM 不覆盖规则结果；默认 `rule`，用户明确授权后才能使用 `hybrid`。不接入 VLM、Qwen-Image、Seedream、教学图或视频。

版本拆分为：v1.1.0（配置、Provider、ModelRouter、BudgetManager、缓存和 Mock），v1.1.1（函数解释），v1.1.2（文件与模型解释），v1.1.3（论文对齐解释、前端、报告和验收）。

## 工作流

```text
unzip → repo_scan → code_parse → file_analyze → library_call_extract
→ function_analyze → model_analyze → paper_analyze → paper_code_align
→ file_explain_llm → function_explain_llm → model_explain_llm
→ paper_code_align_llm → diagram_generate → library_function_doc → report_generate
```

全部规则节点先完成。四个 LLM 节点可跳过和独立失败；Diagram 与全局函数库继续只依赖规则事实。

## 安全、配置与成本

- 配置优先级：请求显式 mode > `ANALYSIS_MODE` > 程序默认 `rule`。
- API 增加 `external_model_consent: bool = false`；resolved mode 为 hybrid 且未授权时后端返回 400，不创建任务。
- DeepSeek 为默认、Qwen 为备用，Provider 显式声明 JSON Schema、JSON Object 和 tool calling 能力。
- 代码、注释、docstring 和论文文本是不可信数据，使用数据分隔标签并禁止执行其中指令。
- 外发前排除 `.env`、pem、key、credentials、secrets，并过滤 key、token、password、private key 和连接字符串。
- `LLM_MAX_TOTAL_ENTITIES` 限制逻辑实体；`LLM_MAX_PROVIDER_REQUESTS` 独立限制包含 retry/fallback 的真实请求。
- 任务级 BudgetManager 在每次 HTTP 发送前使用锁原子预留请求额度，缓存命中不消耗请求预算。
- 缓存键：provider、model、prompt_version、task_type、脱敏后的 input_hash。

## 输出与接口

新增 `llm_explanations.json`，包含 mode、consent、status、双预算、usage、skipped entities、evidence catalog、四类解释和 warnings。每项 metadata 包含 provider/model、latency、token usage、input hash、截断、缓存和生成时间。

新增 `GET /llm/public-config`，只返回非敏感配置。前端分别展示逻辑实体上限和真实请求上限，并说明两者不同；AI 卡片始终位于规则内容之后。

## 测试与验收

- 自动测试只使用 MockProvider 或 MockTransport，禁止真实网络。
- 覆盖 consent、配置优先级、Provider capabilities、主备回退、双预算原子性、隐私脱敏、Prompt Injection、evidence、缓存、四节点和 rule 回归。
- `scripts/smoke_llm.py` 只用于手动真实连通性验证，不进入 pytest、validate 或 CI。
- 后端 pytest、前端测试、生产构建和 `scripts/validate.sh` 必须通过。
