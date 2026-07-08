import { fireEvent, render, screen } from "@testing-library/react";
import { LibraryFunctionModal } from "../components/LibraryFunctionModal";

test("shows teaching explanation when doc exists", () => {
  const onClose = vi.fn();
  render(
    <LibraryFunctionModal
      call={{ canonical_name: "torch.randn", call_text: "torch.randn(2, 3)", line_no: 10 }}
      doc={{
        canonical_name: "torch.randn",
        summary: "生成随机张量",
        beginner_explanation: "可以理解为造一批随机数字。",
        parameters_explanation: ["size: 输出形状"],
        return_explanation: "Tensor",
        common_mistakes: ["注意随机性"]
      }}
      onClose={onClose}
    />
  );

  expect(screen.getByText("生成随机张量")).toBeInTheDocument();
  expect(screen.getByText("可以理解为造一批随机数字。")).toBeInTheDocument();
  fireEvent.click(screen.getByText("关闭"));
  expect(onClose).toHaveBeenCalled();
});

test("shows fallback when doc is missing", () => {
  render(
    <LibraryFunctionModal
      call={{ canonical_name: "unknown.call", call_text: "x.call()" }}
      onClose={vi.fn()}
    />
  );

  expect(screen.getByText("暂无教学解释。当前只显示本次调用信息。")).toBeInTheDocument();
});
