import {render, screen} from "@testing-library/react";
import {vi} from "vitest";
import {JobCenter} from "../features/platform/JobCenter";

test("shows deployment profile from v2 control-plane health", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/health")) {
      return response({status: "ok", profile: "local", api_contract_version: "2"});
    }
    if (url.endsWith("/auth/local-session")) {
      return response({
        access_token: "access",
        token_type: "bearer",
        session_id: "session",
        workspace_id: "w",
        project_id: "p",
      });
    }
    if (url.endsWith("/workspaces")) {
      return response({items: [{workspace_id: "w", name: "Local Workspace", status: "active", role: "owner"}]});
    }
    if (url.endsWith("/workspaces/w/projects")) {
      return response({items: [{project_id: "p", workspace_id: "w", name: "Default Project", status: "active", role: null}]});
    }
    if (url.endsWith("/workspaces/w/projects/p/jobs")) return response({items: []});
    return response({});
  }));
  render(<JobCenter onClose={() => undefined} />);
  expect(await screen.findByText("local")).toBeInTheDocument();
  expect(screen.getByText("v2")).toBeInTheDocument();
  vi.unstubAllGlobals();
});

function response(body: unknown) {
  return {ok: true, status: 200, json: async () => body};
}
