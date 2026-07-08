from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.schemas.library_function import (
    LibraryFunctionDoc,
    LibraryFunctionOccurrence,
    LibraryFunctionProcessResult,
)


DEFAULT_LIBRARY_DB_PATH = Path("data/python_function_library.sqlite3")
JSON_LIST_FIELDS = {"parameters_explanation", "common_mistakes", "related_functions"}


class LibraryFunctionService:
    def __init__(self, db_path: str | Path | None = None) -> None:
        configured_path = db_path or os.getenv("LIBRARY_DB_PATH") or DEFAULT_LIBRARY_DB_PATH
        self.db_path = Path(configured_path)

    def ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS library_functions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_name TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    package_name TEXT,
                    category TEXT,
                    source_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    beginner_explanation TEXT NOT NULL,
                    parameters_explanation TEXT NOT NULL,
                    return_explanation TEXT,
                    common_usage TEXT,
                    code_example TEXT,
                    shape_or_tensor_note TEXT,
                    common_mistakes TEXT NOT NULL,
                    related_functions TEXT NOT NULL,
                    official_doc_url TEXT,
                    confidence TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS library_function_occurrences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    library_function_id INTEGER NOT NULL,
                    canonical_name TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    project_name TEXT,
                    file_path TEXT NOT NULL,
                    function_name TEXT NOT NULL,
                    class_name TEXT,
                    qualified_function_name TEXT NOT NULL,
                    line_no INTEGER,
                    call_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(library_function_id) REFERENCES library_functions(id)
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_library_functions_canonical_name "
                "ON library_functions(canonical_name)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_library_function_occurrences_function_id "
                "ON library_function_occurrences(library_function_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_library_function_occurrences_task_id "
                "ON library_function_occurrences(task_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_library_function_occurrences_canonical_name "
                "ON library_function_occurrences(canonical_name)"
            )

    def get_by_canonical_name(self, canonical_name: str) -> LibraryFunctionDoc | None:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM library_functions WHERE canonical_name = ?",
                (canonical_name,),
            ).fetchone()
        return self._row_to_doc(row) if row else None

    def create_doc_from_call(self, call: dict) -> LibraryFunctionDoc:
        canonical_name = call.get("canonical_name", "")
        category = call.get("category") or "third_party"
        display_name = call.get("display_name") or canonical_name
        package_name = call.get("package_name")
        confidence = "high" if call.get("confidence") == "high" else "medium"
        template = _template_for_category(category, canonical_name, display_name)
        now = _utc_now()
        return LibraryFunctionDoc(
            canonical_name=canonical_name,
            display_name=display_name,
            package_name=package_name,
            category=category,
            source_type="template_generated",
            summary=template["summary"],
            beginner_explanation=template["beginner_explanation"],
            parameters_explanation=template["parameters_explanation"],
            return_explanation=template["return_explanation"],
            common_usage=template["common_usage"],
            code_example=template["code_example"],
            shape_or_tensor_note=template["shape_or_tensor_note"],
            common_mistakes=template["common_mistakes"],
            related_functions=[],
            official_doc_url=None,
            confidence=confidence,
            created_at=now,
            updated_at=now,
        )

    def upsert_library_function_doc(self, doc: LibraryFunctionDoc) -> LibraryFunctionDoc:
        self.ensure_schema()
        existing = self.get_by_canonical_name(doc.canonical_name)
        if existing is not None:
            return existing

        now = _utc_now()
        doc_to_insert = doc.model_copy(
            update={
                "created_at": doc.created_at or now,
                "updated_at": doc.updated_at or now,
            }
        )
        columns = [
            "canonical_name",
            "display_name",
            "package_name",
            "category",
            "source_type",
            "summary",
            "beginner_explanation",
            "parameters_explanation",
            "return_explanation",
            "common_usage",
            "code_example",
            "shape_or_tensor_note",
            "common_mistakes",
            "related_functions",
            "official_doc_url",
            "confidence",
            "created_at",
            "updated_at",
        ]
        values = [_serialize_value(column, getattr(doc_to_insert, column)) for column in columns]

        with self._connect() as conn:
            try:
                cursor = conn.execute(
                    f"INSERT INTO library_functions ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in columns)})",
                    values,
                )
            except sqlite3.IntegrityError:
                existing_after_conflict = self.get_by_canonical_name(doc.canonical_name)
                if existing_after_conflict is not None:
                    return existing_after_conflict
                raise
            doc_id = cursor.lastrowid
        return doc_to_insert.model_copy(update={"id": doc_id})

    def record_occurrence(
        self,
        doc: LibraryFunctionDoc,
        call: dict,
        task_id: str,
        project_name: str | None,
    ) -> None:
        if doc.id is None:
            raise ValueError(f"Library function doc has no id: {doc.canonical_name}")
        self.ensure_schema()
        occurrence = LibraryFunctionOccurrence(
            library_function_id=doc.id,
            canonical_name=doc.canonical_name,
            task_id=task_id,
            project_name=project_name,
            file_path=call.get("file_path", ""),
            function_name=call.get("function_name", ""),
            class_name=call.get("class_name"),
            qualified_function_name=call.get("qualified_function_name", call.get("function_name", "")),
            line_no=call.get("line_no"),
            call_text=call.get("call_text", ""),
            created_at=_utc_now(),
        )
        with self._connect() as conn:
            duplicate = conn.execute(
                """
                SELECT id FROM library_function_occurrences
                WHERE task_id = ?
                  AND canonical_name = ?
                  AND file_path = ?
                  AND qualified_function_name = ?
                  AND (line_no = ? OR (line_no IS NULL AND ? IS NULL))
                  AND call_text = ?
                """,
                (
                    occurrence.task_id,
                    occurrence.canonical_name,
                    occurrence.file_path,
                    occurrence.qualified_function_name,
                    occurrence.line_no,
                    occurrence.line_no,
                    occurrence.call_text,
                ),
            ).fetchone()
            if duplicate:
                return
            conn.execute(
                """
                INSERT INTO library_function_occurrences (
                    library_function_id,
                    canonical_name,
                    task_id,
                    project_name,
                    file_path,
                    function_name,
                    class_name,
                    qualified_function_name,
                    line_no,
                    call_text,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    occurrence.library_function_id,
                    occurrence.canonical_name,
                    occurrence.task_id,
                    occurrence.project_name,
                    occurrence.file_path,
                    occurrence.function_name,
                    occurrence.class_name,
                    occurrence.qualified_function_name,
                    occurrence.line_no,
                    occurrence.call_text,
                    occurrence.created_at,
                ),
            )

    def process_library_calls(
        self,
        library_calls: list[dict],
        task_id: str,
        project_name: str | None,
    ) -> LibraryFunctionProcessResult:
        self.ensure_schema()
        docs_by_name: dict[str, LibraryFunctionDoc] = {}
        new_docs_by_name: dict[str, LibraryFunctionDoc] = {}
        skipped: list[dict] = []
        updated_calls: list[dict] = []
        errors: list[dict] = []

        for call in library_calls:
            updated_call = {**call, "is_recorded_in_global_library": False}
            canonical_name = call.get("canonical_name", "")
            if _should_skip_call(call):
                skipped.append(updated_call)
                updated_calls.append(updated_call)
                continue

            try:
                doc = docs_by_name.get(canonical_name) or self.get_by_canonical_name(canonical_name)
                if doc is None:
                    doc = self.upsert_library_function_doc(self.create_doc_from_call(call))
                    new_docs_by_name[doc.canonical_name] = doc
                docs_by_name[doc.canonical_name] = doc
                self.record_occurrence(doc, call, task_id, project_name)
                updated_call["is_recorded_in_global_library"] = True
            except Exception as exc:  # pragma: no cover - defensive path for SQLite IO issues.
                errors.append(
                    {
                        "path": call.get("file_path", ""),
                        "error_type": type(exc).__name__,
                        "message": f"Failed to process library function {canonical_name}: {exc}",
                    }
                )
            updated_calls.append(updated_call)

        return LibraryFunctionProcessResult(
            library_function_docs=list(docs_by_name.values()),
            new_library_functions=list(new_docs_by_name.values()),
            updated_library_calls=updated_calls,
            skipped_low_confidence_calls=skipped,
            errors=errors,
        )

    def list_functions(self, limit: int = 100, package_name: str | None = None) -> list[LibraryFunctionDoc]:
        self.ensure_schema()
        limit = max(1, min(limit, 1000))
        with self._connect() as conn:
            if package_name:
                rows = conn.execute(
                    "SELECT * FROM library_functions WHERE package_name = ? ORDER BY canonical_name LIMIT ?",
                    (package_name, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM library_functions ORDER BY canonical_name LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_doc(row) for row in rows]

    def list_occurrences(self, canonical_name: str) -> list[LibraryFunctionOccurrence]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM library_function_occurrences
                WHERE canonical_name = ?
                ORDER BY created_at, id
                """,
                (canonical_name,),
            ).fetchall()
        return [self._row_to_occurrence(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_doc(self, row: sqlite3.Row) -> LibraryFunctionDoc:
        data = dict(row)
        for field in JSON_LIST_FIELDS:
            data[field] = json.loads(data[field] or "[]")
        return LibraryFunctionDoc(**data)

    def _row_to_occurrence(self, row: sqlite3.Row) -> LibraryFunctionOccurrence:
        return LibraryFunctionOccurrence(**dict(row))


def _should_skip_call(call: dict) -> bool:
    return (
        not call.get("canonical_name")
        or call.get("confidence") == "low"
        or call.get("category") == "unknown"
    )


def _serialize_value(column: str, value: Any) -> Any:
    if column in JSON_LIST_FIELDS:
        return json.dumps(value or [], ensure_ascii=False)
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SPECIAL_FUNCTION_TEMPLATES: dict[str, dict[str, Any]] = {
    "torch.nn.Linear": {
        "summary": "`torch.nn.Linear` 用于创建全连接层，把输入最后一维从 `in_features` 映射到 `out_features`。",
        "beginner_explanation": "可以把它理解为一层可学习的线性变换：模型会学习一组权重和可选偏置，把一组特征转换成另一组特征。",
        "parameters_explanation": [
            "`in_features`：输入特征数，必须等于输入 Tensor 最后一维大小。",
            "`out_features`：输出特征数，也就是这一层要产生多少个新特征。",
            "`bias`：是否额外学习偏置项，默认通常为 True。",
        ],
        "return_explanation": "返回一个 `torch.nn.Linear` 模块，调用该模块后会得到形状最后一维为 `out_features` 的 Tensor。",
        "common_usage": "深度学习中常用于分类头、MLP、特征投影，或把模型中间表示映射到类别数、隐藏维度等目标空间。",
        "code_example": "layer = torch.nn.Linear(in_features=128, out_features=10)\ny = layer(x)",
        "shape_or_tensor_note": "输入形状通常是 `(..., in_features)`，输出形状是 `(..., out_features)`；最容易出错的是最后一维不等于 `in_features`。",
        "common_mistakes": [
            "把 batch size 误写成 `in_features`。",
            "输入 Tensor 最后一维和 `in_features` 不一致。",
            "忘记 Linear 层本身只是模块，真正计算需要调用 `layer(x)`。",
        ],
    },
    "torch.nn.functional.relu": {
        "summary": "`torch.nn.functional.relu` 用于把 Tensor 中小于 0 的值变成 0，保留大于 0 的值。",
        "beginner_explanation": "可以把它理解为一个简单的非线性开关：负数被关掉，正数继续通过，让神经网络能表达更复杂的关系。",
        "parameters_explanation": [
            "`input`：要处理的 Tensor。",
            "`inplace`：是否原地修改输入，默认通常为 False，初学时建议保持默认。",
        ],
        "return_explanation": "返回与输入形状相同的 Tensor，其中负值位置被替换为 0。",
        "common_usage": "深度学习中常放在线性层、卷积层之后，作为隐藏层激活函数。",
        "code_example": "y = torch.nn.functional.relu(x)",
        "shape_or_tensor_note": "ReLU 不改变 Tensor 的 shape，只改变数值；原地模式可能影响后续梯度计算或复用输入。",
        "common_mistakes": [
            "以为 ReLU 会改变维度。",
            "随意使用 `inplace=True` 导致反向传播或后续逻辑出错。",
        ],
    },
    "torch.randn": {
        "summary": "`torch.randn` 用于生成服从标准正态分布的随机 Tensor。",
        "beginner_explanation": "可以把它理解为按指定形状造一批随机数，常用于模拟输入、初始化测试数据或构造噪声。",
        "parameters_explanation": [
            "`size`：输出 Tensor 的形状，例如 `2, 3` 或 `(2, 3)`。",
            "`device`：可选，指定生成在 CPU 还是 GPU。",
            "`dtype`：可选，指定数据类型。",
        ],
        "return_explanation": "返回指定形状的随机 Tensor，数值大致围绕 0 波动。",
        "common_usage": "深度学习中常用于构造假输入、调试模型 forward、生成噪声或测试张量维度。",
        "code_example": "x = torch.randn(4, 128)",
        "shape_or_tensor_note": "传入的形状就是输出 shape；如果模型在 GPU 上，随机 Tensor 也通常需要放到同一 device。",
        "common_mistakes": [
            "生成的 Tensor shape 与模型期望输入不一致。",
            "模型在 GPU 上但随机 Tensor 仍在 CPU 上。",
            "把随机数据当成真实数据分布。",
        ],
    },
    "torch.cat": {
        "summary": "`torch.cat` 用于沿已有维度把多个 Tensor 拼接起来。",
        "beginner_explanation": "可以把它理解为把几块形状兼容的 Tensor 接成长的一块，类似把表格按行或按列接在一起。",
        "parameters_explanation": [
            "`tensors`：要拼接的 Tensor 序列。",
            "`dim`：沿哪个已有维度拼接。",
        ],
        "return_explanation": "返回拼接后的 Tensor；除 `dim` 维外，其他维度大小必须一致。",
        "common_usage": "深度学习中常用于拼接特征、合并多路输出、构造 batch 或连接 skip connection 的特征。",
        "code_example": "y = torch.cat([a, b], dim=1)",
        "shape_or_tensor_note": "`cat` 不会新增维度，只会让指定的已有维度变长；其他维度必须相同。",
        "common_mistakes": [
            "把需要新增维度的场景误用成 `cat`，这时可能应该用 `stack`。",
            "拼接维度以外的 shape 不一致。",
            "选错 `dim` 导致特征或 batch 维被错误拼接。",
        ],
    },
    "torch.stack": {
        "summary": "`torch.stack` 用于把多个相同形状的 Tensor 沿新维度堆叠起来。",
        "beginner_explanation": "可以把它理解为把多张同样大小的纸叠成一摞，因此结果会多出一个维度。",
        "parameters_explanation": [
            "`tensors`：要堆叠的 Tensor 序列，每个 Tensor shape 必须相同。",
            "`dim`：新维度插入的位置。",
        ],
        "return_explanation": "返回多出一个维度的新 Tensor。",
        "common_usage": "深度学习中常用于把多个样本、时间步、模型输出或中间特征合成一个批量 Tensor。",
        "code_example": "batch = torch.stack([x1, x2, x3], dim=0)",
        "shape_or_tensor_note": "如果每个输入是 `(C, H, W)`，`dim=0` 后通常得到 `(N, C, H, W)`。",
        "common_mistakes": [
            "输入 Tensor shape 不完全相同。",
            "把 `stack` 和 `cat` 混淆：`stack` 会新增维度，`cat` 不会。",
        ],
    },
    "torch.matmul": {
        "summary": "`torch.matmul` 用于执行向量、矩阵或批量矩阵乘法。",
        "beginner_explanation": "可以把它理解为线性代数里的乘法工具，用来把一个特征空间映射到另一个特征空间。",
        "parameters_explanation": [
            "`input`：左侧 Tensor。",
            "`other`：右侧 Tensor。",
        ],
        "return_explanation": "返回矩阵乘法结果；输出 shape 由输入的最后两个维度和批量维广播规则决定。",
        "common_usage": "深度学习中常用于注意力分数计算、特征投影、相似度计算和自定义线性变换。",
        "code_example": "scores = torch.matmul(q, k.transpose(-2, -1))",
        "shape_or_tensor_note": "矩阵乘法要求左侧最后一维与右侧倒数第二维匹配；批量维需要能广播。",
        "common_mistakes": [
            "最后两个维度不匹配。",
            "忘记在注意力计算中转置 key 的最后两个维度。",
            "误把逐元素乘法当成矩阵乘法。",
        ],
    },
    "torch.mean": {
        "summary": "`torch.mean` 用于计算 Tensor 的平均值，可以对全部元素或指定维度求平均。",
        "beginner_explanation": "可以把它理解为把一组数压缩成平均水平，也可以沿某个维度把 Tensor 汇总变小。",
        "parameters_explanation": [
            "`input`：要统计的 Tensor。",
            "`dim`：可选，指定沿哪个维度求平均。",
            "`keepdim`：可选，是否保留被求平均的维度。",
        ],
        "return_explanation": "返回平均值 Tensor；如果指定 `dim`，该维度会被压缩，除非 `keepdim=True`。",
        "common_usage": "深度学习中常用于特征池化、损失统计、日志指标汇总或把空间维/序列维压缩成整体表示。",
        "code_example": "pooled = torch.mean(x, dim=1)",
        "shape_or_tensor_note": "`dim` 会影响输出 shape；需要广播回原 shape 时常设置 `keepdim=True`。",
        "common_mistakes": [
            "选错 `dim`，把 batch 维也平均掉。",
            "忘记 `keepdim` 导致后续广播或拼接失败。",
        ],
    },
    "numpy.array": {
        "summary": "`numpy.array` 用于把列表、元组等数据转换成 NumPy 数组。",
        "beginner_explanation": "可以把它理解为把普通 Python 数据整理成适合数值计算的数组格式。",
        "parameters_explanation": [
            "`object`：要转换的数据，例如 list、tuple 或嵌套列表。",
            "`dtype`：可选，指定数组元素类型。",
        ],
        "return_explanation": "返回一个 `numpy.ndarray`，其 shape 通常由输入数据的嵌套结构决定。",
        "common_usage": "深度学习中常用于读取数据后的预处理、把标签或特征整理成数组，再转换为 Tensor。",
        "code_example": "arr = numpy.array([[1, 2], [3, 4]])",
        "shape_or_tensor_note": "嵌套列表长度不一致时可能得到 object 数组，不适合直接做常规数值计算。",
        "common_mistakes": [
            "输入嵌套列表形状不规则。",
            "没有指定或检查 dtype，导致整数、浮点或 object 类型不符合预期。",
        ],
    },
    "numpy.concatenate": {
        "summary": "`numpy.concatenate` 用于沿已有轴把多个 NumPy 数组拼接起来。",
        "beginner_explanation": "可以把它理解为把几块数组接在一起，指定沿哪一条轴变长。",
        "parameters_explanation": [
            "`arrays`：要拼接的数组序列。",
            "`axis`：沿哪个已有轴拼接。",
        ],
        "return_explanation": "返回拼接后的 `numpy.ndarray`；除拼接轴外，其他轴长度必须一致。",
        "common_usage": "深度学习中常用于合并多批特征、标签、预测结果或数据预处理后的数组。",
        "code_example": "merged = numpy.concatenate([a, b], axis=0)",
        "shape_or_tensor_note": "`concatenate` 不新增轴，只让指定已有轴变长；需要新增轴时可先扩维或使用 stack 类操作。",
        "common_mistakes": [
            "除 `axis` 外的维度不一致。",
            "把新增维度的需求误写成 concatenate。",
            "axis 选择错误导致样本维和特征维混淆。",
        ],
    },
    "PIL.Image.open": {
        "summary": "`PIL.Image.open` 用于从文件路径或文件对象打开图片。",
        "beginner_explanation": "可以把它理解为把磁盘上的图片读成一个 PIL Image 对象，后续才能转换、裁剪或送入数据预处理流程。",
        "parameters_explanation": [
            "`fp`：图片路径或文件对象。",
            "`mode`：通常不用手动传，图片模式可在打开后用 `.convert()` 调整。",
        ],
        "return_explanation": "返回一个 `PIL.Image.Image` 对象；图片数据通常会在实际访问时再加载。",
        "common_usage": "深度学习中常用于 Dataset 的 `__getitem__` 中读取图片，再配合 transform 转成 Tensor。",
        "code_example": "image = PIL.Image.open(path).convert(\"RGB\")",
        "shape_or_tensor_note": "PIL 图片尺寸通常按 `(width, height)` 表示，转换成 Tensor 后常见形状是 `(channels, height, width)`。",
        "common_mistakes": [
            "忘记 `.convert(\"RGB\")`，导致灰度图或带 alpha 通道图片和模型输入不匹配。",
            "混淆 PIL 的宽高顺序和 Tensor 的通道、高、宽顺序。",
            "文件句柄生命周期处理不当。",
        ],
    },
}


def _template_for_category(category: str, canonical_name: str, display_name: str) -> dict[str, Any]:
    special_template = SPECIAL_FUNCTION_TEMPLATES.get(canonical_name)
    if special_template is not None:
        return special_template

    templates: dict[str, dict[str, Any]] = {
        "pytorch": {
            "summary": f"`{canonical_name}` 常用于 PyTorch 张量、模型或训练流程中的计算操作。",
            "beginner_explanation": "可以把它理解为深度学习代码里的一个工具函数，用来创建、变换或计算 Tensor。",
            "common_usage": "常见于模型前向计算、构造输入、损失计算或训练辅助逻辑。",
            "shape_or_tensor_note": "使用时需要特别关注 Tensor 的形状、dtype 和所在设备。",
            "common_mistakes": ["忽略 Tensor shape 导致维度不匹配。", "混用 CPU/GPU Tensor 导致运行错误。"],
        },
        "numpy": {
            "summary": f"`{canonical_name}` 常用于 NumPy 数组和数值计算。",
            "beginner_explanation": "可以把它理解为处理一组数字或多维数组的基础工具。",
            "common_usage": "常见于数据预处理、统计计算、数组形状调整或构造测试数据。",
            "shape_or_tensor_note": "使用时需要关注数组 shape、广播规则和数据类型。",
            "common_mistakes": ["忽略数组 shape 导致广播结果不符合预期。", "混淆 Python list 和 NumPy array 的行为。"],
        },
        "opencv": {
            "summary": f"`{canonical_name}` 常用于 OpenCV 图像读取、处理或变换。",
            "beginner_explanation": "可以把它理解为对图像矩阵执行读取、变换或分析的工具。",
            "common_usage": "常见于图像预处理、尺寸调整、颜色转换和视觉任务数据准备。",
            "shape_or_tensor_note": "OpenCV 图像通常是数组形式，并且颜色通道常见顺序是 BGR。",
            "common_mistakes": ["混淆 RGB 和 BGR 通道顺序。", "忽略图像数组的高度、宽度、通道顺序。"],
        },
        "pil": {
            "summary": f"`{canonical_name}` 常用于 PIL 图片读取、转换或处理。",
            "beginner_explanation": "可以把它理解为打开图片并做基础处理的工具。",
            "common_usage": "常见于数据集读取图片、格式转换和简单图像增强。",
            "shape_or_tensor_note": "PIL Image 与 Tensor/NumPy 数组之间转换时要注意尺寸和通道顺序。",
            "common_mistakes": ["忘记把图片转换成模型需要的格式。", "混淆图片尺寸中的宽高顺序。"],
        },
        "einops": {
            "summary": f"`{canonical_name}` 常用于清晰表达张量维度重排或聚合。",
            "beginner_explanation": "可以把它理解为用可读字符串说明 Tensor 的维度如何移动或组合。",
            "common_usage": "常见于模型结构中调整 batch、channel、height、width 等维度。",
            "shape_or_tensor_note": "需要确保表达式中的维度名和输入 Tensor 的真实 shape 对齐。",
            "common_mistakes": ["表达式维度名写错。", "重排前后元素数量不一致。"],
        },
        "python_stdlib": {
            "summary": f"`{canonical_name}` 是 Python 标准库中的基础能力。",
            "beginner_explanation": "可以把它理解为 Python 自带的工具，不需要额外安装第三方包。",
            "common_usage": "常见于路径处理、配置读取、数学计算、随机数或数据结构辅助逻辑。",
            "shape_or_tensor_note": None,
            "common_mistakes": ["没有结合具体函数文档确认参数含义。", "忽略文件路径、类型或异常情况。"],
        },
        "third_party": {
            "summary": f"`{canonical_name}` 是第三方库提供的函数或方法。",
            "beginner_explanation": "可以把它理解为项目依赖包提供的现成功能，具体行为需要结合该库文档确认。",
            "common_usage": "常见于调用外部依赖完成项目中的专门功能。",
            "shape_or_tensor_note": None,
            "common_mistakes": ["只看函数名就假设其行为。", "没有确认当前依赖版本下的参数和返回值。"],
        },
    }
    fallback = templates["third_party"]
    template = templates.get(category, fallback)
    return {
        "summary": template["summary"],
        "beginner_explanation": template["beginner_explanation"],
        "parameters_explanation": ["参数含义需结合具体函数官方文档确认。"],
        "return_explanation": "通常返回处理后的对象、数组、张量或计算结果，具体类型需结合函数文档和调用上下文确认。",
        "common_usage": template["common_usage"],
        "code_example": f"result = {display_name}(...)",
        "shape_or_tensor_note": template["shape_or_tensor_note"],
        "common_mistakes": template["common_mistakes"],
    }
