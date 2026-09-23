import { apiFetch, ApiError } from "./apiClient";

describe("apiFetch (critical API integration)", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    jest.restoreAllMocks();
    jest.useRealTimers();
  });

  it("surfaces the backend's own sanitized `detail` message as ApiError.message, never a raw response body", async () => {
    globalThis.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 409,
      headers: { get: () => null },
      json: async () => ({ detail: "Cannot move a delivery assignment from PENDING to PICKED_UP." }),
    } as unknown as Response);

    await expect(apiFetch("/api/v1/rider/deliveries/1/pickup", { method: "POST" })).rejects.toMatchObject({
      message: "Cannot move a delivery assignment from PENDING to PICKED_UP.",
      status: 409,
    });
  });

  it("auto-retries exactly once on a GET network failure and returns the retry's result — a blip a rider never has to notice", async () => {
    jest.useFakeTimers();
    const fetchMock = jest
      .fn()
      .mockRejectedValueOnce(new TypeError("Network request failed"))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: { get: () => null },
        json: async () => ({ id: "order-1" }),
      } as unknown as Response);
    globalThis.fetch = fetchMock;

    const promise = apiFetch<{ id: string }>("/api/v1/rider/deliveries/available");
    await jest.advanceTimersByTimeAsync(1000);
    const result = await promise;

    expect(result).toEqual({ id: "order-1" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does NOT auto-retry a mutating POST request — retrying an un-audited write is never silently attempted", async () => {
    const fetchMock = jest.fn().mockRejectedValue(new TypeError("Network request failed"));
    globalThis.fetch = fetchMock;

    const error = (await apiFetch("/api/v1/rider/deliveries/1/pickup", { method: "POST" }).catch((e: unknown) => e)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
