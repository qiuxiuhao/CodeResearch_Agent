import { act, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { MermaidBlock } from "../components/MermaidBlock";

const mermaidMock = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn()
}));

vi.mock("mermaid", () => ({ default: mermaidMock }));

beforeEach(() => {
  mermaidMock.initialize.mockReset();
  mermaidMock.render.mockReset();
});

test("loads and renders Mermaid only after the block mounts", async () => {
  mermaidMock.render.mockResolvedValue({ svg: "<svg data-testid='rendered-diagram'></svg>" });
  render(<MermaidBlock code="graph TD\nA-->B" />);

  expect(await screen.findByTestId("rendered-diagram")).toBeInTheDocument();
  expect(mermaidMock.initialize).toHaveBeenCalledOnce();
  expect(mermaidMock.render).toHaveBeenCalledOnce();
});

test("shows source fallback when Mermaid rendering fails", async () => {
  mermaidMock.render.mockRejectedValue(new Error("invalid diagram"));
  render(<MermaidBlock code="not mermaid" />);

  expect(await screen.findByText("Mermaid 渲染失败，已回退到源码展示。")).toBeInTheDocument();
  expect(screen.getByText("not mermaid")).toBeInTheDocument();
});

test("ignores a render result that arrives after unmount", async () => {
  let resolveRender: (value: { svg: string }) => void = () => undefined;
  mermaidMock.render.mockReturnValue(new Promise((resolve) => {
    resolveRender = resolve;
  }));
  const view = render(<MermaidBlock code="graph TD\nA-->B" />);

  await act(async () => undefined);
  expect(mermaidMock.render).toHaveBeenCalledOnce();
  view.unmount();
  await act(async () => resolveRender({ svg: "<svg data-testid='late-diagram'></svg>" }));

  expect(screen.queryByTestId("late-diagram")).not.toBeInTheDocument();
});
