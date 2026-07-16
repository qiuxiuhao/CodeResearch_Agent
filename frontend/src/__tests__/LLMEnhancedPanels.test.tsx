import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TaskForm } from "../components/TaskForm";

afterEach(() => vi.unstubAllGlobals());

test("text and vision AI switches show independent budgets and require independent consent", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/llm/public-config")) {
      return {
        ok: true,
        headers: { get: () => "application/json" },
        json: async () => ({
          default_analysis_mode: "rule",
          default_text_llm_enabled: false,
          max_total_entities: 30,
          max_provider_requests: 60,
          max_concurrency: 2,
          external_model_notice: "数据可能发送到外部模型",
          providers: {},
          max_function_explanations: 20,
          max_file_explanations: 10,
          max_model_explanations: 5,
          max_paper_alignments: 5,
          vision: {
            default_vision_vlm_enabled: false,
            max_figure_analyses: 5,
            max_provider_requests: 10,
            max_concurrency: 2,
            providers: {},
            external_vision_notice: "论文 Figure 可能发送到外部模型"
          }
        })
      };
    }
    if (url.includes("/settings/providers")) {
      return {
        ok: true,
        headers: { get: () => "application/json" },
        json: async () => ({
          revision: 1,
          providers: [
            {
              id: "deepseek",
              display_name: "DeepSeek",
              group: "text_llm",
              enabled: true,
              configured: true,
              api_key_source: "UI",
              revision: 1,
              source: {},
              fields: { model: "deepseek-chat" }
            },
            {
              id: "qwen_vl",
              display_name: "Qwen-VL",
              group: "vision_vlm",
              enabled: true,
              configured: true,
              api_key_source: "UI",
              revision: 1,
              source: {},
              fields: { model: "qwen-vl-plus" }
            }
          ]
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

  fireEvent.click(await screen.findByLabelText(/文本 AI 解释/));
  expect(screen.getByText(/最多选择逻辑分析实体：30/)).toBeInTheDocument();
  expect(screen.getByText(/最多发送外部 Provider 请求：60/)).toBeInTheDocument();
  expect(screen.getByText(/逻辑实体数不是 API 请求数/)).toBeInTheDocument();

  fireEvent.click(screen.getByText("开始分析"));
  await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringContaining("必须同意")));
  expect(fetchMock).toHaveBeenCalledTimes(2);

  fireEvent.click(screen.getByLabelText(/我确认脱敏后的文本分析内容允许发送/));
  fireEvent.click(screen.getByText("开始分析"));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  const request = fetchMock.mock.calls[2][1];
  if (!request) throw new Error("expected task creation request options");
  expect(String(request.body)).not.toContain('"external_model_consent"');
  expect(String(request.body)).not.toContain('"analysis_mode"');
  expect(String(request.body)).toContain('"text_llm_enabled":true');

  fireEvent.change(screen.getByLabelText("论文 PDF 路径（可选）"), { target: { value: "paper.pdf" } });
  fireEvent.click(screen.getByLabelText(/论文 Figure AI 理解/));
  expect(screen.getByText(/最多分析 Figure：5/)).toBeInTheDocument();
  expect(screen.getByText(/最多发送视觉 Provider 请求：10/)).toBeInTheDocument();
  fireEvent.click(screen.getByText("开始分析"));
  await waitFor(() => expect(onError).toHaveBeenCalledWith(expect.stringContaining("单独同意")));
  fireEvent.click(screen.getByLabelText(/筛选后的论文 Figure/));
  fireEvent.click(screen.getByText("开始分析"));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  const visionRequest = fetchMock.mock.calls[3][1];
  if (!visionRequest) throw new Error("expected vision task creation request options");
  expect(String(visionRequest.body)).toContain('"vision_vlm_enabled":true');
  expect(String(visionRequest.body)).toContain('"external_vision_consent":true');
});
