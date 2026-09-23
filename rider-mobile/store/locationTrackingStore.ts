import { create } from "zustand";

export type LocationSharingState = "idle" | "requesting-permission" | "sharing" | "denied" | "error";

type LocationTrackingState = {
  state: LocationSharingState;
  setState: (state: LocationSharingState) => void;
};

// A single shared place for the foreground reporter (mounted once, in
// (rider)/_layout.tsx, so a rider who is both online and on an active
// delivery only ever has one interval running) to publish its status, and
// for any screen (e.g. the delivery detail screen) to read it without
// running a second reporter of its own.
export const useLocationTrackingStore = create<LocationTrackingState>((set) => ({
  state: "idle",
  setState: (state) => set({ state }),
}));
