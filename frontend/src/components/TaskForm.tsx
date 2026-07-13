import { FormEvent, useEffect, useState } from "react";
import { createTaskByPath, createTaskByUpload, getLLMPublicConfig } from "../api/client";
import type { AnalysisMode, LLMPublicConfig, TaskSummary } from "../types/analysis";

type Props = {
  onTaskCreated: (summary: TaskSummary) => void | Promise<void>;
  onError: (message: string | null) => void;
};

export function TaskForm({ onTaskCreated, onError }: Props) {
  const [inputMode, setInputMode] = useState<"path" | "upload">("path");
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>("rule");
  const [externalModelConsent, setExternalModelConsent] = useState(false);
  const [llmConfig, setLLMConfig] = useState<LLMPublicConfig | null>(null);
  const [zipPath, setZipPath] = useState("examples/small_pytorch_project.zip");
  const [paperPath, setPaperPath] = useState("");
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [paperFile, setPaperFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    void getLLMPublicConfig().then((config) => {
      setLLMConfig(config);
      setAnalysisMode(config.default_analysis_mode ?? "rule");
    }).catch(() => undefined);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    onError(null);
    try {
      if (analysisMode === "hybrid" && !externalModelConsent) {
        throw new Error("启用 hybrid 模式前必须同意将脱敏后的分析数据发送到外部模型服务商");
      }
      const summary =
        inputMode === "path"
          ? await createTaskByPath({
              zip_path: zipPath,
              output_root: "outputs",
              paper_pdf_path: paperPath || null,
              analysis_mode: analysisMode,
              external_model_consent: externalModelConsent
            })
          : await submitUpload();
      await onTaskCreated(summary);
    } catch (exc) {
      onError(exc instanceof Error ? exc.message : "创建任务失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function submitUpload() {
    if (!zipFile) {
      throw new Error("请选择 ZIP 文件");
    }
    const formData = new FormData();
    formData.append("zip_file", zipFile);
    formData.append("output_root", "outputs");
    formData.append("analysis_mode", analysisMode);
    formData.append("external_model_consent", String(externalModelConsent));
    if (paperFile) {
      formData.append("paper_pdf", paperFile);
    }
    return createTaskByUpload(formData);
  }

  return (
    <section className="panel">
      <h2>创建分析任务</h2>
      <div className="button-row">
        <button className={inputMode === "path" ? "primary-button" : "secondary-button"} onClick={() => setInputMode("path")} type="button">
          本地路径
        </button>
        <button className={inputMode === "upload" ? "primary-button" : "secondary-button"} onClick={() => setInputMode("upload")} type="button">
          浏览器上传
        </button>
      </div>
      <form className="task-form" onSubmit={submit}>
        {inputMode === "path" ? (
          <>
            <label>
              ZIP 路径
              <input value={zipPath} onChange={(event) => setZipPath(event.target.value)} />
            </label>
            <label>
              论文 PDF 路径（可选）
              <input value={paperPath} onChange={(event) => setPaperPath(event.target.value)} placeholder="examples/paper.pdf" />
            </label>
          </>
        ) : (
          <>
            <label>
              ZIP 文件
              <input accept=".zip" type="file" onChange={(event) => setZipFile(event.target.files?.[0] ?? null)} />
            </label>
            <label>
              论文 PDF（可选）
              <input accept=".pdf" type="file" onChange={(event) => setPaperFile(event.target.files?.[0] ?? null)} />
            </label>
          </>
        )}
        <fieldset className="llm-options">
          <legend>分析方式</legend>
          <label>
            模式
            <select value={analysisMode} onChange={(event) => {
              const next = event.target.value as AnalysisMode;
              setAnalysisMode(next);
              if (next === "rule") setExternalModelConsent(false);
            }}>
              <option value="rule">规则模式（默认，不调用外部模型）</option>
              <option value="hybrid">Hybrid：规则事实 + AI 教学解释</option>
            </select>
          </label>
          {analysisMode === "hybrid" && (
            <div className="consent-panel">
              <p>{llmConfig?.external_model_notice ?? "脱敏后的代码与论文片段可能发送到外部模型服务商，并可能产生费用。"}</p>
              <p>
                最多选择逻辑分析实体：{llmConfig?.max_total_entities ?? 30}；
                最多发送外部 Provider 请求：{llmConfig?.max_provider_requests ?? 60}；
                最大并发：{llmConfig?.max_concurrency ?? 2}。
              </p>
              <p className="muted">逻辑实体数不是 API 请求数；重试和 fallback 会增加真实请求，缓存命中不会发送请求。</p>
              <label className="checkbox-label">
                <input type="checkbox" checked={externalModelConsent} onChange={(event) => setExternalModelConsent(event.target.checked)} />
                我确认这些内容允许发送到外部模型服务商
              </label>
            </div>
          )}
        </fieldset>
        <button className="primary-button" disabled={isSubmitting} type="submit">
          {isSubmitting ? "分析中..." : "开始分析"}
        </button>
      </form>
    </section>
  );
}
