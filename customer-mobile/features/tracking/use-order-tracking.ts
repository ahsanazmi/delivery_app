import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, type AppStateStatus } from "react-native";

import { ApiError } from "@/services/api/apiClient";
import {
    getOrderTracking,
    getOrderTrackingSocketUrl,
    TERMINAL_ORDER_STATUSES,
    type OrderTracking,
} from "@/services/api/trackingApi";

const POLL_INTERVAL_MS = 15000;
const BASE_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 15000;

export type TrackingConnectionState = "connecting" | "connected" | "disconnected";

/**
 * Live order tracking backed by the WebSocket feed, with automatic
 * reconnection (exponential backoff) and a REST-polling fallback that only
 * runs while the socket is down — so a flaky connection degrades to the old
 * 15s poll instead of leaving the screen stuck with no updates at all.
 */
export function useOrderTracking(accessToken: string | null, orderId: string | undefined) {
  const [tracking, setTracking] = useState<OrderTracking | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connectionState, setConnectionState] = useState<TrackingConnectionState>("connecting");

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const attemptRef = useRef(0);
  const stoppedRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const pollOnce = useCallback(async () => {
    if (!accessToken || !orderId) return;
    try {
      const data = await getOrderTracking(accessToken, orderId);
      setTracking(data);
      setError(null);
      // Live Rider Tracking Phase 33 — Fallback Polling must stop once it's
      // no longer necessary. A terminal status can arrive via a poll
      // response too (not just the WS onmessage handler below) if the
      // socket is still down when the order finishes — without this, a
      // customer whose WebSocket never recovers would keep polling a
      // completed order forever.
      if (TERMINAL_ORDER_STATUSES.includes(data.order_status)) {
        stoppedRef.current = true;
        stopPolling();
        if (reconnectTimerRef.current) {
          clearTimeout(reconnectTimerRef.current);
          reconnectTimerRef.current = null;
        }
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Unable to load tracking.");
    }
  }, [accessToken, orderId, stopPolling]);

  const startPolling = useCallback(() => {
    if (pollTimerRef.current) return;
    void pollOnce();
    pollTimerRef.current = setInterval(pollOnce, POLL_INTERVAL_MS);
  }, [pollOnce]);

  const connect = useCallback(() => {
    if (!accessToken || !orderId || stoppedRef.current) return;

    setConnectionState((current) => (current === "connected" ? current : "connecting"));

    const socket = new WebSocket(getOrderTrackingSocketUrl(accessToken, orderId));
    socketRef.current = socket;

    socket.onopen = () => {
      attemptRef.current = 0;
      setConnectionState("connected");
      setError(null);
      stopPolling(); // the socket is authoritative while it's up
    };

    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as OrderTracking;
        setTracking(data);
        setError(null);
        if (TERMINAL_ORDER_STATUSES.includes(data.order_status)) {
          stoppedRef.current = true; // nothing more will ever change; stop reconnecting
          socket.close();
        }
      } catch {
        // A malformed frame is dropped; the next message (or a poll) recovers state.
      }
    };

    socket.onerror = () => {
      socket.close();
    };

    socket.onclose = () => {
      if (socketRef.current === socket) socketRef.current = null;
      if (stoppedRef.current) return;

      setConnectionState("disconnected");
      startPolling(); // safety net for as long as the socket stays down

      const attempt = attemptRef.current + 1;
      attemptRef.current = attempt;
      const delay = Math.min(BASE_BACKOFF_MS * 2 ** (attempt - 1), MAX_BACKOFF_MS);
      reconnectTimerRef.current = setTimeout(connect, delay);
    };
  }, [accessToken, orderId, startPolling, stopPolling]);

  useEffect(() => {
    stoppedRef.current = false;
    attemptRef.current = 0;
    connect();

    return () => {
      stoppedRef.current = true;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      stopPolling();
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [connect, stopPolling]);

  // Live Rider Tracking Phase 20 — Reconnection Handling: "app
  // backgrounded / app resumed." A socket can go silently stale while the
  // OS suspends the app's networking in the background — no onclose ever
  // fires for that, so `connect` alone wouldn't know to do anything.
  // Forcing a fresh connection specifically on the foreground transition
  // (not on every AppState change) guarantees the customer never looks at
  // a screen that's actually been disconnected for a while without
  // knowing it, and also gets an immediate fresh snapshot rather than
  // waiting for the next event that may or may not still be coming.
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (nextState: AppStateStatus) => {
      if (nextState !== "active" || stoppedRef.current) return;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      attemptRef.current = 0;
      // Detach the old socket's handlers before closing it — otherwise its
      // own onclose would still fire (close() is async) and schedule a
      // second, competing reconnect right on top of the one below.
      const staleSocket = socketRef.current;
      if (staleSocket) {
        staleSocket.onopen = null;
        staleSocket.onmessage = null;
        staleSocket.onerror = null;
        staleSocket.onclose = null;
        staleSocket.close();
      }
      socketRef.current = null;
      connect();
    });
    return () => subscription.remove();
  }, [connect]);

  return { tracking, error, connectionState, refresh: pollOnce };
}
