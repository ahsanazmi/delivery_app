// Deep Linking (Phase 27) — handleDeepLink's own routing table, kept in
// parity with app/(rider)/notifications.tsx's own destinationFor() so a
// tap lands on the same screen whether it came from a live push or from
// browsing notification history later.

// notification-provider.tsx imports useRouter from expo-router purely
// for its own type (AppRouter); handleDeepLink itself never calls it —
// mocked here only so importing the module under test doesn't pull in
// expo-router's real dependency chain (this app's newer expo-router
// pulls in `standard-navigation`, which this project's jest
// transformIgnorePatterns doesn't cover — a pre-existing environment
// gap, not something handleDeepLink itself needs).
jest.mock("expo-router", () => ({ useRouter: () => undefined }));

import { handleDeepLink } from "../notification-provider";

function mockRouter() {
  return { push: jest.fn() } as unknown as Parameters<typeof handleDeepLink>[0];
}

describe("handleDeepLink", () => {
  it("routes new_delivery to the dashboard (self-accept surface)", () => {
    const router = mockRouter();
    handleDeepLink(router, { type: "new_delivery" });
    expect(router.push).toHaveBeenCalledWith("/");
  });

  it("routes delivery_cancelled to the delivery detail screen", () => {
    const router = mockRouter();
    handleDeepLink(router, { type: "delivery_cancelled", order_id: "order-1" });
    expect(router.push).toHaveBeenCalledWith({ pathname: "/delivery/[id]", params: { id: "order-1" } });
  });

  it("routes cod_collection_required to the delivery detail screen", () => {
    const router = mockRouter();
    handleDeepLink(router, { type: "cod_collection_required", order_id: "order-2" });
    expect(router.push).toHaveBeenCalledWith({ pathname: "/delivery/[id]", params: { id: "order-2" } });
  });

  it.each(["account_approved", "account_suspended", "document_approved", "document_rejected"])(
    "routes %s to the verification screen",
    (type) => {
      const router = mockRouter();
      handleDeepLink(router, { type });
      expect(router.push).toHaveBeenCalledWith("/verification");
    },
  );

  it("routes cod_settlement_due to the wallet", () => {
    const router = mockRouter();
    handleDeepLink(router, { type: "cod_settlement_due" });
    expect(router.push).toHaveBeenCalledWith("/wallet");
  });

  it("falls back to the dashboard for an unrecognized category instead of crashing", () => {
    const router = mockRouter();
    expect(() => handleDeepLink(router, { type: "some_future_category" })).not.toThrow();
    expect(router.push).toHaveBeenCalledWith("/");
  });

  it("silently no-ops when data is undefined", () => {
    const router = mockRouter();
    expect(() => handleDeepLink(router, undefined)).not.toThrow();
    expect(router.push).not.toHaveBeenCalled();
  });
});
