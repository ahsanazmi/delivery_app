import { apiFetch, ApiError } from "./apiClient";

describe("apiFetch (critical API integration)", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  it("resolves with the parsed JSON body on a successful response", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => "10" },
      json: async () => ({ id: "abc" }),
    } as unknown as Response);

    const result = await apiFetch<{ id: string }>("/api/v1/whatever");
    expect(result).toEqual({ id: "abc" });
  });

  it("surfaces the backend's own sanitized `detail` message as ApiError.message, never a raw response body", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      headers: { get: () => null },
      json: async () => ({ detail: "Order cannot be cancelled at this stage" }),
    } as unknown as Response);

    await expect(apiFetch("/api/v1/customer/orders/1/cancel")).rejects.toMatchObject({
      message: "Order cannot be cancelled at this stage",
      status: 409,
    });
  });

  it("turns a network-level failure into a generic, safe message rather than propagating the raw fetch error", async () => {
    globalThis.fetch = jest.fn().mockRejectedValue(new TypeError("Network request failed"));

    const error = (await apiFetch("/api/v1/whatever").catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe("Unable to reach the server. Check that the API is running and the API URL is correct.");
    expect(error.status).toBe(0);
  });
});
