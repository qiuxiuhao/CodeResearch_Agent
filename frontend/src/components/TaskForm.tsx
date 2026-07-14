import { FormEvent, useEffect, useState } from "react";
import { createTaskByPath, createTaskByUpload, getLLMPublicConfig } from "../api/client";
import type { LLMPublicConfig, TaskSummary } from "../types/analysis";

type Props = {
  onTaskCreated: (summary: TaskSummary) => void | Promise<void>;
  onError: (message: string | null) => void;
};

export function TaskForm({ onTaskCreated, onError }: Props) {
  const [inputMode, setInputMode] = useState<"path" | "upload">("path");
  const [textLLMEnabled, setTextLLMEnabled] = useState(false);
  const [visionVLMEnabled, setVisionVLMEnabled] = useState(false);
  const [externalTextConsent, setExternalTextConsent] = useState(false);
  const [externalVisionConsent, setExternalVisionConsent] = useState(false);
  const [llmConfig, setLLMConfig] = useState<LLMPublicConfig | null>(null);
  const [zipPath, setZipPath] = useState("examples/small_pytorch_project.zip");
  const [paperPath, setPaperPath] = useState("");
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [paperFile, setPaperFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    void getLLMPublicConfig().then((config) => {
      setLLMConfig(config);
      setTextLLMEnabled(config.default_text_llm_enabled ?? config.default_analysis_mode === "hybrid");
      setVisionVLMEnabled(config.vision?.default_vision_vlm_enabled ?? false);
    }).catch(() => undefined);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    onError(null);
    try {
      if (textLLMEnabled && !externalTextConsent) {
        throw new Error("启用文本 AI 解释前必须同意将脱敏后的文本分析数据发送到外部模型服务商");
      }
      const hasPaper = inputMode === "path" ? Boolean(paperPath.trim()) : Boolean(paperFile);
      if (visionVLMEnabled && !hasPaper) {
        throw new Error("启用论文 Figure AI 理解前请先提供论文 PDF");
      }
      if (visionVLMEnabled && !externalVisionConsent) {
        throw new Error("启用论文 Figure AI 理解前必须单独同意论文图片外发");
      }
      const summary =
        inputMode === "path"
          ? await createTaskByPath({
              zip_path: zipPath,
              output_root: "outputs",
              paper_pdf_path: paperPath || null,
              analysis_mode: textLLMEnabled ? "hybrid" : "rule",
              external_model_consent: externalTextConsent,
              text_llm_enabled: textLLMEnabled,
              vision_vlm_enabled: visionVLMEnabled,
              external_text_consent: externalTextConsent,
              external_vision_consent: externalVisionConsent
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
    formData.append("analysis_mode", textLLMEnabled ? "hybrid" : "rule");
    formData.append("external_model_consent", String(externalTextConsent));
    formData.append("text_llm_enabled", String(textLLMEnabled));
    formData.append("vision_vlm_enabled", String(visionVLMEnabled));
    formData.append("external_text_consent", String(externalTextConsent));
    formData.append("external_vision_consent", String(externalVisionConsent));
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
          <legend>可选 AI 增强（默认仅规则分析）</legend>
          <label className="checkbox-label">
            <input type="checkbox" checked={textLLMEnabled} onChange={(event) => {
              setTextLLMEnabled(event.target.checked);
              if (!event.target.checked) setExternalTextConsent(false);
            }} />
            文本 AI 解释（函数、文件、模型和论文代码对齐）
          </label>
          {textLLMEnabled && (
            <div className="consent-panel">
              <p>{llmConfig?.external_model_notice ?? "脱敏后的代码与论文片段可能发送到外部模型服务商，并可能产生费用。"}</p>
              <p>
                最多选择逻辑分析实体：{llmConfig?.max_total_entities ?? 30}；
                最多发送外部 Provider 请求：{llmConfig?.max_provider_requests ?? 60}；
                最大并发：{llmConfig?.max_concurrency ?? 2}。
              </p>
              <p className="muted">逻辑实体数不是 API 请求数；重试和 fallback 会增加真实请求，缓存命中不会发送请求。</p>
              <label className="checkbox-label">
                <input type="checkbox" checked={externalTextConsent} onChange={(event) => setExternalTextConsent(event.target.checked)} />
                我确认脱敏后的文本分析内容允许发送到外部模型服务商
              </label>
            </div>
          )}
          <label className="checkbox-label">
            <input type="checkbox" checked={visionVLMEnabled} onChange={(event) => {
              setVisionVLMEnabled(event.target.checked);
              if (!event.target.checked) setExternalVisionConsent(false);
            }} />
            论文 Figure AI 理解（需要提供 PDF）
          </label>
          {visionVLMEnabled && (
            <div className="consent-panel vision-consent-panel">
              <p>{llmConfig?.vision?.external_vision_notice ?? "筛选并渲染后的论文 Figure 可能发送给第三方视觉模型服务商，并可能产生费用；不会发送整个 PDF。"}</p>
              <p>
                最多分析 Figure：{llmConfig?.vision?.max_figure_analyses ?? 5}；
                最多发送视觉 Provider 请求：{llmConfig?.vision?.max_provider_requests ?? 10}；
                最大并发：{llmConfig?.vision?.max_concurrency ?? 2}。
              </p>
              <label className="checkbox-label">
                <input type="checkbox" checked={externalVisionConsent} onChange={(event) => setExternalVisionConsent(event.target.checked)} />
                我确认筛选后的论文 Figure 和相关上下文允许发送到外部视觉模型服务商
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
