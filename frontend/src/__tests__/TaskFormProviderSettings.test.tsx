import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TaskForm } from "../components/TaskForm";
import { notifyProviderSettingsUpdated } from "../providerSettingsEvents";

afterEach(() => vi.unstubAllGlobals());

test("TaskForm updates provider readiness after settings change without refresh", async () => {
  let configured = false;
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/llm/public-config")) {
      return jsonResponse({
        default_analysis_mode: "rule",
        default_text_llm_enabled: false,
        default_teaching_narrative_llm_enabled: false,
        max_total_entities: 30,
        max_provider_requests: 60,
        max_concurrency: 2,
        providers: {},
        vision: { default_vision_vlm_enabled: false },
        image_generation: { default_image_generation_enabled: false }
      });
    }
    if (url.includes("/settings/providers")) {
      return jsonResponse({
        revision: configured ? 2 : 1,
        providers: [
          {
            id: "deepseek",
            display_name: "DeepSeek",
            group: "text_llm",
            enabled: true,
            configured,
            api_key_source: configured ? "UI" : "None",
            revision: configured ? 2 : 1,
            source: {},
            fields: { model: "deepseek-chat" }
          }
        ]
      });
    }
    return jsonResponse({ task_id: "task_test", status: "completed", summary: { task_id: "task_test" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  const openSettings = vi.fn();
  render(<TaskForm onTaskCreated={vi.fn()} onError={vi.fn()} onOpenSettings={openSettings} />);

  const textSwitch = await screen.findByLabelText(/文本 AI 解释/);
  await waitFor(() => expect(textSwitch).toBeDisabled());
  expect(screen.getByText(/文本 LLM Provider：未配置/)).toBeInTheDocument();
  fireEvent.click(screen.getAllByText("进入设置")[0]);
  expect(openSettings).toHaveBeenCalledTimes(1);

  configured = true;
  notifyProviderSettingsUpdated();

  await waitFor(() => expect(screen.getByLabelText(/文本 AI 解释/)).not.toBeDisabled());
  expect(screen.getByText(/文本 LLM Provider：DeepSeek \/ deepseek-chat/)).toBeInTheDocument();
});

function jsonResponse(body: unknown) {
  return {
    ok: true,
    headers: { get: () => "application/json" },
    json: async () => body
  };
}
