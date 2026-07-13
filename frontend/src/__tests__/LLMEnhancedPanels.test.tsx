import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TaskForm } from "../components/TaskForm";

afterEach(() => vi.unstubAllGlobals());

test("hybrid mode shows separate entity and provider-request limits and requires consent", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/llm/public-config")) {
      return {
        ok: true,
        headers: { get: () => "application/json" },
        json: async () => ({
          default_analysis_mode: "rule",
          max_total_entities: 30,
          max_provider_requests: 60,
          max_concurrency: 2,
          external_model_notice: "数据可能发送到外部模型",
          providers: {},
          max_function_explanations: 20,
          max_file_explanations: 10,
          max_model_explanations: 5,
          max_paper_alignments: 5
        })
      };
    }
    return {
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => ({ task_id: "task_test" })
    };
  });
  vi.stubGlobal("fetch", fetchMock);
  const onError = vi.fn();
  render(<TaskForm onTaskCreated={vi.fn()} onError={onError} />);

  fireEvent.change(await screen.findByLabelText("模式"), { target: { value: "hybrid" } });
  expect(screen.getByText(/最多选择逻辑分析实体：30/)).toBeInTheDocument();
  expect(screen.getByText(/最多发送外部 Provider 请求：60/)).toBeInTheDocument();
  expect(screen.getByText(/逻辑实体数不是 API 请求数/)).toBeInTheDocument();

  fireEvent.click(screen.getByText("开始分析"));
  await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringContaining("必须同意")));
  expect(fetchMock).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByLabelText(/我确认这些内容允许发送/));
  fireEvent.click(screen.getByText("开始分析"));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  const request = fetchMock.mock.calls[1][1];
  if (!request) throw new Error("expected task creation request options");
  expect(String(request.body)).toContain('"external_model_consent":true');
});
