# v1.5 / v1.6 / v1.7 依赖、模型权重与人工准备清单

最后核对：2026-07-18

环境：Conda `code-research-agent`
项目：`/Users/qiu_star/Desktop/own_project/CodeResearch_Agent`

本文只记录项目当前仍需人工安装、下载或配置的内容。自动测试不得下载真实模型，也不得调用
真实 Provider。

## 一、当前实际状态

### 已安装

当前 Conda 环境已经具备 v1.6 Research Agent 的持久化依赖：

```text
langgraph                         1.2.8
langgraph-checkpoint-sqlite       3.1.0
aiosqlite                         0.22.1（传递依赖）
sqlite-vec                        0.1.9（传递依赖）
```

`pyproject.toml` 已提供：

```text
agent extra: langgraph-checkpoint-sqlite>=3.1.0,<3.2.0
dev extra:   langgraph-checkpoint-sqlite>=3.1.0,<3.2.0
```

因此当前环境不需要再次补装 v1.6 Checkpointer。新建环境时仍需执行：

```bash
conda activate code-research-agent
cd /Users/qiu_star/Desktop/own_project/CodeResearch_Agent
pip install -e '.[agent]'
```

### 当前未发现

实际检查中，当前 Conda 环境未发现以下可选 Retrieval 包：

```text
qdrant-client
fastembed
onnxruntime
```

项目目录中也未发现已经准备好的：

```text
data/models 下的模型缓存
data/qdrant 下的 Qdrant Local 数据
```

这里只能确认项目指定目录中没有资源；不代表用户机器上的其他 Hugging Face/FastEmbed 全局
缓存一定不存在。

## 二、按使用目标判断是否需要补充

| 使用目标 | 还需要安装/下载 | 是否阻塞 |
| -- | -- | -- |
| SQLite FTS5 + Graph 检索 | 无模型 | 不阻塞 |
| v1.6 本地确定性 Planner/Answer fallback | 无模型 | 不阻塞 |
| v1.6 SQLite checkpoint、恢复和取消 | 当前环境已安装 | 不阻塞 |
| Dense Retrieval | `retrieval` extra + 默认 Embedding 权重 | 尚未准备 |
| 真实 Reranker | `retrieval` extra + Reranker 权重 | 尚未准备，可选 |
| Qdrant BM25 Sparse | `retrieval` extra + `Qdrant/bm25` | 当前代码问题未修复前不要启用 |
| 外部 LLM Planner/Answer | Provider 凭据、授权和预算配置 | 不需要下载本地权重 |

如果只使用 FTS5、Graph、Evidence-only 回答和本地确定性 Agent，不需要下载任何模型。

## 三、Dense Retrieval 最小准备

### 1. 安装 Retrieval extra

```bash
conda activate code-research-agent
cd /Users/qiu_star/Desktop/own_project/CodeResearch_Agent
pip install -e '.[retrieval]'
```

该 extra 当前为：

```text
qdrant-client[fastembed]>=1.9.0,<2.0
```

它会带入 Qdrant Client、FastEmbed、ONNX Runtime 等传递依赖。当前采用 Qdrant Local，不需要
单独安装 Qdrant Server。

### 2. 默认 Dense Embedding 权重

