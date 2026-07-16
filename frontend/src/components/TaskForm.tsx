import { FormEvent, useEffect, useState } from "react";
import {
  createTaskByPathAsync,
  createTaskByUploadAsync,
  getLLMPublicConfig,
  getProviderSettings,
  getTaskProgress
} from "../api/client";
import { PROVIDER_SETTINGS_UPDATED } from "../providerSettingsEvents";
import type { LLMPublicConfig, ProviderPublicSettings, TaskProgress, TaskSummary } from "../types/analysis";
import { TaskProgressPanel } from "./TaskProgressPanel";

type Props = {
  onTaskCreated: (summary: TaskSummary) => void | Promise<void>;
  onError: (message: string | null) => void;
  onOpenSettings?: () => void;
};

export function TaskForm({ onTaskCreated, onError, onOpenSettings }: Props) {
  const [inputMode, setInputMode] = useState<"path" | "upload">("path");
  const [textLLMEnabled, setTextLLMEnabled] = useState(false);
  const [teachingNarrativeLLMEnabled, setTeachingNarrativeLLMEnabled] = useState(false);
  const [visionVLMEnabled, setVisionVLMEnabled] = useState(false);
  const [imageGenerationEnabled, setImageGenerationEnabled] = useState(false);
  const [teachingReviewVLMEnabled, setTeachingReviewVLMEnabled] = useState(false);
  const [externalTextConsent, setExternalTextConsent] = useState(false);
  const [externalVisionConsent, setExternalVisionConsent] = useState(false);
  const [externalImageConsent, setExternalImageConsent] = useState(false);
  const [externalTeachingReviewConsent, setExternalTeachingReviewConsent] = useState(false);
  const [llmConfig, setLLMConfig] = useState<LLMPublicConfig | null>(null);
  const [zipPath, setZipPath] = useState("examples/small_pytorch_project.zip");
  const [paperPath, setPaperPath] = useState("");
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [paperFile, setPaperFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [progress, setProgress] = useState<TaskProgress | null>(null);
  const [providers, setProviders] = useState<ProviderPublicSettings[] | null>(null);

  useEffect(() => {
    void getLLMPublicConfig().then((config) => {
      setLLMConfig(config);
      setTextLLMEnabled(config.default_text_llm_enabled ?? config.default_analysis_mode === "hybrid");
      setTeachingNarrativeLLMEnabled(config.default_teaching_narrative_llm_enabled ?? config.default_text_llm_enabled ?? false);
      setVisionVLMEnabled(config.vision?.default_vision_vlm_enabled ?? false);
    }).catch(() => undefined);
  }, []);

  useEffect(() => {
    let active = true;
    async function refreshProviders() {
      try {
        const response = await getProviderSettings();
        if (active) setProviders(Array.isArray(response.providers) ? response.providers : []);
      } catch {
        if (active) setProviders(null);
      }
    }
    void refreshProviders();
    const handleProviderUpdate = () => {
      void refreshProviders();
    };
    window.addEventListener(PROVIDER_SETTINGS_UPDATED, handleProviderUpdate);
    return () => {
      active = false;
      window.removeEventListener(PROVIDER_SETTINGS_UPDATED, handleProviderUpdate);
    };
  }, []);

  useEffect(() => {
    if (!imageGenerationEnabled) {
      setTeachingReviewVLMEnabled(false);
      setExternalTeachingReviewConsent(false);
    }
  }, [imageGenerationEnabled]);

  const textProvider = providerGroupStatus(providers, "text_llm");
  const visionProvider = providerGroupStatus(providers, "vision_vlm");
  const imageProvider = providerGroupStatus(providers, "image_generation");

  useEffect(() => {
    if (providers === null) return;
    if (!textProvider.configured) {
      setTextLLMEnabled(false);
      setTeachingNarrativeLLMEnabled(false);
      setExternalTextConsent(false);
    }
    if (!visionProvider.configured) {
      setVisionVLMEnabled(false);
      setTeachingReviewVLMEnabled(false);
      setExternalVisionConsent(false);
      setExternalTeachingReviewConsent(false);
    }
    if (!imageProvider.configured) {
      setImageGenerationEnabled(false);
      setExternalImageConsent(false);
    }
  }, [
    providers,
    textProvider.configured,
    visionProvider.configured,
    imageProvider.configured,
    textLLMEnabled,
    teachingNarrativeLLMEnabled,
    visionVLMEnabled,
    imageGenerationEnabled,
    teachingReviewVLMEnabled
  ]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setProgress(null);
    onError(null);
    try {
      if (textLLMEnabled && !externalTextConsent) {
        throw new Error("启用文本 AI 解释前必须同意将脱敏后的文本分析数据发送到外部模型服务商");
      }
      if ((textLLMEnabled || teachingNarrativeLLMEnabled) && providers !== null && !textProvider.configured) {
        throw new Error("文本 LLM Provider 未配置，请先进入 Provider 设置");
      }
      if (teachingNarrativeLLMEnabled && !externalTextConsent) {
        throw new Error("启用教学文案 LLM 前必须同意将脱敏后的教学图结构发送到外部模型服务商");
      }
      const hasPaper = inputMode === "path" ? Boolean(paperPath.trim()) : Boolean(paperFile);
      if (visionVLMEnabled && !hasPaper) {
        throw new Error("启用论文 Figure AI 理解前请先提供论文 PDF");
      }
      if (visionVLMEnabled && providers !== null && !visionProvider.configured) {
        throw new Error("视觉 VLM Provider 未配置，请先进入 Provider 设置");
      }
      if (visionVLMEnabled && !externalVisionConsent) {
        throw new Error("启用论文 Figure AI 理解前必须单独同意论文图片外发");
      }
      if (imageGenerationEnabled && !externalImageConsent) {
        throw new Error("启用 AI 教学图视觉层前必须单独同意脱敏教学图 Spec 外发");
      }
      if (imageGenerationEnabled && providers !== null && !imageProvider.configured) {
        throw new Error("图片生成 Provider 未配置，请先进入 Provider 设置");
      }
      if (teachingReviewVLMEnabled && !imageGenerationEnabled) {
        throw new Error("启用教学图 VLM 审查前必须先启用 AI 教学图视觉层");
      }
      if (teachingReviewVLMEnabled && providers !== null && !visionProvider.configured) {
        throw new Error("教学图 VLM Review Provider 未配置，请先进入 Provider 设置");
      }
      if (teachingReviewVLMEnabled && !externalTeachingReviewConsent) {
        throw new Error("启用教学图 VLM 审查前必须单独同意教学图审查外发");
      }
      let nextProgress =
        inputMode === "path"
          ? await createTaskByPathAsync({
              zip_path: zipPath,
              output_root: "outputs",
              paper_pdf_path: paperPath || null,
              analysis_mode: textLLMEnabled ? "hybrid" : "rule",
              external_model_consent: externalTextConsent,
              text_llm_enabled: textLLMEnabled,
              teaching_narrative_llm_enabled: teachingNarrativeLLMEnabled,
              vision_vlm_enabled: visionVLMEnabled,
              external_text_consent: externalTextConsent,
              external_vision_consent: externalVisionConsent,
              teaching_diagrams_enabled: true,
              image_generation_enabled: imageGenerationEnabled,
              external_image_consent: externalImageConsent,
              teaching_review_vlm_enabled: teachingReviewVLMEnabled,
              external_teaching_review_consent: externalTeachingReviewConsent
            })
          : await submitUpload();
      setProgress(nextProgress);
      while (nextProgress.status === "queued" || nextProgress.status === "running") {
        await delay(700);
        nextProgress = await getTaskProgress(nextProgress.task_id);
        setProgress(nextProgress);
      }
      if (nextProgress.status === "failed") {
        throw new Error(nextProgress.error || "分析任务失败");
      }
      await onTaskCreated(nextProgress.summary ?? { task_id: nextProgress.task_id });
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
    formData.append("teaching_narrative_llm_enabled", String(teachingNarrativeLLMEnabled));
    formData.append("vision_vlm_enabled", String(visionVLMEnabled));
    formData.append("external_text_consent", String(externalTextConsent));
    formData.append("external_vision_consent", String(externalVisionConsent));
    formData.append("teaching_diagrams_enabled", "true");
    formData.append("image_generation_enabled", String(imageGenerationEnabled));
    formData.append("external_image_consent", String(externalImageConsent));
    formData.append("teaching_review_vlm_enabled", String(teachingReviewVLMEnabled));
    formData.append("external_teaching_review_consent", String(externalTeachingReviewConsent));
    if (paperFile) {
      formData.append("paper_pdf", paperFile);
    }
    return createTaskByUploadAsync(formData);
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
          <div className="ai-option-list">
          <label className="checkbox-label option-toggle">
            <input type="checkbox" checked={textLLMEnabled} disabled={providers !== null && !textProvider.configured} onChange={(event) => {
              setTextLLMEnabled(event.target.checked);
              if (!event.target.checked && !teachingNarrativeLLMEnabled) setExternalTextConsent(false);
            }} />
            <span className="option-copy">
              <strong>文本 AI 解释</strong>
              <small>函数、文件、模型和论文代码对齐</small>
            </span>
          </label>
          <ProviderStatusLine label="文本 LLM Provider" status={textProvider} onOpenSettings={onOpenSettings} />
          <label className="checkbox-label option-toggle">
            <input type="checkbox" checked={teachingNarrativeLLMEnabled} disabled={providers !== null && !textProvider.configured} onChange={(event) => {
              setTeachingNarrativeLLMEnabled(event.target.checked);
              if (!event.target.checked && !textLLMEnabled) setExternalTextConsent(false);
            }} />
            <span className="option-copy">
              <strong>教学文案 LLM</strong>
              <small>教学图标题、步骤和学习提示</small>
            </span>
          </label>
          {(textLLMEnabled || teachingNarrativeLLMEnabled) && (
            <div className="consent-panel">
              <p>{llmConfig?.external_model_notice ?? "脱敏后的代码与论文片段可能发送到外部模型服务商，并可能产生费用。"}</p>
              <p>
                最多选择逻辑分析实体：{llmConfig?.max_total_entities ?? 30}；
                最多发送外部 Provider 请求：{llmConfig?.max_provider_requests ?? 60}；
                教学文案最多请求：4；
                最大并发：{llmConfig?.max_concurrency ?? 2}。
              </p>
              <p className="muted">逻辑实体数不是 API 请求数；重试和 fallback 会增加真实请求，缓存命中不会发送请求。</p>
              <label className="checkbox-label">
                <input type="checkbox" checked={externalTextConsent} onChange={(event) => setExternalTextConsent(event.target.checked)} />
                我确认脱敏后的文本分析内容允许发送到外部模型服务商
              </label>
            </div>
          )}
          <label className="checkbox-label option-toggle">
            <input type="checkbox" checked={visionVLMEnabled} disabled={providers !== null && !visionProvider.configured} onChange={(event) => {
              setVisionVLMEnabled(event.target.checked);
              if (!event.target.checked) setExternalVisionConsent(false);
            }} />
            <span className="option-copy">
              <strong>论文 Figure AI 理解</strong>
              <small>需要提供 PDF</small>
            </span>
          </label>
          <ProviderStatusLine label="视觉 VLM Provider" status={visionProvider} onOpenSettings={onOpenSettings} />
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
          <label className="checkbox-label option-toggle">
            <input type="checkbox" checked={imageGenerationEnabled} disabled={providers !== null && !imageProvider.configured} onChange={(event) => {
              setImageGenerationEnabled(event.target.checked);
              if (!event.target.checked) setExternalImageConsent(false);
            }} />
            <span className="option-copy">
              <strong>AI 教学图视觉层</strong>
              <small>Qwen-Image / Seedream，Blueprint 本地生成</small>
            </span>
          </label>
          <ProviderStatusLine label="图片生成 Provider" status={imageProvider} onOpenSettings={onOpenSettings} />
          {imageGenerationEnabled && (
            <div className="consent-panel">
              <p>{llmConfig?.image_generation?.external_image_notice ?? "脱敏后的 TeachingDiagramSpec 可能发送到外部图片生成服务商，并可能产生费用。"}</p>
              <p>
                最多发送图片 Provider 请求：{llmConfig?.image_generation?.max_provider_requests ?? 8}；
                最大并发：{llmConfig?.image_generation?.max_concurrency ?? 2}。
              </p>
              <label className="checkbox-label">
                <input type="checkbox" checked={externalImageConsent} onChange={(event) => setExternalImageConsent(event.target.checked)} />
                我确认脱敏后的教学图 Spec 允许发送到外部图片生成服务商
              </label>
            </div>
          )}
          <label className="checkbox-label option-toggle">
            <input
              type="checkbox"
              checked={teachingReviewVLMEnabled}
              disabled={!imageGenerationEnabled || (providers !== null && !visionProvider.configured)}
              onChange={(event) => {
                setTeachingReviewVLMEnabled(event.target.checked);
                if (!event.target.checked) setExternalTeachingReviewConsent(false);
              }}
            />
            <span className="option-copy">
              <strong>教学图 VLM Review</strong>
              <small>依赖 AI 教学图视觉层</small>
            </span>
          </label>
          {!imageGenerationEnabled && <p className="muted inline-note">AI 教学图视觉层关闭时，Review 自动关闭。</p>}
          {teachingReviewVLMEnabled && (
            <div className="consent-panel vision-consent-panel">
              <p>本地合成后的教学图图片和脱敏 public spec 可能发送到外部视觉模型服务商。</p>
              <p>
                最多发送审查 Provider 请求：{llmConfig?.image_generation?.max_provider_requests ?? 8}；
                缓存命中不会发送请求。
              </p>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={externalTeachingReviewConsent}
                  onChange={(event) => setExternalTeachingReviewConsent(event.target.checked)}
                />
                我确认教学图 Review 图片和 public spec 允许发送到外部视觉模型服务商
              </label>
            </div>
          )}
          </div>
        </fieldset>
        <button className="primary-button" disabled={isSubmitting} type="submit">
          {isSubmitting ? "分析中..." : "开始分析"}
        </button>
        {progress && <TaskProgressPanel progress={progress} />}
      </form>
    </section>
  );
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

type ProviderGroup = ProviderPublicSettings["group"];
type ProviderGroupStatus = {
  loaded: boolean;
  configured: boolean;
  label: string;
};

function providerGroupStatus(providers: ProviderPublicSettings[] | null, group: ProviderGroup): ProviderGroupStatus {
  if (providers === null) {
    return { loaded: false, configured: false, label: "读取中" };
  }
  const enabled = providers.filter((provider) => provider.group === group && provider.enabled);
  const configured = enabled.find((provider) => provider.configured);
  if (configured) {
    const model = typeof configured.fields.model === "string" ? configured.fields.model : "";
    return { loaded: true, configured: true, label: `${configured.display_name}${model ? ` / ${model}` : ""}` };
  }
  return { loaded: true, configured: false, label: "未配置" };
}

function ProviderStatusLine({
  label,
  status,
  onOpenSettings
}: {
  label: string;
  status: ProviderGroupStatus;
  onOpenSettings?: () => void;
}) {
  return (
    <p className={`provider-status-line ${status.loaded && !status.configured ? "missing" : "ready"}`}>
      <span>{label}：{status.label}</span>
      {status.loaded && !status.configured && onOpenSettings && (
        <button className="inline-link-button" onClick={onOpenSettings} type="button">
          进入设置
        </button>
      )}
    </p>
  );
}
