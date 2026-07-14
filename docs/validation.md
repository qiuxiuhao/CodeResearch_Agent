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
- 确认总览、文件、函数、当前任务库函数说明、全局函数库、模型、图示和报告页面可以加载。
- 切换零基础模式，并打开一个库函数解释弹窗。

## 提交前清理

```bash
bash scripts/clean.sh
```
