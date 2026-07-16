import { fireEvent, render, screen } from "@testing-library/react";
import { FileAnalysisPanel } from "../components/FileAnalysisPanel";
import { ModelAnalysisPanel } from "../components/ModelAnalysisPanel";
import type { AnalysisResult } from "../types/analysis";

test("file analysis shows one selected file and separates AI explanation", () => {
  const result: AnalysisResult = {
    task_id: "file-panel",
    file_analysis: {
      file_analysis: [
        { file_path: "a.py", file_type: "entry", purpose: "A 文件", main_functions: ["main"] },
        { file_path: "b.py", file_type: "model", purpose: "B 文件", main_classes: ["Net"] }
      ]
    },
    llm_explanations: {
      file_explanations: [
        { file_path: "a.py", summary: "A AI 解释" },
        { file_path: "b.py", summary: "B AI 解释" }
      ]
    }
  };

  render(<FileAnalysisPanel result={result} mode="normal" />);

  expect(screen.getByRole("button", { name: /a.py/ })).toHaveClass("active");
  expect(screen.getByText("A 文件")).toBeInTheDocument();
  expect(screen.queryByText("B 文件")).not.toBeInTheDocument();
  expect(screen.queryByText("A AI 解释")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "AI 解释" }));
  expect(screen.getByText("A AI 解释")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /b.py/ }));
  expect(screen.getByText("B AI 解释")).toBeInTheDocument();
});

test("model analysis shows one selected model and separates AI explanation", () => {
  const result: AnalysisResult = {
    task_id: "model-panel",
    model_analysis: {
      model_analysis: [
        { file_path: "a.py", class_name: "NetA", is_main_model_candidate: true, model_inputs: ["x"], model_outputs: ["y"] },
        { file_path: "b.py", class_name: "NetB", is_main_model_candidate: false, model_inputs: ["image"], model_outputs: ["logits"] }
      ]
    },
    llm_explanations: {
      model_explanations: [
        { file_path: "a.py", class_name: "NetA", summary: "NetA AI 解释" },
        { file_path: "b.py", class_name: "NetB", summary: "NetB AI 解释" }
      ]
    }
  };

  render(<ModelAnalysisPanel result={result} mode="normal" />);

  expect(screen.getByRole("button", { name: /NetA/ })).toHaveClass("active");
  expect(screen.getByText("输入：x")).toBeInTheDocument();
  expect(screen.queryByText("输入：image")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /NetB/ }));
  expect(screen.getByText("输入：image")).toBeInTheDocument();
  expect(screen.queryByText("NetB AI 解释")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "AI 解释" }));
  expect(screen.getByText("NetB AI 解释")).toBeInTheDocument();
});
