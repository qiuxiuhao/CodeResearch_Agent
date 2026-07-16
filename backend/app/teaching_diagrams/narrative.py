from __future__ import annotations

from backend.app.schemas.teaching_diagram import TeachingDiagramNarrative, TeachingDiagramSkeleton


def build_local_narrative(skeleton: TeachingDiagramSkeleton) -> TeachingDiagramNarrative:
    module_labels = [item.label for item in skeleton.modules[:4]]
    steps = []
    if skeleton.connections:
        for index, connection in enumerate(skeleton.connections[:6], start=1):
            source = _label_for(skeleton, connection.source_module_id)
            target = _label_for(skeleton, connection.target_module_id)
            steps.append(f"{index}. {source} 传递到 {target}")
    else:
        steps = [f"{index}. 观察模块：{label}" for index, label in enumerate(module_labels, start=1)]
    summary = f"{skeleton.source_entity.title}：从 {module_labels[0]} 开始，理解关键模块之间的数据流。" if module_labels else skeleton.source_entity.title
    return TeachingDiagramNarrative(
        skeleton_id=skeleton.skeleton_id,
        skeleton_hash=skeleton.skeleton_hash,
        section_titles={section.id: section.title for section in skeleton.sections},
        teaching_steps=steps,
        one_sentence_summary=summary,
        learning_tips=[
            "先沿箭头看数据如何流动，再回头看每个模块的作用。",
            "Tensor Shape 和公式只展示规则证据支持的内容。",
        ],
    )


def _label_for(skeleton: TeachingDiagramSkeleton, module_id: str) -> str:
    module = next((item for item in skeleton.modules if item.id == module_id), None)
    return module.label if module else module_id
