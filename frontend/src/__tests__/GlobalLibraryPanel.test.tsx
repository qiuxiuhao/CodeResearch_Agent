import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { GlobalLibraryPanel } from "../components/GlobalLibraryPanel";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/library/stats")) {
        return jsonResponse({
          function_count: 1,
          occurrence_count: 2,
          package_counts: [{ name: "torch", count: 1 }],
          category_counts: [{ name: "pytorch", count: 1 }],
          confidence_counts: [{ name: "high", count: 1 }]
        });
      }
      if (url.startsWith("/library/functions/high-frequency")) {
        return jsonResponse({ items: [{ canonical_name: "torch.randn", package_name: "torch", category: "pytorch", occurrence_count: 2 }] });
      }
      if (url.startsWith("/library/functions/low-confidence")) {
        return jsonResponse({ items: [] });
      }
      if (url.startsWith("/library/functions/torch.randn/occurrences")) {
        return jsonResponse({
          items: [
            {
              id: 1,
              canonical_name: "torch.randn",
              task_id: "task-a",
              project_name: "demo",
              file_path: "train.py",
              function_name: "build_batch",
              qualified_function_name: "build_batch",
              line_no: 12,
              call_text: "torch.randn(2, 3)",
              created_at: "2026-01-01T00:00:00Z"
            }
          ],
          total: 1,
          limit: 50,
          offset: 0
        });
      }
      if (url === "/library/functions/torch.randn") {
        return jsonResponse({
          function: {
            canonical_name: "torch.randn",
            package_name: "torch",
            category: "pytorch",
            confidence: "high",
            summary: "生成随机 Tensor。",
            beginner_explanation: "按形状造随机数。",
            parameters_explanation: ["size：输出形状"],
            common_mistakes: ["shape 不匹配"]
          },
          occurrence_count: 2,
          first_seen: "2026-01-01T00:00:00Z",
          last_seen: "2026-01-02T00:00:00Z"
        });
      }
      if (url.startsWith("/library/functions")) {
        return jsonResponse({
          items: [
            {
              canonical_name: "torch.randn",
              package_name: "torch",
              category: "pytorch",
              confidence: "high",
              summary: "生成随机 Tensor。",
              occurrence_count: 2
            }
          ],
          total: 1,
          limit: 50,
          offset: 0,
          filters: {
            packages: ["torch"],
            categories: ["pytorch"],
            confidences: ["high"]
          }
        });
      }
      return jsonResponse({});
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("loads global library list and opens function detail", async () => {
  render(<GlobalLibraryPanel />);

  expect((await screen.findAllByText("torch.randn")).length).toBeGreaterThan(0);
  expect(screen.getByText("函数数")).toBeInTheDocument();
  expect(screen.getByText("高频函数")).toBeInTheDocument();
  expect(screen.getByText("暂无低置信度函数。")).toBeInTheDocument();

  fireEvent.click(screen.getAllByText("torch.randn")[0]);

  expect(await screen.findByText("按形状造随机数。")).toBeInTheDocument();
  expect(screen.getByText("torch.randn(2, 3)")).toBeInTheDocument();
});

test("submits search filters", async () => {
  const fetchMock = vi.mocked(fetch);
  render(<GlobalLibraryPanel />);

  await screen.findAllByText("torch.randn");
  fireEvent.change(screen.getByLabelText("搜索全局函数库"), { target: { value: "randn" } });
  fireEvent.change(screen.getByLabelText("按包筛选"), { target: { value: "torch" } });
  fireEvent.click(screen.getByText("搜索"));

  await waitFor(() => {
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("query=randn"))).toBe(true);
  });
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("package_name=torch"))).toBe(true);
});

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    json: async () => body
  } as Response;
}
