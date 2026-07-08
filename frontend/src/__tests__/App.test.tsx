import { render, screen } from "@testing-library/react";
import App from "../App";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ tasks: [] })
    }))
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("renders the interactive workspace shell", async () => {
  render(<App />);

  expect(screen.getAllByText("CodeResearch Agent").length).toBeGreaterThan(0);
  expect(await screen.findByText("暂无历史任务")).toBeInTheDocument();
  expect(screen.getByText("创建分析任务")).toBeInTheDocument();
  expect(screen.getByText("正常模式")).toBeInTheDocument();
  expect(screen.getByText("零基础模式")).toBeInTheDocument();
});
