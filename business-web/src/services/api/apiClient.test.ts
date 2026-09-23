import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, ApiError } from "./apiClient";

describe("apiFetch (critical API integration)", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("resolves with the parsed JSON body on a successful response", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "abc" }), { status: 200, headers: { "content-type": "application/json" } }),
    );
    const result = await apiFetch<{ id: string }>("/api/v1/whatever");
    expect(result).toEqual({ id: "abc" });
  });

  it("surfaces the backend's own sanitized `detail` message as ApiError.message, never a raw response body", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Order cannot be cancelled at this stage" }), { status: 409 }),
    );
    await expect(apiFetch("/api/v1/restaurant/orders/1/accept")).rejects.toMatchObject({
      message: "Order cannot be cancelled at this stage",
      status: 409,
    });
  });

  it("falls back to a generic message when the error response has no `detail` (e.g. a raw 500 with no body)", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 500 }));
    await expect(apiFetch("/api/v1/whatever")).rejects.toMatchObject({
      message: "Something went wrong. Please try again.",
      status: 500,
    });
  });

  it("turns a network-level failure into a generic, safe message rather than propagating the raw fetch error", async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(apiFetch("/api/v1/whatever")).rejects.toBeInstanceOf(ApiError);
    await expect(apiFetch("/api/v1/whatever")).rejects.toMatchObject({
      message: "Unable to reach the server. Check that the API is running and the API URL is correct.",
      status: 0,
    });
  });
});
