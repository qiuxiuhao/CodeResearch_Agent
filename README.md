# CodeResearch Agent

CodeResearch Agent 是一个面向代码仓库与论文的本地优先研究平台。当前开发线为 **v2.0.0**，可复现的稳定基线为 `v1.9.0`（Commit `d869f88e2c0132fae7cf52adc7def28f946751c1`）。

当前交付状态必须严格区分：

- **Local CPU Profile**：受支持的单机路径，使用 SQLite、LocalArtifactStore、InProcessJobBackend 和本地 Qdrant/FastEmbed。
- **AutoDL CUDA Team Profile**：正在完善的私有单机验收路径，目标是 PostgreSQL、Redis、MinIO、Qdrant、Celery、Supervisor 和一个共享 GPU 推理进程；尚不能作为公开多人生产服务。
- **Docker Team Profile**：保留为其他长期服务器的参考部署，仍需完成真实 Compose、迁移、故障注入和恢复门禁。
- Alignment 真实双标 Gold 尚未提供，状态为 `ALIGNMENT_BENCHMARK_PENDING`，因此 v2.0 RC/GA 仍被阻断。

系统已有结构化索引、Hybrid Retrieval、Research Agent、论文代码 Alignment、统一 Trace、Evaluation/Regression 和 Bad Case 合同。生成式文本/VLM/图片默认调用受控远端 Provider；本地 CPU 或 RTX 4090 只承载 Dense Embedding、BM25 和 Reranker，不加载本地大语言模型。

## 1. 平台要求

共同要求：

```text
Python 3.11
Node.js 20+（已在 Node 24 验证）
npm
Git
至少 5 GiB 可用空间（Local）
```

Local 推荐 8 GiB 以上内存。AutoDL Team 验收要求 Linux x86_64、CUDA 12.x、cuDNN 9、至少 8 CPU 核、32 GiB RAM、100 GiB 可用数据盘和单卡 RTX 4090 24 GiB。

项目不依赖 `.env` 启动。配置来自显式 YAML，Secret 由系统 Keychain 或受保护的加密文件管理。旧环境变量仅作为兼容覆盖，并会产生弃用提示。

## 2. 获取源码与基础检查

```bash
git clone <your-repository-url> CodeResearch_Agent
cd CodeResearch_Agent
git status --short
git tag --points-at HEAD
```

不要把 `data/models/`、`data/artifacts/`、数据库、输出目录或任何 Secret 提交到 Git。

## 3. Mac / CPU Local Profile

### 3.1 创建环境

```bash
conda create -n cra-v2-local python=3.11 pip -y
conda activate cra-v2-local
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements-cpu.txt
python -m pip install --no-deps -e .
python -m pip check
```

开发和测试工具另装在同一环境：

```bash
python -m pip install --require-hashes -r requirements-dev.txt
```

前端使用锁文件恢复：

```bash
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

### 3.2 校验配置与下载权重

```bash
cra config validate --config config/local-cpu.yaml
cra doctor --config config/local-cpu.yaml
cra models prefetch --config config/local-cpu.yaml
cra models verify --config config/local-cpu.yaml
```

`prefetch` 是安装阶段唯一需要模型网络访问的步骤。下载后，请在离线状态再次执行 `verify`。默认 Manifest 固定以下模型的不可变 revision：

```text
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
Qdrant/bm25
BAAI/bge-reranker-base
```

可选 Jina Code Dense 不随默认下载；需要时增加 `--include-optional`。当前默认模型缓存实测约 1.3 GiB，实际空间会随上游文件布局和缓存元数据变化。

### 3.3 Secret 与首个管理员

macOS 默认使用系统 Keychain：

```bash
cra secrets set --config config/local-cpu.yaml --provider deepseek
cra secrets list --config config/local-cpu.yaml
```

命令会交互读取 API Key，不要把 Key 放进 shell 历史、YAML 或 Git。没有真实 Provider 时仍可运行规则分析、Mock 测试和离线评测；系统不会自动发起付费请求。

创建一次性 Bootstrap Token：

```bash
cra auth bootstrap-token --config config/local-cpu.yaml --ttl-hours 24
```

保存终端输出，服务启动后只使用一次：

```bash
curl -X POST http://127.0.0.1:8000/api/v2/auth/bootstrap \
  -H 'Content-Type: application/json' \
  -H 'X-Bootstrap-Token: <one-use-token>' \
  -d '{"username":"owner","password":"replace-with-a-long-password"}'
