import { render, screen, within } from "@testing-library/react";
import { TaskProgressPanel } from "../components/TaskProgressPanel";
import type { TaskProgress } from "../types/analysis";

test("renders LangGraph node progress and current step", () => {
  const progress: TaskProgress = {
    task_id: "task_progress",
    status: "running",
    current_node: "file_analyze",
    current_label: "文件级分析",
    completed_nodes: 3,
    total_nodes: 21,
    percent: 14,
    error: null,
    summary: null,
    steps: [
      { id: "unzip", label: "解压项目", status: "done" },
      { id: "repo_scan", label: "扫描仓库", status: "done" },
      { id: "code_parse", label: "解析 Python AST", status: "done" },
      { id: "file_analyze", label: "文件级分析", status: "running" },
      { id: "report_generate", label: "生成报告", status: "pending" }
    ]
  };

  render(<TaskProgressPanel progress={progress} />);
  const steps = within(screen.getByLabelText("LangGraph 节点进度"));

  expect(screen.getByText("分析中")).toBeInTheDocument();
  expect(screen.getAllByText("文件级分析")).toHaveLength(2);
  expect(screen.getByText("14%")).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "14");
  expect(screen.getByText("节点 3/21")).toBeInTheDocument();
  expect(steps.getByText("扫描仓库")).toHaveClass("done");
  expect(steps.getByText("生成报告")).toHaveClass("pending");
});


test("renders failed progress with node error", () => {
  render(
    <TaskProgressPanel
      progress={{
        task_id: "task_failed",
        status: "failed",
        current_node: "model_analyze",
        current_label: "模型结构分析",
        completed_nodes: 6,
        total_nodes: 21,
        percent: 29,
        error: "模型分析失败",
        summary: null,
        steps: [
          { id: "function_analyze", label: "函数级分析", status: "done" },
          { id: "model_analyze", label: "模型结构分析", status: "failed" }
        ]
      }}
    />
  );

  const steps = within(screen.getByLabelText("LangGraph 节点进度"));

  expect(screen.getByText("分析失败")).toBeInTheDocument();
  expect(screen.getByText("模型分析失败")).toBeInTheDocument();
  expect(steps.getByText("模型结构分析")).toHaveClass("failed");
});
