import { FormEvent, useState } from "react";
import { createTaskByPath, createTaskByUpload } from "../api/client";
import type { TaskSummary } from "../types/analysis";

type Props = {
  onTaskCreated: (summary: TaskSummary) => void | Promise<void>;
  onError: (message: string | null) => void;
};

export function TaskForm({ onTaskCreated, onError }: Props) {
  const [mode, setMode] = useState<"path" | "upload">("path");
  const [zipPath, setZipPath] = useState("examples/small_pytorch_project.zip");
  const [paperPath, setPaperPath] = useState("");
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [paperFile, setPaperFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    onError(null);
    try {
      const summary =
        mode === "path"
          ? await createTaskByPath({
              zip_path: zipPath,
              output_root: "outputs",
              paper_pdf_path: paperPath || null
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
    if (paperFile) {
      formData.append("paper_pdf", paperFile);
    }
    return createTaskByUpload(formData);
  }

  return (
    <section className="panel">
      <h2>创建分析任务</h2>
      <div className="button-row">
        <button className={mode === "path" ? "primary-button" : "secondary-button"} onClick={() => setMode("path")} type="button">
          本地路径
        </button>
        <button className={mode === "upload" ? "primary-button" : "secondary-button"} onClick={() => setMode("upload")} type="button">
          浏览器上传
        </button>
      </div>
      <form className="task-form" onSubmit={submit}>
        {mode === "path" ? (
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
        <button className="primary-button" disabled={isSubmitting} type="submit">
          {isSubmitting ? "分析中..." : "开始分析"}
        </button>
      </form>
    </section>
  );
}