```

### 3.4 启动

构建前端后，由 FastAPI 同端口提供 API；开发期也可单独运行 Vite。

```bash
CRA_SERVE_FRONTEND=true \
CRA_FRONTEND_DIST="$PWD/frontend/dist" \
cra serve --config config/local-cpu.yaml
```

打开：

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/api/v2/health
http://127.0.0.1:8000/health
```

开发前端：

```bash
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

Local 默认使用 CPU，不启用 MPS，也不会静默切换 CUDA。

## 4. Local 使用流程

登录后，通过 `/api/v2` 创建 Workspace、Project 和 Artifact，再提交 Job。统一 Job 类型包括：

```text
analysis, indexing, research, alignment, evaluation,
replay, export, backup, restore, maintenance, delete
```

Analysis/Index 只接受状态为 `available` 的仓库 Artifact；论文同理。Job、Attempt、Outbox 和 Run 控制状态位于 `data/control_plane.sqlite3`，派生数据库、Checkpoint、Trace 与文件系统 Artifact 不属于同一个原子事务。

备份与恢复 Job 通过 ArtifactRef 传递结果。Restore 先写入隔离目录并校验 SQLite 完整性，不会覆盖当前运行目录。

## 5. AutoDL RTX 4090 私有 Team 验收

这条路径适用于本人私有验收，不承诺公网多人生产。只暴露端口 6006；PostgreSQL、Redis、MinIO、Qdrant 和 GPU Unix Socket 都必须绑定本机。

数据布局：

```text
/root/autodl-tmp/cra/
  artifacts/
  backups/
  envs/
  logs/
  models/
  run/
  secrets/
  services/
```

### 5.1 初始化 Python、前端和模型

```bash
cd /root/CodeResearch_Agent
export CRA_DATA_ROOT=/root/autodl-tmp/cra
export CRA_REPO_ROOT=$PWD
bash deploy/autodl/bootstrap.sh
```

脚本使用 Python 3.11、`requirements-gpu-cu12.txt` 和 `requirements-team.txt` 的 Hash 锁安装。CPU 版 FastEmbed/ORT 与 GPU 版不能混装。

### 5.2 原生基础服务

AutoDL 普通实例不依赖嵌套 Docker。先安装 PostgreSQL 与 Redis，再为 MinIO、Qdrant 提供经过人工冻结的 URL 和 SHA-256：

```bash
export MINIO_BINARY_URL='<immutable-https-url>'
export MINIO_BINARY_SHA256='<sha256>'
export QDRANT_BINARY_URL='<immutable-https-url>'
export QDRANT_BINARY_SHA256='<sha256>'
bash deploy/autodl/install-services.sh
```

随后必须按运维 Runbook 初始化数据库、五类数据库角色、RLS、Bucket、Redis Auth 和 Secret 引用。当前脚本不会猜测生产密码或下载未固定校验和的二进制。

### 5.3 CUDA 验收

```bash
/root/autodl-tmp/cra/envs/cra-v2/bin/cra config validate \
  --config config/team-autodl-gpu.yaml
/root/autodl-tmp/cra/envs/cra-v2/bin/cra doctor \
  --config config/team-autodl-gpu.yaml
/root/autodl-tmp/cra/envs/cra-v2/bin/cra models verify \
  --config config/team-autodl-gpu.yaml
