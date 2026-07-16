import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { DiagramsPanel } from "../components/DiagramsPanel";
import type { AnalysisResult } from "../types/analysis";

vi.mock("../components/MermaidBlock", () => ({
  MermaidBlock: ({ code }: { code: string }) => <pre data-testid="mermaid-block">{code}</pre>
}));

test("switches between Mermaid Blueprint and AI teaching views", () => {
  render(<DiagramsPanel result={resultWithTeaching({ display_variant: "ai", final_asset: asset("final") })} />);

  expect(screen.getByAltText(/AI 教学图/)).toHaveAttribute("src", expect.stringContaining("final.png"));
  fireEvent.click(screen.getByRole("button", { name: "Mermaid" }));
  expect(screen.getAllByTestId("mermaid-block").some((item) => item.textContent?.includes("graph TD"))).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Blueprint" }));
  expect(screen.getByAltText(/Blueprint/)).toHaveAttribute("src", expect.stringContaining("blueprint.png"));
  fireEvent.click(screen.getByRole("button", { name: "AI 教学图" }));
  expect(screen.getByText(/可能存在简化/)).toBeInTheDocument();
});

test("disables AI tab and defaults to Blueprint when review did not pass", () => {
  render(<DiagramsPanel result={resultWithTeaching({ display_variant: "blueprint", final_asset: null, fallback_reason: "review_failed_fallback_blueprint" })} />);

  expect(screen.getByRole("button", { name: "AI 教学图" })).toBeDisabled();
  expect(screen.getByAltText(/Blueprint/)).toHaveAttribute("src", expect.stringContaining("blueprint.png"));
  expect(screen.getByText(/review_failed_fallback_blueprint/)).toBeInTheDocument();
});

test("prefers SVG Blueprint when Chinese font fallback warning is present", () => {
  render(<DiagramsPanel result={resultWithTeaching({ warnings: ["teaching_diagram_font_unavailable"] })} />);

  expect(screen.getByAltText(/Blueprint/)).toHaveAttribute("src", expect.stringContaining("blueprint.svg"));
});

function resultWithTeaching(overrides: Record<string, unknown> = {}): AnalysisResult {
  return {
    task_id: "task_demo",
    diagrams: {
      version: "1.2",
      diagrams: [
        { id: "model_flow", diagram_type: "model_flow", title: "模型流程", mermaid: "graph TD\nA-->B", description: "模型流程" }
      ]
    },
    teaching_diagrams: {
      version: "1.3.2",
      status: "success",
      diagrams: [
        {
          diagram_id: "td_demo",
          title: "教学图",
          related_mermaid_diagram_ids: ["model_flow"],
          source_entity: { entity_type: "model", entity_id: "model:x", title: "模型" },
          spec_path: "teaching_diagrams/specs/td_demo.json",
          blueprint_svg: asset("blueprint_svg"),
          blueprint_png: asset("blueprint_png"),
          display_variant: "blueprint",
          display_asset: asset("blueprint_png"),
          fallback_reason: null,
          warnings: [],
          ...overrides
        }
      ]
    }
  } as AnalysisResult;
}

function asset(name: string) {
  return {
    path: `teaching_diagrams/${name}.png`,
    mime_type: "image/png",
    width: 1280,
    height: 720,
    byte_size: 123,
    sha256: "a".repeat(64)
  };
}
