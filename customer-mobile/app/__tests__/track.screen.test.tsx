import { render, screen } from "@testing-library/react-native";

// Live Rider Tracking Phase 36 — Automated Testing. RiderMap and
// use-order-tracking are already covered by their own dedicated test
// files (RiderMap.test.tsx, use-order-tracking.test.ts) — this file tests
// the screen's own logic: which state (cancelled/delivered/live) renders
// which banner/badge/text, given a tracking payload the hook hands it.

jest.mock("expo-router", () => ({
  Redirect: ({ href }: { href: string }) => {
    const { Text } = require("react-native");
    return <Text testID="redirect">redirect:{href}</Text>;
  },
  useLocalSearchParams: () => ({ id: "order-1" }),
  useRouter: () => ({ back: jest.fn(), push: jest.fn(), replace: jest.fn() }),
}));

const mockUseSession = jest.fn();
jest.mock("@/features/auth/session-context", () => ({
  useSession: () => mockUseSession(),
}));

const mockUseOrderTracking = jest.fn();
jest.mock("@/features/tracking/use-order-tracking", () => ({
  useOrderTracking: (...args: unknown[]) => mockUseOrderTracking(...args),
}));

jest.mock("@/features/tracking/RiderMap", () => ({
  RiderMap: () => {
    const { Text } = require("react-native");
    return <Text testID="rider-map" />;
  },
}));

import TrackOrderScreen from "../track/[id]";

function baseTracking(overrides: Record<string, unknown> = {}) {
  return {
    order_id: "order-1",
    order_number: "SHC-0001",
    order_status: "out_for_delivery",
    assignment_status: "assigned",
    rider: { id: "rider-1", name: "Ravi", phone: "9999999999" },
    rider_location: null,
    restaurant_name: "Chai House",
    restaurant_latitude: 12.1,
    restaurant_longitude: 77.1,
    delivery_address_line: "15 Market Road, Bengaluru",
    delivery_latitude: 12.97,
    delivery_longitude: 77.59,
    estimated_delivery_at: new Date(Date.now() + 20 * 60 * 1000).toISOString(),
    eta_source: "static",
    status_history: [{ status: "placed", note: null, created_at: new Date().toISOString() }],
    ...overrides,
  };
}

function mockTracking(tracking: unknown) {
  mockUseOrderTracking.mockReturnValue({
    tracking,
    error: null,
    connectionState: "connected",
    refresh: jest.fn(),
  });
}

describe("TrackOrderScreen", () => {
  beforeEach(() => {
    mockUseSession.mockReturnValue({ user: { id: "u1" }, accessToken: "test-token" });
    mockUseOrderTracking.mockReset();
  });

  it("redirects to /login for an anonymous session", () => {
    mockUseSession.mockReturnValue({ user: null, accessToken: null });
    mockTracking(null);
    render(<TrackOrderScreen />);
    expect(screen.getByTestId("redirect")).toHaveTextContent("redirect:/login");
  });

  it("shows the restaurant and destination as text, not just map pins", () => {
    mockTracking(baseTracking());
    render(<TrackOrderScreen />);
    expect(screen.getByText("Chai House")).toBeTruthy();
    expect(screen.getByText("15 Market Road, Bengaluru")).toBeTruthy();
  });

  it("shows the cancelled banner and hides the live-tracking content for a cancelled order", () => {
    mockTracking(baseTracking({ order_status: "cancelled" }));
    render(<TrackOrderScreen />);
    expect(screen.getByText(/was cancelled/)).toBeTruthy();
    expect(screen.queryByTestId("rider-map")).toBeNull();
  });

  it("shows a delivered banner, not a stale ETA or a misleading 'waiting for rider' placeholder", () => {
    mockTracking(baseTracking({ order_status: "delivered", rider_location: null }));
    render(<TrackOrderScreen />);
    // "Delivered" also appears as the timeline's own step label — the
    // banner is the distinct, additional occurrence this phase's fix added.
    expect(screen.getAllByText("Delivered").length).toBeGreaterThan(1);
    expect(screen.getByText("This order has been delivered.")).toBeTruthy();
    expect(screen.queryByText(/Waiting for the rider's location/)).toBeNull();
    expect(screen.queryByText("Estimated delivery")).toBeNull();
  });

  it("shows a LIVE badge for a fresh rider position", () => {
    mockTracking(baseTracking({
      rider_location: { latitude: 12.97, longitude: 77.59, updated_at: new Date().toISOString(), state: "live" },
    }));
    render(<TrackOrderScreen />);
    expect(screen.getByText("Live")).toBeTruthy();
  });

  it("shows an OFFLINE badge and 'Location unavailable' once the rider's position goes stale past the offline threshold", () => {
    mockTracking(baseTracking({
      rider_location: {
        latitude: 12.97, longitude: 77.59,
        updated_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
        state: "offline",
      },
    }));
    render(<TrackOrderScreen />);
    expect(screen.getByText("Unavailable")).toBeTruthy();
    expect(screen.getByText("Location unavailable")).toBeTruthy();
  });

  it("shows a retry option when tracking fails to load at all", () => {
    mockUseOrderTracking.mockReturnValue({
      tracking: null,
      error: "Unable to load tracking.",
      connectionState: "disconnected",
      refresh: jest.fn(),
    });
    render(<TrackOrderScreen />);
    expect(screen.getByText("Unable to load tracking.")).toBeTruthy();
    expect(screen.getByText("Try again")).toBeTruthy();
  });
});
