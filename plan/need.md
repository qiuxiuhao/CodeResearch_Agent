# CodeResearch Agent v2.0：依赖、模型与未完成能力清单

更新日期：2026-07-19

分支：`upgrade/v2.0-production-infrastructure`

HEAD：`d869f88e2c0132fae7cf52adc7def28f946751c1`

Tag：`v1.9.0`

工作树：包含未提交 v2.0 开发改动，不是正式 Release 基线

本文件只记录实际检查到的事实。依赖锁、Schema 或静态测试存在，不等于对应生产服务、故障恢复或真实模型路径已经验收。

## 1. 当前结论

### 已确认

- Local CPU 开发环境为 `/Users/qiu_star/miniforge3/envs/cra-v2-local`，Python 3.11.15，`pip check` 通过。
- 前端 Node v24.15.0，锁定依赖可安装，Vitest、typecheck 和生产 build 可运行。
- CPU Retrieval 依赖已经安装：`qdrant-client 1.18.0`、`fastembed 0.8.0`、`onnxruntime 1.27.0`。
- 默认 Dense、BM25 与 Reranker 已由 `cra models prefetch` 下载并由 Manifest 校验；`data/models` 当前约 1.3 GiB。
- BM25 `cache_dir` 构造缺陷已修复；模型加载错误不再由原宽泛异常完全静默吞掉。
- Local Control Plane、Job/Attempt/Outbox、Artifact、身份与权限合同已存在；Local Analysis 垂直链路以及 Local Export/Backup/隔离 Restore/Delete 有自动测试。
- Local Runtime 已注册 11 类 Job：Analysis、Indexing、Research、Alignment、Evaluation、Replay、Export、Backup、Restore、Maintenance、Delete。
- 分层 Hash 锁已创建：公共、CPU、CUDA 12、Team 和 Dev。
- Team Hash 锁已在全新 Python 3.11.15 临时环境安装并通过 `pip check`；该检查发生在 macOS arm64，仍需在 Linux x86_64 + CUDA 12/cuDNN 9 重新做目标平台安装与推理验收。
- 当前工作树完整后端回归：`483 passed，6 warnings`（2026-07-19，Python 3.11.15）。
- 当前前端回归：`19 files / 32 tests passed`；TypeScript typecheck、Vite build与build contract通过。

### 未确认或未完成

- Team Profile 仍不能被描述为完整生产交付。
- Team 目前只有 Analysis/Index Worker 的真实领域执行路径；Research、Alignment、Evaluation、Replay、Export、Backup、Restore 仍返回稳定的 `team_<job>_handler_unavailable` 终态错误。
- Team Identity/API 尚未接入 PostgreSQL；当前 v2 API 的身份和大部分资源路径仍要求 Local Store。
- PostgreSQL Domain Store、Observability 分区 Store、Postgres Checkpoint 的完整迁移和集成测试未完成。
- Provider Reservation、Budget Ledger、跨 Worker 并发控制未接入真实 Provider 调用。
- AutoDL 原生脚本尚未完成 PostgreSQL/Redis 初始化、数据库角色/RLS迁移、MinIO Bucket、Secret注入和真实 Supervisor Journey。
- Compose 尚未完成不可变镜像 Digest、GPU Runtime、完整初始化、PITR和故障注入验证。
- 完整 `/api/v2`、SDK、CLI、前端管理面与 Local/Team 全流程等价测试尚未完成。
- `ALIGNMENT_BENCHMARK_PENDING` 未关闭：缺少真实六组 repo-paper、92 条双标/仲裁 Gold。

因此当前代码可作为 v2 开发工作树使用，不能宣称 v2.0 GA、Team Production Ready 或 Alignment Quality 完成。

## 2. 依赖交付

安装时不要混用 CPU 与 CUDA 锁：

```text
requirements.txt             公共运行依赖
requirements-cpu.txt         CPU FastEmbed / ONNX Runtime / Qdrant
requirements-gpu-cu12.txt    CUDA FastEmbed / ONNX Runtime GPU / Qdrant
requirements-team.txt        PostgreSQL / Redis / Celery / S3 / Postgres Checkpoint / OTel / Supervisor
requirements-dev.txt         pytest、锁生成和开发工具
requirements/*.in            pip-tools 输入
```

源码安装固定使用：

```bash
python -m pip install --no-deps -e .
```

### 当前 Mac 环境

