import { restoreSession, setAccessToken, v2Request } from "../api/v2Client";

beforeEach(() => {
  document.cookie = "cra_csrf=test-csrf; path=/";
  setAccessToken(null);
});

afterEach(() => {
  document.cookie = "cra_csrf=; Max-Age=0; path=/";
  vi.unstubAllGlobals();
});

test("concurrent session restoration rotates through one refresh request", async () => {
  let release: (() => void) | undefined;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  const fetchMock = vi.fn(async () => {
    await pending;
    return response({access_token: "fresh-access"});
  });
  vi.stubGlobal("fetch", fetchMock);

  const first = restoreSession();
  const second = restoreSession();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  release?.();
  expect(await Promise.all([first, second])).toEqual([true, true]);
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("restored access token stays in memory and authenticates the retried request", async () => {
  const storageSpy = vi.spyOn(Storage.prototype, "setItem");
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith("/auth/refresh")) return response({access_token: "fresh-access"});
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer fresh-access");
    return response({ok: true});
  });
  vi.stubGlobal("fetch", fetchMock);
  expect(await restoreSession()).toBe(true);
  expect(await v2Request("/protected")).toEqual({ok: true});
  expect(storageSpy).not.toHaveBeenCalled();
  storageSpy.mockRestore();
});

function response(body: unknown) {
  return {ok: true, status: 200, json: async () => body};
}
