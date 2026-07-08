import { useEffect } from "react";
import type { LibraryCall, LibraryFunctionDoc } from "../types/analysis";

type Props = {
  call: LibraryCall;
  doc?: LibraryFunctionDoc;
  onClose: () => void;
};

export function LibraryFunctionModal({ call, doc, onClose }: Props) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const title = call.canonical_name || call.display_name || call.call_text || "unknown";
  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div className="modal" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="库函数解释">
        <div className="modal-header">
          <div>
            <h2>{title}</h2>
            <p className="muted">
              调用：{call.call_text || "未知"} {call.line_no ? `行号：${call.line_no}` : ""}
            </p>
          </div>
          <button className="secondary-button" onClick={onClose} type="button">
            关闭
          </button>
        </div>
        {doc ? (
          <div>
            <h3>一句话作用</h3>
            <p>{doc.summary}</p>
            <h3>通俗解释</h3>
            <p>{doc.beginner_explanation}</p>
            <h3>常见参数</h3>
            <List items={doc.parameters_explanation} fallback="暂无参数说明。" />
            <h3>返回值</h3>
            <p>{doc.return_explanation || "暂无返回值说明。"}</p>
            <h3>深度学习中的常见用途</h3>
            <p>{doc.common_usage || "需结合调用上下文确认。"}</p>
            {doc.code_example && <pre>{doc.code_example}</pre>}
            <h3>Shape / Tensor 注意事项</h3>
            <p>{doc.shape_or_tensor_note || "暂无注意事项。"}</p>
            <h3>常见误区</h3>
            <List items={doc.common_mistakes} fallback="暂无常见误区。" />
            <p className="muted">置信度：{doc.confidence || "medium"}</p>
          </div>
        ) : (
          <p className="muted">暂无教学解释。当前只显示本次调用信息。</p>
        )}
      </div>
    </div>
  );
}

function List({ items, fallback }: { items?: string[]; fallback: string }) {
  if (!items || items.length === 0) {
    return <p className="muted">{fallback}</p>;
  }
  return (
    <ul>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
