// Deep Linking (Phase 27) — handleDeepLink's own routing table, tested
// directly (no component render needed, it's a pure function of
// router + the push payload's data). Covers every category this app
// actually receives, plus the two safety nets: a missing order_id and
// an unrecognized category must both be silent no-ops, never a crash.

import { handleDeepLink } from "../notification-provider";

function mockRouter() {
  return { push: jest.fn(), replace: jest.fn() } as unknown as Parameters<typeof handleDeepLink>[0];
}

describe("handleDeepLink", () => {
  it("routes order_status to the live tracking screen", () => {
    const router = mockRouter();
    handleDeepLink(router, { type: "order_status", order_id: "order-1" });
    expect(router.push).toHaveBeenCalledWith({ pathname: "/track/[id]", params: { id: "order-1" } });
  });

  it.each(["payment_failed", "payment_success", "refund"])(
    "routes %s to the order detail screen (where the payment card lives)",
    (type) => {
      const router = mockRouter();
      handleDeepLink(router, { type, order_id: "order-2" });
      expect(router.push).toHaveBeenCalledWith({ pathname: "/orders/[id]", params: { id: "order-2" } });
    },
  );

  it("routes promotion to home", () => {
    const router = mockRouter();
    handleDeepLink(router, { type: "promotion" });
    expect(router.push).toHaveBeenCalledWith("/home");
  });

  it("never navigates when order_id is missing for an order-scoped category", () => {
    const router = mockRouter();
    handleDeepLink(router, { type: "order_status" });
    expect(router.push).not.toHaveBeenCalled();
  });

  it("silently no-ops for an unrecognized category instead of crashing", () => {
    const router = mockRouter();
    expect(() => handleDeepLink(router, { type: "some_future_category", order_id: "order-3" })).not.toThrow();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("silently no-ops when data is undefined (e.g. a notification with no payload)", () => {
    const router = mockRouter();
    expect(() => handleDeepLink(router, undefined)).not.toThrow();
    expect(router.push).not.toHaveBeenCalled();
  });

  // Background/Terminated App Behavior (Phase 29) — a cold-start tap
  // uses replace(), never push(), so it always wins the race against
  // splash.tsx's own independently-scheduled redirect.
  it('uses replace() instead of push() when method is "replace" (cold start)', () => {
    const router = mockRouter();
    handleDeepLink(router, { type: "order_status", order_id: "order-4" }, "replace");
    expect(router.replace).toHaveBeenCalledWith({ pathname: "/track/[id]", params: { id: "order-4" } });
    expect(router.push).not.toHaveBeenCalled();
  });

  it("defaults to push() when method is omitted (tap while already running)", () => {
    const router = mockRouter();
    handleDeepLink(router, { type: "promotion" });
    expect(router.push).toHaveBeenCalledWith("/home");
    expect(router.replace).not.toHaveBeenCalled();
  });
});
