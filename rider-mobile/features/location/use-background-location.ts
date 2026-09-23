import { useEffect } from "react";

import { startBackgroundLocationTracking, stopBackgroundLocationTracking } from "./background-location-task";

/**
 * Starts/stops background location tracking in lockstep with the same
 * `active` signal the foreground reporter uses (see use-location-reporter.ts)
 * — background tracking is additive coverage for while the app isn't in the
 * foreground, not a separate policy. A no-op wherever the underlying
 * platform APIs aren't available (Expo Go, permission declined) — see
 * background-location-task.ts.
 */
export function useBackgroundLocationTracking(accessToken: string | null, active: boolean) {
  useEffect(() => {
    if (!active || !accessToken) {
      void stopBackgroundLocationTracking();
      return;
    }

    void startBackgroundLocationTracking(accessToken);

    return () => {
      void stopBackgroundLocationTracking();
    };
  }, [accessToken, active]);
}