```text
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

- 用途：默认 Dense Retrieval，重点支持中文问题检索英文代码。
- 向量维度：384。
- 近似下载大小：220 MB。
- 项目默认缓存目录：`data/models`。
- 覆盖变量：`RETRIEVAL_MODEL_CACHE_DIR`。

完成默认 Dense 手工验收时，这是唯一必需的模型权重。

项目目前没有专用的模型 prefetch CLI。应在受控、允许联网的准备步骤中通过 FastEmbed 完成
一次预缓存，确认文件进入 `RETRIEVAL_MODEL_CACHE_DIR` 后，再设置：

```bash
export RETRIEVAL_OFFLINE=true
export RETRIEVAL_DENSE_ENABLED=true
```

不得依赖 API 请求期间隐式下载模型。

## 四、按需准备的其他权重

### 1. 默认 Reranker

```text
BAAI/bge-reranker-base
```

- 用途：中英文 Cross-Encoder Reranker。
- 近似下载大小：1 GB。
- 仅在 `RETRIEVAL_RERANKER_ENABLED=true` 时需要。
- 缺失、离线或推理失败时，系统回退到 Final RRF。
- 当前不是 v1.6 Agent 主链路启动的必需项。

### 2. Qdrant BM25 Sparse

```text
Qdrant/bm25
```

- 用途：Qdrant named sparse vector 消融实验。
- 仅在 `RETRIEVAL_QDRANT_SPARSE_ENABLED=true` 时需要。
- SQLite FTS5 已提供零模型 Sparse baseline，因此它不阻塞发布。

当前仍存在实际代码问题：`backend/app/retrieval/api.py` 实例化
`QdrantBM25SparseProvider()` 时没有传入构造函数必需的 `cache_dir`。由于 optional factory 会
捕获异常，当前表现通常是该向量服务不可用并回退，而不是成功启用 Qdrant Sparse。

在修复该参数、补充专项测试并重新验收前：

```text
不要启用 RETRIEVAL_QDRANT_SPARSE_ENABLED
不需要提前下载 Qdrant/bm25
```

### 3. 代码专用 Dense 消融候选

```text
jinaai/jina-embeddings-v2-base-code
```

- 向量维度：768。
- 近似下载大小：640 MB。
- 仅用于与默认多语言模型进行消融。
- 切换后必须创建新的 `vector_profile_hash`、Collection 和 Vector Generation。
- 不能复用默认 384 维模型的向量索引。

### 4. 轻量英文 Reranker 消融候选

```text
Xenova/ms-marco-MiniLM-L-6-v2
```

- 近似下载大小：80 MB。
- 主要用于英文检索延迟对照。
- 不作为默认中英文 Reranker。

## 五、v1.6 Research Agent 不需要新增的权重

v1.6 没有新增本地 Planner、Answer Generator 或 Claim Verifier 权重。

- 未授权外部文本时，Router、fallback Planner、Evidence Checker 和 Finalizer 都在本地运行。
- 需要更自然的 Planner/Answer 时，复用现有 DeepSeek/Qwen 等外部文本 Provider。
- 外部 Provider 需要配置凭据、预算与 `external_text_consent=true`，但不需要下载本地模型。
- Provider 不可用时仍可返回受证据约束的本地 fallback/evidence-only 结果。
- Checkpoint、Run Store、Tool Registry 和 30 条自动 Benchmark 都不依赖模型权重。

启用 v1.6 Agent 的基础开关：

```bash
export RETRIEVAL_ENABLED=true
export RESEARCH_AGENT_ENABLED=true
```

默认数据库路径：

```text
STRUCTURED_INDEX_DB_PATH=data/structured_index.sqlite3
RESEARCH_RUN_DB_PATH=data/research_runs.sqlite3
RESEARCH_CHECKPOINT_DB_PATH=data/research_checkpoints.sqlite3
```

## 六、推荐准备顺序

### A. 只验收无模型主链路

```text
1. 保留当前已安装的 agent extra
2. 构建或准备 structured index
3. 启用 RETRIEVAL_ENABLED 和 RESEARCH_AGENT_ENABLED
4. 保持 Dense、Reranker、Qdrant Sparse 关闭
5. 验收 FTS5 + Graph + Agent checkpoint/恢复/evidence-only
```

该路径当前不需要额外下载。

### B. 最小 Dense 验收

```text
1. 安装 retrieval extra
2. 预缓存 paraphrase-multilingual-MiniLM-L12-v2
3. 确认模型位于 data/models 或 RETRIEVAL_MODEL_CACHE_DIR
4. 恢复 RETRIEVAL_OFFLINE=true
5. 启用 RETRIEVAL_DENSE_ENABLED=true
6. 运行 Dense-only、Dense+Sparse 和 Dense+Sparse+Graph 消融
```

### C. 完整 Reranker 验收

```text
1. 完成最小 Dense 验收
2. 预缓存 BAAI/bge-reranker-base
3. 启用 RETRIEVAL_RERANKER_ENABLED=true
4. 记录 Locked Test 的质量、平均延迟和 P95 延迟
```

### D. 可选消融

```text
1. Jina code 模型使用独立 Vector Generation
2. 修复 BM25 cache_dir 后再准备 Qdrant/bm25
3. 需要轻量英文对照时再准备 Xenova Reranker
```

## 七、当前最小缺口结论

当前 v1.6 无模型 Agent 主链路没有缺失的必需依赖或权重。

如果要补做默认 Dense Retrieval 的真实手工验收，当前最小缺口是：

```text
qdrant-client[fastembed] 依赖
+
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

如果还要验收默认 Reranker，再增加：

```text
BAAI/bge-reranker-base
```

Qdrant BM25、Jina code 和轻量英文 Reranker 都属于可选消融，不应作为当前启动阻塞项。

## 八、v1.7 论文代码对齐 2.0

v1.7 本地规则 Profile、Candidate、Feature、Scorer、Calibration、Store、Coordinator、API 和
Review 不新增必需 Python 依赖，也不需要下载新权重。Constrained Verifier 复用现有 DeepSeek/
Qwen 文本 Provider；只有请求同时启用 Verifier、提供外发授权且 Provider 已配置时才调用。

当前发布质量门禁缺少的不是软件依赖，而是人工数据：

```text
6 个已授权且固定版本的 repo-paper pair
4 Dev + 2 Locked Test
72 个正例 + 20 个 unalignable/hard negative
双人标注、adjudication、不可变 repo/index/paper/profile/evidence ID
```

`evaluation/alignment/fixture_catalog_v1.json` 只冻结了 6 个槽位，未伪造仓库、论文或 Gold。
在补齐上述数据前，可以验收所有合同、持久化、API 和 Mock Provider 行为，但不能宣称已经达到
Candidate Recall、F1、Calibration、Abstention 或 Locked Test 的质量门槛。
