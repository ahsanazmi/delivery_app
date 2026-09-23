import { afterEach, describe, expect, it, vi } from "vitest";

import { getAdminPayments, settleAdminCOD, updateAdminRiderApproval } from "./adminApi";

describe("Admin actions — request shape sent to the backend", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("sends `reason` (not `rejection_reason`) for a non-reject rider approval action, with the bearer token attached", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }));
    global.fetch = fetchMock;

    await updateAdminRiderApproval("test-admin-token", "rider-1", "approve", "Looks good");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/v1/admin/riders/rider-1/approve");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("Bearer test-admin-token");
    expect(JSON.parse(init.body)).toEqual({ reason: "Looks good" });
  });

  it("sends `rejection_reason` (the one endpoint with a different key) for a reject action — matches the backend's own contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }));
    global.fetch = fetchMock;

    await updateAdminRiderApproval("test-admin-token", "rider-1", "reject", "Documents unclear");

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ rejection_reason: "Documents unclear" });
  });

  it("sends the exact amount and note for a COD settlement, never a client-computed 'outstanding' figure", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }));
    global.fetch = fetchMock;

    await settleAdminCOD("test-admin-token", "rider-1", "450.00", "Cash handed over in person");

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/v1/admin/cod/rider-1/settle");
    expect(JSON.parse(init.body)).toEqual({ amount: "450.00", note: "Cash handed over in person" });
  });

  it("Admin Payment Management (Phase 27) — sends the dedicated order_number and customer filters, not just the generic search box", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, page: 1, limit: 20 }), { status: 200 }),
    );
    global.fetch = fetchMock;

    await getAdminPayments("test-admin-token", { order_number: "ORD-1", customer: "Alice", page: 1, limit: 20 });

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(String(url), "http://localhost");
    expect(parsed.searchParams.get("order_number")).toBe("ORD-1");
    expect(parsed.searchParams.get("customer")).toBe("Alice");
  });
});
