import { fireEvent, render, screen } from "@testing-library/react";
import { FunctionAnalysisPanel } from "../components/FunctionAnalysisPanel";
import type { AnalysisResult } from "../types/analysis";

test("same-named functions in different files can be selected independently", () => {
  const result: AnalysisResult = {
    task_id: "same-name-functions",
    function_analysis: {
      function_analysis: [
        { file_path: "a.py", qualified_name: "process", function_name: "process", purpose: "处理 A" },
        { file_path: "b.py", qualified_name: "process", function_name: "process", purpose: "处理 B" }
      ]
    },
    llm_explanations: {
      function_explanations: [
        { file_path: "a.py", qualified_name: "process", summary: "A 文件解释" },
        { file_path: "b.py", qualified_name: "process", summary: "B 文件解释" }
      ]
    }
  };

  render(<FunctionAnalysisPanel result={result} mode="normal" onLibraryCallClick={vi.fn()} />);

  const aButton = screen.getByText("a.py").closest("button");
  const bButton = screen.getByText("b.py").closest("button");
  expect(aButton).toHaveClass("active");
  expect(bButton).not.toHaveClass("active");
  fireEvent.click(screen.getByRole("button", { name: "AI 解释" }));
  expect(screen.getByText("A 文件解释")).toBeInTheDocument();

  fireEvent.click(bButton!);
  expect(aButton).not.toHaveClass("active");
  expect(bButton).toHaveClass("active");
  fireEvent.click(screen.getByRole("button", { name: "AI 解释" }));
  expect(screen.getByText("B 文件解释")).toBeInTheDocument();
});
