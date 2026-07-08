import { fireEvent, render, screen } from "@testing-library/react";
import { FunctionDetail } from "../components/FunctionDetail";

test("beginner mode displays library calls and click opens callback", () => {
  const onLibraryCallClick = vi.fn();
  render(
    <FunctionDetail
      mode="beginner"
      onLibraryCallClick={onLibraryCallClick}
      fn={{
        qualified_name: "SimpleNet.forward",
        purpose: "前向传播",
        beginner_explanation: "输入张量经过线性层和激活函数。",
        implementation_logic: ["调用 fc1", "调用 relu"],
        library_calls: [
          {
            canonical_name: "torch.nn.functional.relu",
            call_text: "F.relu(x)",
            line_no: 12,
            confidence: "high",
            category: "torch"
          }
        ]
      }}
    />
  );

  expect(screen.getByText("零基础解释")).toBeInTheDocument();
  expect(screen.getByText("本函数调用的库函数")).toBeInTheDocument();
  fireEvent.click(screen.getByText(/torch.nn.functional.relu/));
  expect(onLibraryCallClick).toHaveBeenCalledWith(expect.objectContaining({ canonical_name: "torch.nn.functional.relu" }));
});

test("low confidence unknown calls are visually weakened", () => {
  render(
    <FunctionDetail
      mode="beginner"
      onLibraryCallClick={vi.fn()}
      fn={{
        qualified_name: "train_one_epoch",
        purpose: "训练一轮",
        library_calls: [
          {
            canonical_name: "output.mean",
            category: "unknown",
            confidence: "low",
            call_text: "output.mean()"
          }
        ]
      }}
    />
  );

  expect(screen.getByText(/output.mean/)).toHaveClass("low");
});
