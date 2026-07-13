import { render, screen } from "@testing-library/react";
import { AIExplanationCard } from "../components/AIExplanationCard";

const explanation = {
  summary: "基于静态事实的总结",
  teaching_explanation: "面向初学者的解释",
  evidence_refs: ["function:model.py:Net.forward:10-12"],
  metadata: { provider: "deepseek", model: "deepseek-chat", total_tokens: 42 }
};

test("AI explanation is labelled and keeps beginner content mode-specific", () => {
  const { rerender } = render(<AIExplanationCard explanation={explanation} mode="normal" />);
  expect(screen.getByText("AI 增强解释（基于静态分析事实）")).toBeInTheDocument();
  expect(screen.queryByText("面向初学者的解释")).not.toBeInTheDocument();

  rerender(<AIExplanationCard explanation={explanation} mode="beginner" />);
  expect(screen.getByText("面向初学者的解释")).toBeInTheDocument();
  expect(screen.getByText(/function:model.py/)).toBeInTheDocument();
});
