import { render, screen } from "@testing-library/react";
import { PaperFigureGallery } from "../components/PaperFigureGallery";

test("renders canonical preview and keeps contribution links explicitly suggestive", () => {
  render(<PaperFigureGallery taskId="task_demo" figures={[{
    figure_id: "fig_1234567890abcdef1234",
    page_number: 2,
    page_width: 600,
    page_height: 800,
    page_rotation: 0,
    bbox: [10, 20, 500, 400],
    normalized_bbox: [0.01, 0.02, 0.8, 0.5],
    caption: { label: "Figure 1", text: "Architecture overview", confidence: "high" },
    canonical_preview: { path: "preview.png", width: 900, height: 600, byte_size: 100, sha256: "a".repeat(64) },
    original_assets: [],
    vlm_analysis: {
      figure_id: "fig_1234567890abcdef1234",
      figure_type: "architecture",
      summary: "输入经过编码器后输出。",
      contribution_candidates: [{ contribution_id: "C1", reason: "架构一致", confidence: "medium" }]
    }
  }]} />);

  const image = screen.getByRole("img", { name: /Figure 1/ });
  expect(image).toHaveAttribute("src", "/analysis/tasks/task_demo/figures/fig_1234567890abcdef1234/preview");
  expect(screen.getByText(/AI Figure 类型：architecture/)).toBeInTheDocument();
  expect(screen.getByText(/C1（medium，AI 建议）/)).toBeInTheDocument();
});
