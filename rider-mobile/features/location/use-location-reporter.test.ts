import { renderHook, waitFor } from "@testing-library/react-native";

// Live Rider Tracking Phase 10 — Rider Tracking State. Proves the reporter
// actually drives the richer state set through its real lifecycle, not
// just that the type exists.

const mockGetCurrentPositionAsync = jest.fn();
const mockRequestForegroundPermissionsAsync = jest.fn();

jest.mock("expo-location", () => ({
  Accuracy: { Balanced: 3 },
  getCurrentPositionAsync: (...args: unknown[]) => mockGetCurrentPositionAsync(...args),
  requestForegroundPermissionsAsync: (...args: unknown[]) => mockRequestForegroundPermissionsAsync(...args),
}));

const mockUpdateRiderLocation = jest.fn();
jest.mock("@/services/api/riderApi", () => ({
  updateRiderLocation: (...args: unknown[]) => mockUpdateRiderLocation(...args),
}));

import { useLocationReporter } from "./use-location-reporter";
import { useLocationTrackingStore } from "@/store/locationTrackingStore";

function currentState() {
  return useLocationTrackingStore.getState().state;
}

describe("useLocationReporter — Rider Tracking State (Phase 10)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useLocationTrackingStore.setState({ state: "idle", lastAccuracy: null, networkStatus: "unknown" });
  });

  it("stays idle when never active", () => {
    renderHook(() => useLocationReporter("token", false));
    expect(currentState()).toBe("idle");
  });

  it("goes through requesting-permission, starting, and tracking on a successful report", async () => {
    mockRequestForegroundPermissionsAsync.mockResolvedValue({ status: "granted" });
    mockGetCurrentPositionAsync.mockResolvedValue({ coords: { latitude: 1, longitude: 2, accuracy: 5, heading: null, speed: null } });
    mockUpdateRiderLocation.mockResolvedValue({});

    renderHook(() => useLocationReporter("token", true));

    await waitFor(() => expect(currentState()).toBe("tracking"));
    expect(mockUpdateRiderLocation).toHaveBeenCalledWith("token", 1, 2, expect.objectContaining({ accuracy: 5 }));
  });

  it("goes to permission-denied when the permission prompt is refused", async () => {
    mockRequestForegroundPermissionsAsync.mockResolvedValue({ status: "denied" });

    renderHook(() => useLocationReporter("token", true));

    await waitFor(() => expect(currentState()).toBe("permission-denied"));
    expect(mockGetCurrentPositionAsync).not.toHaveBeenCalled();
  });

  it("goes to reconnecting when a report attempt fails — the next interval tick will retry", async () => {
    mockRequestForegroundPermissionsAsync.mockResolvedValue({ status: "granted" });
    mockGetCurrentPositionAsync.mockRejectedValue(new Error("GPS unavailable"));

    renderHook(() => useLocationReporter("token", true));

    await waitFor(() => expect(currentState()).toBe("reconnecting"));
  });

  it("goes to stopped (not idle) once it was tracking and then active becomes false", async () => {
    mockRequestForegroundPermissionsAsync.mockResolvedValue({ status: "granted" });
    mockGetCurrentPositionAsync.mockResolvedValue({ coords: { latitude: 1, longitude: 2, accuracy: 5, heading: null, speed: null } });
    mockUpdateRiderLocation.mockResolvedValue({});

    const { rerender } = renderHook(({ active }: { active: boolean }) => useLocationReporter("token", active), {
      initialProps: { active: true },
    });
    await waitFor(() => expect(currentState()).toBe("tracking"));

    rerender({ active: false });

    expect(currentState()).toBe("stopped");
  });

  it("stays idle (not stopped) when active becomes false without ever having started", () => {
    const { rerender } = renderHook(({ active }: { active: boolean }) => useLocationReporter("token", active), {
      initialProps: { active: false },
    });
    rerender({ active: false });
    expect(currentState()).toBe("idle");
  });

  it("records the reported accuracy and marks the network online on a successful report (Phase 25)", async () => {
    mockRequestForegroundPermissionsAsync.mockResolvedValue({ status: "granted" });
    mockGetCurrentPositionAsync.mockResolvedValue({ coords: { latitude: 1, longitude: 2, accuracy: 42, heading: null, speed: null } });
    mockUpdateRiderLocation.mockResolvedValue({});

    renderHook(() => useLocationReporter("token", true));

    await waitFor(() => expect(useLocationTrackingStore.getState().lastAccuracy).toBe(42));
    expect(useLocationTrackingStore.getState().networkStatus).toBe("online");
  });

  it("marks the network offline specifically on RN's no-connectivity fetch error, not on any other failure (Phase 25)", async () => {
    mockRequestForegroundPermissionsAsync.mockResolvedValue({ status: "granted" });
    mockGetCurrentPositionAsync.mockResolvedValue({ coords: { latitude: 1, longitude: 2, accuracy: 5, heading: null, speed: null } });
    mockUpdateRiderLocation.mockRejectedValue(new TypeError("Network request failed"));

    renderHook(() => useLocationReporter("token", true));

    await waitFor(() => expect(useLocationTrackingStore.getState().networkStatus).toBe("offline"));
  });

  it("does not guess at network status for an unrelated failure, e.g. a GPS read error (Phase 25)", async () => {
    mockRequestForegroundPermissionsAsync.mockResolvedValue({ status: "granted" });
    mockGetCurrentPositionAsync.mockRejectedValue(new Error("GPS unavailable"));
    useLocationTrackingStore.setState({ networkStatus: "unknown" });

    renderHook(() => useLocationReporter("token", true));

    await waitFor(() => expect(currentState()).toBe("reconnecting"));
    expect(useLocationTrackingStore.getState().networkStatus).toBe("unknown");
  });
});
