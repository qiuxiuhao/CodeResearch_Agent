import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { DiagramsPanel } from "../components/DiagramsPanel";
import type { AnalysisResult } from "../types/analysis";
import { setActiveScope } from "../api/v2Client";

vi.mock("../components/MermaidBlock", () => ({
  MermaidBlock: ({ code }: { code: string }) => <pre data-testid="mermaid-block">{code}</pre>
}));

beforeEach(() => {
  setActiveScope("workspace-a", "project-a");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(new Blob(["image"], {type: "image/png"}))));
  Object.defineProperty(URL, "createObjectURL", {configurable: true, value: vi.fn(() => "blob:protected-diagram")});
  Object.defineProperty(URL, "revokeObjectURL", {configurable: true, value: vi.fn()});
});

afterEach(() => vi.unstubAllGlobals());

test("switches between protected Blueprint and AI teaching views without duplicating Mermaid", async () => {
  render(<DiagramsPanel result={resultWithTeaching({ display_variant: "ai", final_asset: asset("final") })} />);

  await waitFor(() => expect(screen.getByAltText(/AI 教学图/)).toHaveAttribute("src", "blob:protected-diagram"));
  expect(screen.queryByRole("button", { name: "Mermaid" })).not.toBeInTheDocument();
  expect(screen.queryByTestId("mermaid-block")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Blueprint" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/teaching-diagrams/td_demo/blueprint.png"), expect.anything(),
  ));
  fireEvent.click(screen.getByRole("button", { name: "AI 教学图" }));
  await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(3));
  expect(screen.getByText(/可能存在简化/)).toBeInTheDocument();
});

test("shows one selectable Mermaid diagram when teaching diagrams are absent", () => {
  render(<DiagramsPanel result={resultWithMermaidOnly()} />);

  expect(screen.getByRole("button", { name: /项目结构图/ })).toHaveClass("active");
  expect(screen.getByTestId("mermaid-block")).toHaveTextContent("graph TD");
  fireEvent.click(screen.getByRole("button", { name: /模型整体流程图/ }));
  expect(screen.getByTestId("mermaid-block")).toHaveTextContent("flowchart LR");
});

test("disables AI tab and defaults to Blueprint when review did not pass", async () => {
  render(<DiagramsPanel result={resultWithTeaching({ display_variant: "blueprint", final_asset: null, fallback_reason: "review_failed_fallback_blueprint" })} />);

  expect(screen.getByRole("button", { name: "AI 教学图" })).toBeDisabled();
  await waitFor(() => expect(screen.getByAltText(/Blueprint/)).toHaveAttribute("src", "blob:protected-diagram"));
  expect(screen.getByText(/review_failed_fallback_blueprint/)).toBeInTheDocument();
});

test("prefers SVG Blueprint when Chinese font fallback warning is present", async () => {
  render(<DiagramsPanel result={resultWithTeaching({ warnings: ["teaching_diagram_font_unavailable"] })} />);

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/teaching-diagrams/td_demo/blueprint.svg"), expect.anything(),
  ));
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

function resultWithMermaidOnly(): AnalysisResult {
  return {
    task_id: "task_mermaid",
    diagrams: {
      diagrams: [
        { id: "project_structure", diagram_type: "project_structure", title: "项目结构图", mermaid: "graph TD\nA-->B", description: "项目结构" },
        { id: "model_flow", diagram_type: "model_flow", title: "模型整体流程图", mermaid: "flowchart LR\nX-->Y", description: "模型流程" }
      ]
    }
  } as AnalysisResult;
}
