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
