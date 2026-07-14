import { figureAssetUrl, figurePreviewUrl } from "../api/client";
import type { PaperFigure } from "../types/analysis";

export function PaperFigureGallery({ taskId, figures }: { taskId: string; figures: PaperFigure[] }) {
  if (!figures.length) return <p className="muted">未检测到可展示的 Figure。</p>;
  return (
    <div className="figure-gallery">
      {figures.map((figure) => {
        const analysis = figure.vlm_analysis;
        return (
          <article className="figure-card" key={figure.figure_id}>
            {figure.canonical_preview ? (
              <img src={figurePreviewUrl(taskId, figure.figure_id)} alt={`${figure.caption.label}: ${figure.caption.text}`} />
            ) : <div className="figure-placeholder">Preview 不可用</div>}
            <div className="figure-content">
              <h4>{figure.caption.label}</h4>
              <p>{figure.caption.text}</p>
              <p className="muted">第 {figure.page_number} 页 · Figure ID：{figure.figure_id}</p>
              <details>
                <summary>提取信息与原始资产</summary>
                <p>bbox：{figure.bbox.join(", ")}</p>
                <p>normalized bbox：{figure.normalized_bbox.join(", ")}</p>
                <p>原始资产：{figure.original_assets?.length ?? 0} 个</p>
                {!!figure.original_assets?.length && (
                  <div className="chip-row">
                    {figure.original_assets.map((asset, index) => (
                      <a
                        className="chip"
                        href={figureAssetUrl(taskId, figure.figure_id, asset.asset_id)}
                        key={asset.asset_id}
                        rel="noreferrer"
                        target="_blank"
                      >
                        查看原始资产 {index + 1}
                      </a>
                    ))}
                  </div>
                )}
              </details>
              {analysis ? (
                <div className="vlm-analysis">
                  <strong>AI Figure 类型：{analysis.figure_type}</strong>
                  <p>{analysis.summary}</p>
                  {!!analysis.modules?.length && <p>模块：{analysis.modules.map((item) => `${item.name}（${item.role}）`).join("；")}</p>}
                  {!!analysis.flows?.length && <p>流程：{analysis.flows.map((item) => `${item.source} → ${item.target}`).join("；")}</p>}
                  {!!analysis.contribution_candidates?.length && (
                    <p>论文贡献候选：{analysis.contribution_candidates.map((item) => `${item.contribution_id}（${item.confidence}，AI 建议）`).join("；")}</p>
                  )}
                  {!!analysis.uncertainties?.length && <p className="muted">不确定性：{analysis.uncertainties.join("；")}</p>}
                </div>
              ) : <p className="muted">暂无 VLM 分析；本地 Figure 提取结果仍可使用。</p>}
            </div>
          </article>
        );
      })}
    </div>
  );
}
