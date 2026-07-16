import { render, screen } from "@testing-library/react";
import { AIBudgetPanel } from "../components/AIBudgetPanel";

test("does not treat unknown provider configuration as unconfigured", () => {
  render(
    <AIBudgetPanel
      usage={{
        text_analysis: {
          enabled: true,
          consent: true,
          configured: null
        }
      }}
    />
  );

  expect(screen.getByText("可用")).toBeInTheDocument();
  expect(screen.queryByText("Provider 未配置")).not.toBeInTheDocument();
});

test("shows missing configuration only when provider status is explicitly false", () => {
  render(
    <AIBudgetPanel
      usage={{
        text_analysis: {
          enabled: true,
          consent: true,
          configured: false
        }
      }}
    />
  );

  expect(screen.getByText("缺少配置")).toBeInTheDocument();
  expect(screen.getByText("Provider 未配置")).toBeInTheDocument();
});
