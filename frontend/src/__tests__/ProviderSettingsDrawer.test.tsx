import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProviderSettingsDrawer } from "../components/ProviderSettingsDrawer";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

test("hides async image option and never writes browser storage", async () => {
  const localSet = vi.spyOn(Storage.prototype, "setItem");
  const localRemove = vi.spyOn(Storage.prototype, "removeItem");
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/settings/providers") && init?.method === "PUT") {
      return jsonResponse(provider("qwen_image", "Qwen-Image", "image_generation", 2));
    }
    return jsonResponse({
      revision: 1,
      providers: [
        provider("qwen_image", "Qwen-Image", "image_generation", 1),
        provider("deepseek", "DeepSeek", "text_llm", 1)
      ]
    });
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<ProviderSettingsDrawer open onClose={vi.fn()} />);

  fireEvent.click(await screen.findByText("图片生成"));
  fireEvent.click(screen.getByRole("button", { name: /Qwen-Image/ }));
  expect(screen.getByText("qwen_image")).toBeInTheDocument();
  expect(screen.queryByText(/Async/i)).not.toBeInTheDocument();

  fireEvent.click(screen.getByText("保存"));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/settings/providers/qwen_image"), expect.objectContaining({ method: "PUT" })));

  expect(localSet).not.toHaveBeenCalled();
  expect(localRemove).not.toHaveBeenCalled();
});

function provider(id: string, display_name: string, group: string, revision: number) {
  return {
    id,
    display_name,
    group,
    enabled: true,
    configured: id === "qwen_image",
    masked_key: "****1234",
    api_key_source: id === "qwen_image" ? "UI" : "None",
    revision,
    source: {
      base_url: "Default",
      model: "UI",
      timeout_seconds: "Default",
      retry: "Default",
      request_width: "Default",
      request_height: "Default"
    },
    fields: {
      enabled: true,
      base_url: id === "qwen_image" ? "https://dashscope.aliyuncs.com" : "https://api.deepseek.com",
      model: id === "qwen_image" ? "qwen-image" : "deepseek-chat",
      timeout_seconds: id === "qwen_image" ? 60 : 45,
      retry: 0,
      request_width: 1280,
      request_height: 720,
      endpoint_path: "/api/v1/services/aigc/multimodal-generation/generation",
      allowed_domains: ["dashscope.aliyuncs.com"],
      supports_async: false
    },
    warnings: []
  };
}

function jsonResponse(body: unknown) {
  return {
    ok: true,
    headers: { get: () => "application/json" },
    json: async () => body
  };
}
