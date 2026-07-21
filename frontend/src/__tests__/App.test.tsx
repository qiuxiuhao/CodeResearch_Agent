import { render, screen } from "@testing-library/react";
import App from "../App";

beforeEach(() => {
  document.cookie = "cra_csrf=test-csrf; path=/";
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) return response({access_token: "access"});
      if (url.endsWith("/workspaces")) return response({items: [{workspace_id: "w", name: "Workspace", status: "active", role: "owner"}]});
      if (url.endsWith("/workspaces/w/projects")) return response({items: [{project_id: "p", workspace_id: "w", name: "Project", status: "active", role: "project_owner"}]});
      if (url.endsWith("/workspaces/w/projects/p/jobs")) return response({items: []});
      if (url.includes("/settings/providers")) return response({providers: []});
      if (url.includes("/runtime/public-config")) return response({default_analysis_mode: "rule", providers: {}});
      return response({});
    })
  );
});

function response(body: unknown) {
  return {ok: true, status: 200, json: async () => body};
}

afterEach(() => {
  document.cookie = "cra_csrf=; Max-Age=0; path=/";
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

test("starts a loopback local session without personal login", async () => {
  document.cookie = "cra_csrf=; Max-Age=0; path=/";
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/auth/local-session")) {
      expect(init?.method).toBe("POST");
      return response({
        access_token: "access",
        token_type: "bearer",
        session_id: "session",
        workspace_id: "w",
        project_id: "p",
      });
    }
    if (url.endsWith("/workspaces")) return response({items: [{workspace_id: "w", name: "Local Workspace", status: "active", role: "owner"}]});
    if (url.endsWith("/workspaces/w/projects")) return response({items: [{project_id: "p", workspace_id: "w", name: "Default Project", status: "active", role: "project_owner"}]});
    if (url.endsWith("/workspaces/w/projects/p/jobs")) return response({items: []});
    return response({});
  });
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);

  expect(await screen.findByText("暂无历史任务")).toBeInTheDocument();
  expect(screen.queryByText("登录 Local Workspace")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v2/auth/local-session",
    expect.objectContaining({method: "POST"})
  );
});