| 依赖 | 版本/状态 |
|---|---|
| `fastapi` | 0.139.0 |
| `uvicorn` | 0.50.2 |
| `langgraph` | 1.2.8 |
| `qdrant-client` | 1.18.0 |
| `fastembed` | 0.8.0 |
| `onnxruntime` | 1.27.0 |
| `pytest` | 9.1.1 |
| `psycopg` / `celery` / `redis` / `boto3` / `supervisor` | 未装入 Local 环境，符合 Profile 隔离 |

Team 包不应装入 Local 环境。它们由 `requirements-team.txt` 安装到独立 AutoDL/Team Python 3.11 环境。

### 仍需在目标机安装的非 Python 组件

AutoDL Team：

```text
PostgreSQL server/client
Redis server/client
MinIO server + mc
Qdrant server
CUDA 12.x / cuDNN 9 / NVIDIA driver
Supervisor（Python Team 锁已包含）
```

Release/供应链：

```text
pip-audit
gitleaks
trivy
SBOM generator（如 syft）
License/Notice generator
```

不能把“Hash 锁可安装”解释为上述系统服务已经启动或通过故障恢复。

## 3. 模型和空间

默认 Manifest：`config/models.yaml`。所有默认模型使用不可变 revision；安装阶段可联网，应用请求阶段必须离线并验证 Hash。

| 角色 | 模型 | 当前 Mac 状态 | 执行设备 |
|---|---|---|---|
| Dense | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 已缓存并校验 | CPU / CUDA |
| Sparse | `Qdrant/bm25` | 已缓存并校验 | CPU |
| Reranker | `BAAI/bge-reranker-base` | 已缓存并校验 | CPU / CUDA |
| Code Dense | Jina Code Profile | 可选，默认未下载 | CPU / CUDA |

当前默认缓存实测：

```text
data/models: 约 1.3 GiB，134 个文件（实测时点）
```

建议空间预算：

```text
Local 最小运行与模型：5 GiB 可用空间
Local 完整开发（环境、node_modules、缓存、输出）：10～20 GiB
AutoDL Team 最低检查：100 GiB 可用数据盘
```

模型命令：

```bash
cra models prefetch --config config/local-cpu.yaml
cra models verify --config config/local-cpu.yaml
cra models prefetch --include-optional --config <config>
```

CUDA 正式验收必须证明：

- `CUDAExecutionProvider` 是 Dense/Reranker 实际首选 Provider。
- `nvidia-smi` 显示推理期间 GPU 利用率/显存变化。
- 仅有一个共享 GPU Runtime 模型副本。
- GPU 不可用、模型 Hash 错误或显存不足时稳定拒绝，不静默退到 CPU。

当前 Mac 无 NVIDIA GPU，因此没有完成这项真实验收。

## 4. Provider 和人工输入

远端 DeepSeek/Qwen/VLM/图片 Provider 不需要本地权重，但需要用户自行提供：

```text
API Key
Provider endpoint/model/revision
明确 Consent
Token/成本 Budget
联网权限
```

使用：

```bash
cra secrets set --config <config> --provider <provider>
cra secrets list --config <config>
```

不要把 Secret 放入 YAML、`.env`、Celery Message、Trace、日志或 Git。默认 CI 不调用真实 Provider。

人工输入且当前缺失：

- 六组具备授权的 repo-paper Fixture。
- 92 条 Alignment 双人标注与仲裁 Gold。
- AutoDL 的 PostgreSQL/Redis/MinIO/OIDC/Provider Secret。
- MinIO/Qdrant 不可变下载 URL、SHA-256或正式包源。
- 生产域名、TLS、OIDC issuer/client、备份位置、Object Lock和实际 RPO/RTO。

这些输入缺失不妨碍继续开发 Mock/Fixture 功能，但 Alignment Gold 缺失阻断 RC/GA。

## 5. Local Profile 缺口

### 5.1 已实现合同

- 严格 YAML `ApplicationConfig`、CPU/CUDA互斥配置、`cra config validate` 与 `cra doctor`。
- Local Keychain Secret、一次性 Bootstrap、Session Rotation/Reuse、CSRF和基础Workspace/Project RBAC。
- Control Plane SQLite 中 Job/Attempt/Outbox 原子创建。
- Retryable Attempt自动进入Retry，人工Retry创建新Job；Late Result使用Execution Token保护。
- Artifact流式Hash/大小限制，Archive/PDF校验与隔离存储合同。
- Local 11类Job注册；Analysis/Index、Export、Replay、Backup、Restore、Maintenance、Delete具备处理器。

### 5.2 仍需完成或加强

