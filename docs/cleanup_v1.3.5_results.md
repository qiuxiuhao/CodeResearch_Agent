# v1.3.5 审计与轻量化结果

## 实施边界

- 稳定 checkpoint：`v1.3.4-stable -> ce4f1ee`。
- A01–A11、Prompt Registry/A14、前端构建、Provider 配置、B02/B04/B05、兼容入口、Narrative Schema 和文档分批提交，可独立 revert。
- B03 未引入新 helper：三个 Router 的 cache key、Schema、下载和异常语义不同，抽取需要 callback/状态协议与额外分支，不满足“净代码量和复杂度下降”门槛。
- 未删除纯规则离线路径、LangGraph 顺序 fallback、Blueprint/Mermaid/Provider fallback、Mock Provider、安全检查或历史缓存校验。

## 最终指标

| 指标 | v1.3.4 基线 | v1.3.5 最终候选 | 说明 |
|---|---:|---:|---|
| Python 文件 | 177 | 186 | 新增契约/安全测试和确定性 ZIP helper；不以文件数驱动删除 |
| TypeScript/TSX 源文件 | 54 | 52 | 删除未挂载组件 |
| Python/TS/TSX/CSS 行数 | 25,053 | 25,215 | 净增量为 contract、安全与兼容覆盖；行数不作删除目标 |
| 直接运行时依赖 | 后端 7、前端 6 | 后端 7、前端 4 | Vite 和 React plugin 回归 devDependencies |
| 前端构建产物 | 3,684,247 B | 3,710,015 B | +0.70%，未达 10% warning |
| 首屏 entry JS | 885.63 kB / gzip 230.85 kB | 262,274 B / gzip 80,129 B | Mermaid 移出首屏静态依赖 |
| 后端测试 | 179 passed | 199 passed | 数量仅作参考，新增契约覆盖 |
| 前端测试 | 26 passed | 29 passed | 新增 Mermaid 按需加载/卸载/fallback 覆盖 |
| 后端全量测试中位数 | 43.36 s | 43.408 s | warm-up + 9 次，+0.11% |
| 前端测试中位数 | 1.29 s | 1.360 s | warm-up + 9 次，+5.43% |
| 后端启动 import 中位数 | 0.2451 s | 0.2409 s | warm-up + 9 次，-1.71% |
| 纯规则离线样例中位数 | 未记录 | 1.3609 s | warm-up + 9 次，生成完整 report |
| 前端 build 中位数 | 未记录 | 5.007 s | warm-up + 9 次，包含 no-emit typecheck 和 manifest contract |
| Git 跟踪文件 ZIP | 470,723 B | 472,603 B（批次 7） | 只记录，不驱动删除；最终 tag 大小在发布交接中记录 |

## 契约结果

- Prompt Registry 与 Prompt 目录一一对应，Node 不再使用散落文件名。
- app 与 Vite 配置分别 no-emit typecheck；连续 build 不产生 `vite.config.js`、声明文件或 `tsbuildinfo`。
- Mermaid 仅在图示挂载后通过 `import("mermaid")` 加载，卸载后迟到结果不写状态/DOM，失败保留源码 fallback。
- `ResolvedAnalysisOptions` 是可 JSON round-trip 的纯数据；`ProviderRuntimeContext` 不进入 AgentState/任务输出/缓存或日志。
- `supports_async` 仅保留 deprecated 公开请求字段；未传或 `false` 接受但不持久化，`true` 返回 422。
- Narrative prompt/schema/cache 版本均为 1.3.5，旧 v1.3.3 Narrative 缓存确定 miss；其他 Teaching Diagram Schema 保持不变。
- 展开示例是事实源，提交 ZIP 与源码路径集合和逐文件 SHA-256 一致，临时 ZIP 字节级确定。
