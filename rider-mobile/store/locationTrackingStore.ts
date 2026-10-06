import { create } from "zustand";

// Live Rider Tracking Phase 10 — Rider Tracking State. A richer state set
// than this store originally had (idle/requesting-permission/sharing/
// denied/error) — each value below is a real, distinct point in
// use-location-reporter.ts's own lifecycle, not just relabeling:
//   idle                 never started (not ONLINE, no active delivery)
//   requesting-permission  awaiting the foreground permission prompt
//   permission-denied    permission refused — tracking cannot start
//   starting              permission granted, about to send the first report
//   tracking               at least one report has succeeded
//   reconnecting         a report attempt just failed; the next scheduled
//                          interval tick will retry automatically — this
//                          reporter has no separate backoff/retry loop of
//                          its own, so "reconnecting" describes what
//                          actually happens next, not a distinct mechanism
//   error                reserved for a failure that retrying on its own
//                          won't fix (not produced by this reporter today;
//                          kept for a future, more specific failure class)
//   stopped               was tracking, then active became false (delivery
//                          ended / went offline) — distinct from idle,
//                          which means tracking never started in the first
//                          place
//   paused               reserved — no current code path pauses tracking
//                          without also stopping it; kept so a future
//                          app-backgrounded/foreground-service transition
//                          (Live Rider Tracking Phase 11) has a state to
//                          use instead of overloading "stopped"
export type LocationSharingState =
  | "idle"
  | "requesting-permission"
  | "permission-denied"
  | "starting"
  | "tracking"
  | "reconnecting"
  | "error"
  | "stopped"
  | "paused";

// Live Rider Tracking Phase 25 — Rider Delivery Screen. Two more signals
// beyond the state machine above, both set by the reporter on each
// attempt: the last reported GPS accuracy (meters — lets the screen warn
// "Weak GPS signal" without a new state value, since poor accuracy can
// happen while still successfully "tracking") and a coarse network
// signal derived from how a report attempt actually failed (RN's fetch
// throws a TypeError with this exact message when there's no
// connectivity at all — no new dependency like NetInfo needed for that
// one specific, reliable signature).
export type NetworkStatus = "online" | "offline" | "unknown";

type LocationTrackingState = {
  state: LocationSharingState;
  lastAccuracy: number | null;
  networkStatus: NetworkStatus;
  setState: (state: LocationSharingState) => void;
  setLastAccuracy: (accuracy: number | null) => void;
  setNetworkStatus: (status: NetworkStatus) => void;
};

// A single shared place for the foreground reporter (mounted once, in
// (rider)/_layout.tsx, so a rider who is both online and on an active
// delivery only ever has one interval running) to publish its status, and
// for any screen (e.g. the delivery detail screen) to read it without
// running a second reporter of its own. This is deliberately the *only*
// place tracking status lives — no component keeps its own boolean.
export const useLocationTrackingStore = create<LocationTrackingState>((set) => ({
  state: "idle",
  lastAccuracy: null,
  networkStatus: "unknown",
  setState: (state) => set({ state }),
  setLastAccuracy: (lastAccuracy) => set({ lastAccuracy }),
  setNetworkStatus: (networkStatus) => set({ networkStatus }),
}));
