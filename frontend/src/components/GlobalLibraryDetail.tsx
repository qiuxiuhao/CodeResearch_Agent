import type { GlobalLibraryDetailResponse } from "../types/analysis";
import { EmptyState } from "./EmptyState";

type Props = {
  detail: GlobalLibraryDetailResponse | null;
  isLoading?: boolean;
};

export function GlobalLibraryDetail({ detail, isLoading }: Props) {
  if (isLoading) {
    return <section className="item-card"><p className="muted">正在加载函数详情...</p></section>;
  }
  if (!detail) {
    return <EmptyState message="请选择一个函数查看详情。" />;
  }
  const fn = detail.function;
  return (
    <section className="item-card detail-panel">
      <h3>{fn.canonical_name}</h3>
      <p className="muted">
        {fn.package_name || "unknown"} · {fn.category || "unknown"} · {fn.confidence || "medium"}
      </p>
      <h4>一句话作用</h4>
      <p>{fn.summary || "暂无说明。"}</p>
      <h4>通俗解释</h4>
      <p>{fn.beginner_explanation || "暂无通俗解释。"}</p>
      <h4>常见参数</h4>
      <List items={fn.parameters_explanation} fallback="暂无参数说明。" />
      <h4>返回值</h4>
      <p>{fn.return_explanation || "暂无返回值说明。"}</p>
      <h4>深度学习中的常见用途</h4>
      <p>{fn.common_usage || "需结合调用上下文确认。"}</p>
      {fn.code_example && <pre>{fn.code_example}</pre>}
      <h4>Shape / Tensor 注意事项</h4>
      <p>{fn.shape_or_tensor_note || "暂无注意事项。"}</p>
      <h4>常见误区</h4>
      <List items={fn.common_mistakes} fallback="暂无常见误区。" />
      {fn.related_functions && fn.related_functions.length > 0 && (
        <>
          <h4>相关函数</h4>
          <List items={fn.related_functions} fallback="暂无相关函数。" />
        </>
      )}
      <p className="muted">创建：{fn.created_at || "未知"} · 更新：{fn.updated_at || "未知"}</p>
    </section>
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
