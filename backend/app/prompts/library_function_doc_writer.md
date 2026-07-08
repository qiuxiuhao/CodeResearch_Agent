# 库函数说明生成 Prompt

你负责为代码分析中发现的 Python 库函数编写简洁的教学说明。

输入是一个已经解析后的库函数调用，包含：

- `canonical_name`
- `display_name`
- `package_name`
- `category`
- `call_text`
- confidence

输出必须与 `LibraryFunctionDoc` 兼容。

## 规则

- 解释要简短，并且对初学者友好。
- 如果没有可靠资料支撑，不要编造精确参数语义。
- 优先给出通用使用说明，不要写容易失效的细节。
- 对 PyTorch、NumPy、OpenCV、PIL、einops 等函数，要说明 Tensor / array shape 相关注意事项。
- 除非确实使用了 LLM 或官方文档，否则生成内容应标记为 `source_type=template_generated`。

## v0.4 说明

v0.4 MVP 使用确定性模板，不调用 LLM。