- Research、Alignment、Evaluation 在统一 Job Context 下彻底移除旧 Coordinator 双调度风险并补齐 E2E。
- Git Clone 的真实网络沙箱、DNS rebinding/SSRF二次校验、LFS/Submodule上限和跨平台进程隔离。
- PDF解析的独立低权限进程、CPU/内存限制和恶意样本集。
- OIDC Authorization Code + PKCE 的真实 Provider 集成与回调测试。
- 全部 Workspace/Project Membership/Grant 管理 API、Audit查询和敏感权限矩阵。
- Evaluation六Adapter使用真实冻结 Fixture 的端到端结果；当前合成 Fixture不能代替质量 Gold。
- Local完整 Journey脚本：Bootstrap→Artifact→Analysis→Index→Research→Alignment→Evaluation→Backup→隔离Restore。
- Delete/Retention引用保护、Legal Hold和大型Artifact补偿的持久状态机。

## 6. Team / AutoDL 缺口

### P0：启动和权威状态

- PostgreSQL 初始化/迁移脚本、`cra_api/cra_worker/cra_scheduler/cra_migrator/cra_auditor`角色、FORCE RLS和受控Claim函数的真实数据库测试。
- Team Identity、Session、Workspace/Project API与S3 Artifact API。
- Control/Domain、Observability、Checkpoint独立连接池与故障隔离。
- Dispatcher/Worker Registry版本兼容、Outbox重复发布、Worker Lost、Redis Flush和Late Result的真实集成测试。
- Research、Alignment、Evaluation、Replay、Export、Backup、Restore Team Handler。
- Provider Reservation、Usage Ledger、Workspace Budget/Concurrency权威结算。

### P0：GPU Runtime

- Linux 4090 上安装 GPU/Team锁并验证CUDA 12/cuDNN 9。
- Dense/Reranker真实CUDA请求、批处理、请求/队列上限、显存水位、超时和优雅重载。
- Worker Unix Socket权限、负载测试、Runtime重启和OOM故障注入。

### P1：运维

- 原生 PostgreSQL、Redis、MinIO、Qdrant初始化、健康检查和Secret注入。
- Supervisor全部进程的启动顺序、依赖健康、日志轮转和优雅停机。
- PostgreSQL Base Backup/WAL/PITR、Artifact/Secret Backup、一致性Manifest和隔离Restore。
- AutoDL数据同步独立OSS；本地盘不能作为唯一备份。
- Local→Team Dry Run、ID映射、Hash验证、Qdrant重建、Cutover和回滚。
- Compose的固定镜像Digest、非Root容器、GPU Runtime与完整初始化。

## 7. API、前端和发布缺口

- `/api/v2` 当前只覆盖 Local身份、Workspace/Project、Artifact和Job核心路径；Team路径与全资源管理未完成。
- 前端 Job Center 可以登录、选择Workspace/Project、查看Job/Attempt和Cancel/Retry；其余Catalog、Provider、Audit、Backup、Migration、Worker/Quota页面未完成。
- 仍有v1 Client和caller-scope兼容逻辑，尚未完成统一清理与弃用期合同。
- SSE→数据库轮询回退、Session设备管理、完整Permission Denied和大列表虚拟化仍需验收。
- Python SDK、TypeScript生成类型、CLI全资源命令与OpenAPI Snapshot未完成。
- Release Gate尚未生成正式SBOM、License/Notice、镜像Digest、迁移兼容和Restore报告。

## 8. 下一步实施顺序

1. 在当前分支完成完整后端、前端、build、`validate.sh`，记录本次真实结果。
2. 修复测试发现的问题；未经用户明确授权不提交当前Dirty Worktree。
3. 完成 Local CPU完整Journey和统一Job上下文，再冻结Local支持边界。
4. 在目标AutoDL Python 3.11/CUDA 12环境验证GPU/Team Hash锁和真实CUDA推理。
5. 完成Team数据库初始化、Identity/API、S3、全领域Handler与Provider Ledger。
6. 执行Redis/Worker/GPU/DB/Artifact故障注入、PITR与隔离Restore。
7. 完成前端/API/SDK、供应链Gate和Local/Team业务等价。
8. 最后由人工提供Alignment Gold，关闭`ALIGNMENT_BENCHMARK_PENDING`后才进入RC/GA。

## 9. 不得误报

- 不得把Local自动测试当成Team生产证明。
- 不得把合成Fixture、Legacy Alignment或LLM输出称为人工Gold。
- 不得把模型文件存在称为CUDA已生效。
- 不得把Celery消息或Redis状态当业务权威状态。
- 不得把S3 Versioning称为完整备份。
- 不得把未执行的安全工具记录为通过。
- 不得把当前未提交工作树当正式v2.0发布基线。
