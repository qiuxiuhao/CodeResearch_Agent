# v1.3.5 基础问题评测基线

此基线用于后续 RAG 版本比较，不代表 v1.4.0 已实现检索问答。事实源为 commit
`5073f9f899e83759a6e21ec1ea56a7ae282f84eb` 上的
`examples/small_pytorch_project.zip`，规则模式任务 `task_d7efedaeeb2f` 的旧 JSON 输出。
问题只依据 `repo_index.json`、`parsed_files.json`、`file_analysis.json`、
`function_analysis.json`、`model_analysis.json` 和 `paper_analysis.json` 判定；LLM/VLM 未启用。

| # | 基础问题 | v1.3.5 规则结果 | 事实来源 |
| -- | -- | -- | -- |
| 1 | 仓库有多少个 Python 文件？ | 5 | `repo_index.python_files` |
| 2 | 项目入口文件是什么？ | `main.py` | `entry_file_candidates` |
| 3 | 模型文件是什么？ | `models/simple_model.py` | `model_file_candidates` |
| 4 | 训练文件是什么？ | `train.py` | `train_file_candidates` |
| 5 | 配置文件是什么？ | `config.yaml` | `config_file_candidates` |
| 6 | 是否识别到推理文件？ | 否 | `infer_file_candidates=[]` |
| 7 | 数据集类是什么？ | `TinyDataset` | `file_analysis` |
| 8 | 数据集长度是多少？ | `__len__` 返回 2 | `data/dataset.py`、函数行 2–3 |
| 9 | 数据集按索引返回什么？ | 返回输入的 `index` | `data/dataset.py`、函数行 5–6 |
| 10 | 主模型类是什么？ | `SimpleNet` | `model_analysis` |
| 11 | `SimpleNet` 继承什么？ | `nn.Module`，可还原为 `torch.nn.Module` | `base_classes`、model evidence |
| 12 | 模型构造参数有哪些？ | `input_dim`、`hidden_dim`、`output_dim` | `SimpleNet.__init__` |
| 13 | 模型输入参数是什么？ | `x` | `model_inputs` |
| 14 | 模型输出表达式是什么？ | `self.fc2(hidden)` | `model_outputs` |
| 15 | 模型有多少个初始化层？ | 2 | `model_analysis.layers` |
| 16 | 第一层是什么？ | `self.fc1 = nn.Linear(input_dim, hidden_dim)` | 行 8 layer evidence |
| 17 | 第二层是什么？ | `self.fc2 = nn.Linear(hidden_dim, output_dim)` | 行 9 layer evidence |
| 18 | forward 的第一步是什么？ | `hidden = F.relu(self.fc1(x))` | `forward_steps[0]` |
| 19 | forward 的第二步是什么？ | 返回 `self.fc2(hidden)` | `forward_steps[1]` |
| 20 | 激活函数是什么？ | `torch.nn.functional.relu` | component/library call |
| 21 | `forward` 是否为核心函数？ | 是 | `FunctionAnalysis.is_core_function` |
| 22 | 入口 `main` 调用了什么？ | `SimpleNet`、`train_one_epoch` | `called_internal_functions` |
| 23 | 创建模型时的维度是多少？ | 4、8、2 | `main.py` 行 6 |
| 24 | 训练函数是什么？ | `train_one_epoch` | `train.py`、file analysis |
| 25 | 训练 batch 的 shape 是什么？ | `(2, 4)` | `torch.randn(2, 4)` |
| 26 | 训练函数如何调用模型？ | `output = model(batch)` | `train.py` 行 6 |
| 27 | loss 如何计算？ | `output.mean()` | `train.py` 行 7 |
| 28 | 哪些高置信度 PyTorch 调用被识别？ | `torch.nn.Linear`、`torch.nn.functional.relu`、`torch.randn` | `library_calls` |
| 29 | `output.mean` 的识别置信度是什么？ | low，且未写入全局库 | `train_one_epoch.library_calls` |
| 30 | 是否提供论文并产生论文贡献？ | 否；贡献为空 | `paper_analysis` |

## 基线限制

- v1.3.5 没有仓库级符号 ID、Import Resolver、Call Graph 或 unresolved Edge，问题 22 只能使用函数启发式字符串回答。
- 该基线是固定示例仓库的规则事实快照，不衡量自然语言召回、排序或答案生成质量。
- 后续版本比较应保持上述问题、示例 ZIP 和旧 Schema 语义不变，并另行记录命中证据、延迟和失败原因。
