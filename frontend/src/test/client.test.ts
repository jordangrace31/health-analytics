import { describe, it, expect, vi, beforeEach } from "vitest";
import { api, ApiError } from "../api/client";

beforeEach(() => { vi.restoreAllMocks(); });

it("login posts credentials and returns json", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ status: "ok", username: "jo" }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const res = await api.login("jo", "pw12345");
  expect(res.username).toBe("jo");
  const [, opts] = fetchMock.mock.calls[0];
  expect(opts.credentials).toBe("include");
});

it("throws ApiError on non-2xx", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ detail: "Invalid credentials" }), { status: 401 })));
  await expect(api.login("jo", "bad")).rejects.toBeInstanceOf(ApiError);
});
