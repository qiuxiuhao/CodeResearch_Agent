# v1.5.0 本地模型与依赖准备清单

本文记录完成 v1.5.0 真实 Dense、Qdrant Sparse 和 Reranker 手工验收时需要准备的内容。
自动测试、SQLite FTS5 和 evidence-only 检索不依赖这些模型，也不得在测试过程中自动下载。

## 一、最小必需内容

### 1. 可选 Retrieval Python 依赖

在项目指定 Conda 环境中安装：

```bash
conda activate code-research-agent
cd /Users/qiu_star/Desktop/own_project/CodeResearch_Agent
pip install -e '.[retrieval]'
```

该 extra 当前定义为：

```text
qdrant-client[fastembed]>=1.9.0,<2.0
```

它会安装 Qdrant Client、FastEmbed、ONNX Runtime 及其必要的传递依赖。当前使用 Qdrant
Local，不需要单独安装或下载 Qdrant Server。

### 2. 默认 Dense Embedding 模型

```text
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

- 作用：默认 Dense Retrieval，重点覆盖中文查询英文代码。
- 向量维度：384。
- 近似下载大小：220 MB。
- 默认缓存目录：`data/models`。
- 可通过 `RETRIEVAL_MODEL_CACHE_DIR` 修改缓存目录。

这是完成最小 Dense 手工验收必须准备的模型。

## 二、按功能选择的模型

### 1. 默认 Reranker

```text
BAAI/bge-reranker-base
```

- 作用：中英文 Cross Encoder Reranker 验收。
- 近似下载大小：1 GB。
- 只有启用 `RETRIEVAL_RERANKER_ENABLED=true` 时才需要。
- 未缓存、离线或推理失败时，系统必须无损回退到 Final RRF。

### 2. Qdrant BM25 Sparse

```text
Qdrant/bm25
```

- 作用：Qdrant named sparse vector 消融实验。
- 只有启用 `RETRIEVAL_QDRANT_SPARSE_ENABLED=true` 时才需要。
- SQLite FTS5 已提供独立 Sparse baseline，因此该模型不阻塞 Dense 主链路或 v1.5 发布。

当前已知限制：`backend/app/retrieval/api.py` 创建 `QdrantBM25SparseProvider` 时尚未传入
构造函数要求的 `cache_dir`。在修正并补充专项测试前，不应启用该 Flag，也不需要提前下载
此模型；当前行为会降级到 FTS5。

## 三、仅用于消融实验的候选模型

### 1. 代码专用 Dense 候选

```text
jinaai/jina-embeddings-v2-base-code
```

- 作用：与默认多语言 Dense 模型进行代码检索消融。
- 向量维度：768。
- 近似下载大小：640 MB。
- 不作为默认中文查询模型。
- 切换该模型必须生成新的 `vector_profile_hash`、Collection 和 Vector Generation，不能复用
  384 维默认模型的向量索引。

### 2. 轻量英文 Reranker 候选

```text
Xenova/ms-marco-MiniLM-L-6-v2
```

- 作用：轻量 Reranker 延迟和英文检索消融。
- 近似下载大小：80 MB。
- 不作为默认中英文 Reranker。

## 四、不需要下载的内容

- 不需要 Qdrant Server，当前使用 Qdrant Local。
- 不需要为 SQLite FTS5 下载模型或分词器。
- 不需要本地 LLM；固定研究回答复用现有外部文本 Provider。
- 不需要为 evidence-only 检索配置或调用外部 Provider。
- 不需要论文解析模型。
- 自动测试只使用 Fake Embedder、Fake VectorStore、Mock Reranker 和 Mock Provider，不得下载
  真实模型。

## 五、推荐准备顺序

### 最小 Dense 验收

```text
1. 安装项目的 retrieval extra
2. 下载 paraphrase-multilingual-MiniLM-L12-v2
3. 将模型放入 data/models 或 RETRIEVAL_MODEL_CACHE_DIR
4. 保持 RETRIEVAL_OFFLINE=true，确认离线加载成功
5. 运行 Dense-only、Dense+Sparse 和 Dense+Sparse+Graph 消融
```

### 完整 Reranker 验收

在最小 Dense 验收基础上增加：

```text
6. 下载 BAAI/bge-reranker-base
7. 启用 RETRIEVAL_RERANKER_ENABLED=true
8. 运行 full_reranker 消融并记录 Locked Test 的质量和 P95 延迟
```

### 可选扩展消融

```text
9. 下载 jinaai/jina-embeddings-v2-base-code，重建独立 Vector Generation
10. 修正 QdrantBM25SparseProvider cache_dir 后再准备 Qdrant/bm25
11. 如需轻量英文 Reranker 对照，再下载 Xenova/ms-marco-MiniLM-L-6-v2
```

## 六、最小下载结论

只完成默认 Dense Retrieval 手工验收时，最小组合为：

```text
qdrant-client[fastembed] 依赖
+
sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

如果还要完成默认 Reranker 验收，再增加：

```text
BAAI/bge-reranker-base
```
