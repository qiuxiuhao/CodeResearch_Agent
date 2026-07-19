import {render, screen} from "@testing-library/react";
import {vi} from "vitest";
import {JobCenter} from "../features/platform/JobCenter";

test("shows deployment profile from v2 control-plane health", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({status: "ok", profile: "local", api_contract_version: "2"})
  }));
  render(<JobCenter onClose={() => undefined} />);
  expect(await screen.findByText("local")).toBeInTheDocument();
  expect(screen.getByText("v2")).toBeInTheDocument();
  vi.unstubAllGlobals();
});
