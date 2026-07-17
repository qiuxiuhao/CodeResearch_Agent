# 验收说明

## 完整验收

```bash
bash scripts/validate.sh
```

该脚本会依次执行：

1. 后端 pytest。
2. 前端依赖安装。
3. 前端测试。
4. 前端生产构建。

前端构建先分别对 app 与 `vite.config.ts` 执行 no-emit typecheck，再执行 Vite。构建契约会验证 Mermaid 只作为动态 chunk 加载，并拒绝 `vite.config.js`、`vite.config.d.ts` 或 `*.tsbuildinfo` 生成物。

自动验收禁止真实模型网络请求。Provider 测试使用 MockProvider/MockTransport。

真实 API 仅可手动验证，例如：

```bash
python scripts/smoke_llm.py --provider deepseek --i-understand-cost
python scripts/smoke_vlm.py --provider qwen_vl --i-understand-cost
python scripts/smoke_image.py --provider qwen_image --i-understand-cost
```

该命令可能产生费用，不属于 `validate.sh`。

Vision 自动测试使用 MockVisionProvider，并覆盖 Figure 提取、稳定 ID、bbox、独立 consent、结构化校验、预算、缓存和 fallback。`smoke_vlm.py` 默认只发送无敏感信息的合成架构图；`--probe-json-object` 仅用于手动验证供应商能力，不会自动修改配置。

教学图自动测试使用本地 Skeleton/Blueprint、MockImageProvider 和 MockVisionProvider，不访问真实图片生成或 VLM 服务。`smoke_image.py` 只发送无敏感合成 TeachingDiagramSpec，并要求显式费用确认。

## 手动命令

后端：

```bash
python -m pytest -q
```

前端：

```bash
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

## 启动检查

```bash
bash scripts/dev.sh
```

然后打开：

```text
http://127.0.0.1:5173
```

后端健康检查：

```text
http://127.0.0.1:8000/health
```

## 演示检查

- 使用 `examples/small_pytorch_project.zip` 创建任务。
- 确认 `tests/test_example_archive_contract.py` 验证展开示例、临时确定性 ZIP 和已提交 ZIP 内容一致。
- 确认总览、文件、函数、当前任务库函数说明、全局函数库、模型、图示和报告页面可以加载。
- 切换零基础模式，并打开一个库函数解释弹窗。

## 提交前清理

```bash
bash scripts/clean.sh
```

该命令只清理 Python 缓存/egg-info 与前端依赖、构建和 typecheck 产物。它不删除 `data/*.sqlite3`、`outputs/task_*`、用户报告、教学图、全局函数知识库或 Provider Secret。

破坏性运行数据重置与日常清理分离：

```bash
bash scripts/reset_runtime_data.sh --confirm-delete-runtime-data
```

`reset_runtime_data.sh` 只有在收到上述完整参数时才会删除 `data/*.sqlite3*` 和 `outputs/task_*`。执行前会列出目标并警告全局函数知识库、任务报告和教学图将丢失；Provider Secret 不会被删除。
