import { render, screen } from "@testing-library/react";
import { GlobalLibraryDetail } from "../components/GlobalLibraryDetail";

test("renders global library teaching detail", () => {
  render(
    <GlobalLibraryDetail
      detail={{
        function: {
          canonical_name: "torch.nn.Linear",
          package_name: "torch",
          category: "pytorch",
          confidence: "high",
          summary: "创建全连接层。",
          beginner_explanation: "把输入特征映射到输出特征。",
          parameters_explanation: ["in_features：输入特征数"],
          return_explanation: "返回 Linear 模块。",
          common_usage: "分类头。",
          shape_or_tensor_note: "最后一维要匹配。",
          common_mistakes: ["把 batch size 当成 in_features"]
        }
      }}
    />
  );

  expect(screen.getByText("torch.nn.Linear")).toBeInTheDocument();
  expect(screen.getByText("创建全连接层。")).toBeInTheDocument();
});
