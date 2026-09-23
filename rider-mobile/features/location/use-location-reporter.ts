import * as Location from "expo-location";
import { useEffect, useRef } from "react";

import { updateRiderLocation } from "@/services/api/riderApi";
import { useLocationTrackingStore } from "@/store/locationTrackingStore";

// Matches the backend's MIN_LOCATION_PING_INTERVAL_SECONDS (10s) with a
// small margin, so a foreground report is essentially never thrown away by
// the server-side throttle purely due to timer jitter — every call this
// hook makes is one the backend will actually persist to history, not
// wasted battery/network for a ping that gets silently dropped.
const REPORT_INTERVAL_MS = 12000;

/**
 * Reports the rider's live GPS position to the backend at a fixed interval
 * for as long as `active` is true. `active` is computed by the caller as
 * "is this rider ONLINE, or do they have an active delivery" (Phase 22's
 * rule) — this hook itself has no opinion on why it's active, just whether
 * it is. Stops immediately, and cancels any pending timer, the moment
 * `active` flips to false or the component unmounts.
 *
 * Publishes its status into a shared store (locationTrackingStore) instead
 * of returning it directly — this hook is meant to be mounted exactly once,
 * high up the tree (see (rider)/_layout.tsx), so any screen that wants to
 * show "📍 Sharing your location" can read the shared state without running
 * a second, duplicate reporting interval of its own.
 */
export function useLocationReporter(accessToken: string | null, active: boolean) {
  const setState = useLocationTrackingStore((store) => store.setState);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!active || !accessToken) {
      setState("idle");
      return;
    }

    let cancelled = false;

    async function reportOnce() {
      try {
        const position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        if (cancelled || !accessToken) return;
        await updateRiderLocation(accessToken, position.coords.latitude, position.coords.longitude, {
          accuracy: position.coords.accuracy,
          heading: position.coords.heading,
          speed: position.coords.speed,
        });
        if (!cancelled) setState("sharing");
      } catch {
        if (!cancelled) setState("error");
      }
    }

    async function start() {
      setState("requesting-permission");
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (cancelled) return;
      if (status !== "granted") {
        setState("denied");
        return;
      }
      await reportOnce();
      timerRef.current = setInterval(reportOnce, REPORT_INTERVAL_MS);
    }

    void start();

    return () => {
      cancelled = true;
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [accessToken, active, setState]);
}
