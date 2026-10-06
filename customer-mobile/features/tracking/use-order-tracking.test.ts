import { act, renderHook, waitFor } from "@testing-library/react-native";
import { AppState } from "react-native";

// Live Rider Tracking Phase 20 — Reconnection Handling. Focuses on the one
// genuinely new behavior this phase adds (force a fresh connection on the
// app-backgrounded -> app-resumed transition); the pre-existing
// exponential-backoff/polling-fallback logic already worked and isn't
// re-derived here.

const mockGetOrderTracking = jest.fn();
jest.mock("@/services/api/trackingApi", () => ({
  getOrderTracking: (...args: unknown[]) => mockGetOrderTracking(...args),
  getOrderTrackingSocketUrl: (token: string, orderId: string) => `wss://test/${orderId}?token=${token}`,
  TERMINAL_ORDER_STATUSES: ["delivered", "cancelled", "rejected"],
}));

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.closed = true;
  }
}

// @ts-expect-error — test-only global WebSocket stand-in.
global.WebSocket = FakeWebSocket;

import { useOrderTracking } from "./use-order-tracking";

describe("useOrderTracking — Reconnection Handling (Phase 20)", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    mockGetOrderTracking.mockReset();
  });

  it("opens exactly one socket on mount", () => {
    renderHook(() => useOrderTracking("token", "order-1"));
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("closes the stale socket and opens a fresh one when the app returns to active", async () => {
    let listener: ((state: string) => void) | undefined;
    jest.spyOn(AppState, "addEventListener").mockImplementation((_event: string, cb: any) => {
      listener = cb;
      return { remove: jest.fn() } as any;
    });

    renderHook(() => useOrderTracking("token", "order-1"));
    const firstSocket = FakeWebSocket.instances[0];
    expect(firstSocket).toBeDefined();

    listener?.("active");

    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    expect(firstSocket.closed).toBe(true);
    // The stale socket's own onclose must not fire the normal
    // disconnected/reconnect path — its handlers were detached first.
    expect(firstSocket.onclose).toBeNull();
  });

  it("does not open a new socket when the app goes to background", () => {
    let listener: ((state: string) => void) | undefined;
    jest.spyOn(AppState, "addEventListener").mockImplementation((_event: string, cb: any) => {
      listener = cb;
      return { remove: jest.fn() } as any;
    });

    renderHook(() => useOrderTracking("token", "order-1"));
    expect(FakeWebSocket.instances).toHaveLength(1);

    listener?.("background");

    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});

describe("useOrderTracking — Fallback Polling (Phase 33)", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    mockGetOrderTracking.mockReset();
  });

  it("stops polling once a poll response itself reveals a terminal order status", async () => {
    jest.useFakeTimers();
    try {
      mockGetOrderTracking.mockResolvedValue({ order_status: "delivered" });

      renderHook(() => useOrderTracking("token", "order-1"));
      const socket = FakeWebSocket.instances[0];

      // The socket going down (never having connected) starts the REST
      // polling fallback, same as any other disconnect.
      await act(async () => {
        socket.onclose?.();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(mockGetOrderTracking).toHaveBeenCalledTimes(1);

      // Advance well past when the next poll interval would have fired —
      // it must never fire again once the terminal status was already seen.
      await act(async () => {
        jest.advanceTimersByTime(20000);
        await Promise.resolve();
      });
      expect(mockGetOrderTracking).toHaveBeenCalledTimes(1);
    } finally {
      jest.useRealTimers();
    }
  });
});
