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
 * "is this rider ONLINE, or do they have an active delivery" — this hook
 * itself has no opinion on why it's active, just whether it is. Stops
 * immediately, and cancels any pending timer, the moment `active` flips to
 * false or the component unmounts.
 *
 * Publishes its status into a shared store (locationTrackingStore, Live
 * Rider Tracking Phase 10) instead of returning it directly — this hook is
 * meant to be mounted exactly once, high up the tree (see
 * (rider)/_layout.tsx), so any screen that wants to show tracking status
 * can read the shared state without running a second, duplicate reporting
 * interval of its own, and no component keeps its own tracking boolean.
 */
export function useLocationReporter(accessToken: string | null, active: boolean) {
  const setState = useLocationTrackingStore((store) => store.setState);
  const setLastAccuracy = useLocationTrackingStore((store) => store.setLastAccuracy);
  const setNetworkStatus = useLocationTrackingStore((store) => store.setNetworkStatus);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Distinguishes "never started" (idle) from "was tracking, then active
  // became false" (stopped) — both look identical from `active` alone.
  const hasStartedRef = useRef(false);

  useEffect(() => {
    if (!active || !accessToken) {
      setState(hasStartedRef.current ? "stopped" : "idle");
      return;
    }

    let cancelled = false;

    async function reportOnce() {
      try {
        const position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        if (cancelled || !accessToken) return;
        if (!cancelled) setLastAccuracy(position.coords.accuracy);
        await updateRiderLocation(accessToken, position.coords.latitude, position.coords.longitude, {
          accuracy: position.coords.accuracy,
          heading: position.coords.heading,
          speed: position.coords.speed,
        });
        if (!cancelled) {
          setState("tracking");
          // A successful call proves the network is genuinely reachable
          // right now, regardless of what it reported before.
          setNetworkStatus("online");
        }
      } catch (caught) {
        // The interval below will retry automatically at its next tick —
        // this reporter has no separate backoff loop, so "reconnecting" is
        // what actually happens next, not just a label for "something
        // went wrong."
        if (cancelled) return;
        setState("reconnecting");
        // React Native's fetch throws this exact TypeError when there is
        // no network path at all (airplane mode, both radios off) — a
        // reliable enough signal for "no internet connection" without
        // adding a network-info dependency just for this one distinction.
        // Any other failure (a real HTTP response, a GPS read failure)
        // says nothing about connectivity either way, so it's left alone
        // rather than guessed at.
        if (caught instanceof TypeError && /network/i.test(caught.message)) {
          setNetworkStatus("offline");
        }
      }
    }

    async function start() {
      setState("requesting-permission");
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (cancelled) return;
      if (status !== "granted") {
        setState("permission-denied");
        return;
      }
      setState("starting");
      hasStartedRef.current = true;
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
