import { useCallback, useEffect, useRef, useState } from "react";

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

  const pollOnce = useCallback(async () => {
    if (!accessToken || !orderId) return;
    try {
      const data = await getOrderTracking(accessToken, orderId);
      setTracking(data);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Unable to load tracking.");
    }
  }, [accessToken, orderId]);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

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

  return { tracking, error, connectionState, refresh: pollOnce };
}