```

`doctor` 必须显示 `CUDAExecutionProvider` 为首选 Provider。CUDA 配置下 GPU 不可用时启动应失败；禁止静默回退 CPU。Supervisor 只启动一个共享推理 Runtime，领域 Worker 通过 Unix Socket 调用，避免重复加载显存。

### 5.4 启停

```bash
bash deploy/autodl/start.sh
bash deploy/autodl/status.sh
bash deploy/autodl/backup.sh
bash deploy/autodl/restore-verify.sh /root/autodl-tmp/cra/backups/<window>
bash deploy/autodl/stop.sh
```

入口为：

```text
http://127.0.0.1:6006/
http://127.0.0.1:6006/api/v2/health
```

请通过 AutoDL 的端口代理访问 6006，不要把数据库、Broker、对象存储或 Qdrant 直接暴露到公网。

> 重要：Team 的 Analysis/Index Worker 已有真实执行路径；Research、Alignment、Evaluation、Replay、Export、Backup/Restore 的 Team Worker、Team 身份/API、完整 PostgreSQL Domain/Trace/Checkpoint 迁移仍在开发。未完成这些门禁前，不得把本节视为生产部署证明。

## 6. CPU / CUDA 计算边界

| 能力 | Mac Local | RTX 4090 Team |
|---|---|---|
| Python AST、报告、BM25 | CPU | CPU |
| SQLite/PostgreSQL/Redis/Qdrant | CPU | CPU |
| Dense Embedding | ONNX CPU | ONNX CUDA |
| Reranker | ONNX CPU | ONNX CUDA |
| Research/Alignment 生成模型 | 受控远端 Provider | 受控远端 Provider |
| VLM/图片模型 | 受控远端 Provider | 受控远端 Provider |
| 本地 LLM / MPS | 不支持 | 不支持 |

CUDA 仅用于 Dense 与 Reranker。Worker 不把每次 Provider 调用拆成嵌套 Celery 任务。

## 7. 验证与测试

默认自动测试无网络、无付费 Provider：

```bash
python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
bash scripts/validate.sh
```

专项验证：

```bash
python -m pytest -q tests/control_plane
python scripts/validate_alignment_gold.py
bash scripts/release_security_gate.sh
```

Release Security Gate 依赖 `pip-audit`、`gitleaks`、`trivy`、SBOM/License 工具与固定镜像 Digest。缺少工具时必须报告未执行，不能把跳过当通过。

真实 Provider Smoke Test 必须单独获得 Consent 与预算：

```bash
python scripts/smoke_llm.py
python scripts/smoke_vlm.py
python scripts/smoke_image.py
```

不要在 CI 或普通启动过程中执行这些脚本。

## 8. 依赖锁维护

`pyproject.toml` 保存包元数据；安装使用分层、带 Hash 的 requirements：

```text
requirements.txt
requirements-cpu.txt
requirements-gpu-cu12.txt
requirements-team.txt
requirements-dev.txt
requirements/*.in
```

更新必须从对应 `.in` 文件重新生成锁，而不是直接手改解析结果。CPU 与 GPU 锁需分别在全新 Python 3.11 Conda 环境执行 `pip check` 和真实推理验证。源码最后用：

```bash
python -m pip install --no-deps -e .
```

## 9. 配置与兼容环境变量

配置优先级：

```text
命令行 --config → YAML → 代码默认值
```

示例：

```text
config/default.yaml
config/local-cpu.yaml
config/team-autodl-gpu.yaml
config/models.yaml
```

Team 配置中的数据库、对象存储和 Secret 值是部署模板，不是可以直接用于公网的凭据。不要提交真实 Secret。`.env.example` 只记录 v1 兼容边界，不是安装指南。

## 10. 数据、备份与升级

- Local：同步 Control/Domain SQLite、Artifact、签名密钥和仍需恢复的 Active Checkpoint。
- Team：PostgreSQL PITR、独立 Artifact Backup、Secret Backup 和一致性 Manifest 缺一不可；Redis 和 Qdrant 不是权威恢复源。
- Restore 必须先进入隔离环境并完成 Hash、Schema、RLS 和业务等价验证。
- 升级遵循 Expand → 兼容 API/Worker → Drain → Contract；不能在旧 Worker 或旧消息未清空时删除字段。
- AutoDL 本地盘不作为可靠冗余，需把 Backup Artifact 同步到独立 OSS/Bucket。

## 11. 已知发布阻断项

完整、实时清单见 [plan/need.md](plan/need.md)。主要阻断项包括：

- Team 全领域 Worker、Team Identity/API 和 PostgreSQL Domain/Trace/Checkpoint 的真实集成验收。
- 原生 PostgreSQL/Redis/MinIO/Qdrant 初始化、PITR、故障注入和完整 AutoDL Journey。
- Local 与 Team 的完整业务等价 E2E。
- 真实六组 repo-paper、92 条双标/仲裁 Alignment Gold。
- 供应链、SBOM、镜像、迁移兼容和恢复门禁。

## 12. 设计与计划文档

- [v2.0 实施计划](plan/plan_v2.0.0.md)
- [v2 部署边界](docs/deployment_v2.md)
- [v2 安全边界](docs/security_v2.md)
- [v1.9 基线](docs/baseline_v1.9.0.md)
- [依赖、模型和缺口审计](plan/need.md)

任何 Trace、Evaluation 或模型输出都不能替代业务事实、人工 Gold 或权限判断。
