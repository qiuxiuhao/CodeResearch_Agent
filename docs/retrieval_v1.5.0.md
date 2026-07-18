# v1.5.0 代码结构感知 Hybrid RAG

## 固定检索管线

```text
raw_dense_hits + raw_sparse_hits
  -> preliminary_rrf（只选 Graph seed）
  -> graph_candidates
  -> final_rrf（Dense + Sparse + Graph）
  -> 可选 Hybrid/Reranker 分数融合
  -> Context Builder
  -> 可选固定 Answer Generator
  -> Citation Validator
```

Dense 相似度、BM25 分数和 Graph 分数不直接比较，统一以稳定 rank 进入 weighted RRF。
Reranker 不能覆盖 Hybrid 信号；失败时保持 final RRF 顺序。Graph unresolved edge 只作为
关系说明，不遍历、不伪造 target。

## 存储边界

- `data/structured_index.sqlite3`：v1.4 结构化事实源，只读。
- `data/retrieval_fts.sqlite3`：可重建 FTS5 generation；查询只读 ready generation。
- `data/qdrant`：可选 Dense/Qdrant BM25 派生向量。
- `data/retrieval/manifests`：向量 generation 状态。

Qdrant Point ID 由完整 `vector_profile_hash + repo_id + index_version_id + chunk_id`
生成。相同稳定 Chunk 可在多个仓库和版本并存，删除某版本只删除该版本 Payload 范围。

## Feature Flags

| 环境变量 | 默认值 | 含义 |
| -- | -- | -- |
| `RETRIEVAL_ENABLED` | `false` | 控制三个路由执行；路由始终存在 |
| `RETRIEVAL_DENSE_ENABLED` | `false` | 启用本地 Dense/Qdrant 同步与查询 |
| `RETRIEVAL_QDRANT_SPARSE_ENABLED` | `false` | 可选 Qdrant BM25；失败回退 FTS5 |
| `RETRIEVAL_RERANKER_ENABLED` | `false` | 启用已缓存 Cross Encoder |
| `RETRIEVAL_OFFLINE` | `true` | 禁止运行时下载模型 |
| `RETRIEVAL_MODEL_CACHE_DIR` | `data/models` | 本地模型缓存目录 |
| `QDRANT_LOCAL_PATH` | `data/qdrant` | Qdrant Local 目录 |

默认 Dense 模型为 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`、384
维。部署必须通过 `RETRIEVAL_DENSE_MODEL_REVISION` 固定实际 revision；模型、维度、预处理
或 Chunk Schema 变化都会形成新 `vector_profile_hash` 和 generation。

## API

- `POST /repositories/{repo_id}/retrieval/search`：仅检索，不调用回答模型。
- `POST /repositories/{repo_id}/research/query`：固定单轮检索、上下文、回答和引用校验。
- `GET /repositories/{repo_id}/retrieval/config`：公开 flags、active version 和限额。

公开请求不重复提交 `repo_id`。未指定 `index_version_id` 时，HTTP 层解析该仓库 active
版本；内部所有阶段始终显式携带 repo/version。研究回答请求默认需要：

```json
{
  "text": "SimpleNet.forward 如何实现？",
  "answer_enabled": true,
  "external_text_consent": true
}
```

没有授权时仍返回检索和 ContextBundle，不发送外部文本。Citation Validator 仅接受
ContextBundle 中真实的 context/evidence/entity 组合，并使用事实位置覆盖模型给出的路径、
行号和论文页码；所有重要 Claim 均无有效引用时降级为 evidence-only。

## Benchmark 与评测

`evaluation/retrieval/benchmark_v1.jsonl` 固定 40 条问题：30 条 Development Set 和
10 条 Locked Test Set。Locked Test 不参与日常调参，最终结论以其指标为主。预测 JSONL
每行至少包含：

```json
{"case_id":"test-001","ranked_chunk_ids":["chunk_forward"],"graph_paths":[],"latency_ms":12.3,"fallback_used":false}
```

运行：

```bash
python scripts/evaluate_retrieval.py \
  --predictions evaluation/retrieval/predictions.jsonl \
  --output evaluation/retrieval/report.json
```

可直接重建固定 SQLite fixture 并运行某个消融：

```bash
python scripts/run_retrieval_benchmark.py \
  --mode sparse_only \
  --index-db /tmp/cra-retrieval-benchmark.sqlite3 \
  --fts-db /tmp/cra-retrieval-fts.sqlite3 \
  --predictions /tmp/cra-retrieval-predictions.jsonl \
  --report /tmp/cra-retrieval-report.json \
  --build-fixture
```

`--mode` 支持 `sparse_only`、`dense_only`、`dense_sparse`、
`dense_sparse_graph` 和 `full_reranker`。需要真实模型的模式只读取显式配置且已缓存的模型；
自动测试与 Sparse baseline 不触发下载。

报告分别输出 Dev、Locked Test 和全集的 Recall@1/5/10、MRR、nDCG@5/10、Graph Path
Recall、平均/P50/P95 延迟和 fallback rate。自动测试只使用 Fake Embedder、Fake
VectorStore、Mock Reranker 和 Mock Provider，不下载真实模型。
