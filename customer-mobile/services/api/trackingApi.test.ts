import { deriveEtaDisplayState, type OrderTracking } from "./trackingApi";

// Live Rider Tracking Phase 23 — ETA Staleness.

function tracking(overrides: Partial<Pick<OrderTracking, "estimated_delivery_at" | "eta_source" | "rider_location">>) {
  return {
    estimated_delivery_at: "2026-01-01T12:00:00Z",
    eta_source: "live" as const,
    rider_location: { latitude: 1, longitude: 2, updated_at: "2026-01-01T11:59:00Z", state: "live" as const },
    ...overrides,
  };
}

describe("deriveEtaDisplayState", () => {
  it("is calculating when there's no estimate at all yet", () => {
    expect(deriveEtaDisplayState(tracking({ estimated_delivery_at: null }))).toBe("calculating");
  });

  it("is updated for a live-sourced ETA with a live rider position", () => {
    expect(deriveEtaDisplayState(tracking({}))).toBe("updated");
  });

  it("is updated for a static ETA with a live rider position", () => {
    expect(deriveEtaDisplayState(tracking({ eta_source: "static" }))).toBe("updated");
  });

  it("is updating when the rider's own position has gone merely stale — never presented as current, but not written off either", () => {
    expect(
      deriveEtaDisplayState(
        tracking({ rider_location: { latitude: 1, longitude: 2, updated_at: "x", state: "stale" } }),
      ),
    ).toBe("updating");
  });

  it("is unavailable when the rider's position is offline — never shown as current", () => {
    expect(
      deriveEtaDisplayState(
        tracking({ rider_location: { latitude: 1, longitude: 2, updated_at: "x", state: "offline" } }),
      ),
    ).toBe("unavailable");
  });

  it("is unavailable when the backend itself couldn't produce an estimate, even with a live rider position", () => {
    expect(deriveEtaDisplayState(tracking({ eta_source: "unavailable" }))).toBe("unavailable");
  });

  it("treats an offline rider position as unavailable even when eta_source still says live (a stale cached value)", () => {
    expect(
      deriveEtaDisplayState(
        tracking({ eta_source: "live", rider_location: { latitude: 1, longitude: 2, updated_at: "x", state: "offline" } }),
      ),
    ).toBe("unavailable");
  });
});
