import { create } from "zustand";

import { getRiderDashboard, type RiderDashboard } from "@/services/api/dashboardApi";
import { listAvailableDeliveries, type AvailableDelivery } from "@/services/api/deliveriesApi";
import { getRiderVerification, resubmitRiderVerification, type RiderVerification } from "@/services/api/riderApi";
import { getRiderStatus, setRiderOnlineStatus, type RiderStatus } from "@/services/api/statusApi";

type RiderState = {
  verification: RiderVerification | null;
  isLoadingVerification: boolean;
  fetchVerification: (accessToken: string) => Promise<RiderVerification | null>;
  resubmitVerification: (accessToken: string) => Promise<RiderVerification>;

  status: RiderStatus | null;
  isLoadingStatus: boolean;
  statusError: string | null;
  fetchStatus: (accessToken: string) => Promise<RiderStatus | null>;
  setOnline: (accessToken: string, isOnline: boolean) => Promise<void>;

  dashboard: RiderDashboard | null;
  isLoadingDashboard: boolean;
  dashboardError: string | null;
  fetchDashboard: (accessToken: string) => Promise<RiderDashboard | null>;

  availableDeliveries: AvailableDelivery[];
  isLoadingAvailableDeliveries: boolean;
  availableDeliveriesError: string | null;
  fetchAvailableDeliveries: (accessToken: string) => Promise<void>;
};

// Rider-domain state, separate from authStore's session concerns.
export const useRiderStore = create<RiderState>((set) => ({
  verification: null,
  isLoadingVerification: false,

  async fetchVerification(accessToken) {
    set({ isLoadingVerification: true });
    try {
      const verification = await getRiderVerification(accessToken);
      set({ verification, isLoadingVerification: false });
      return verification;
    } catch {
      set({ isLoadingVerification: false });
      return null;
    }
  },

  async resubmitVerification(accessToken) {
    const verification = await resubmitRiderVerification(accessToken);
    set({ verification });
    return verification;
  },

  status: null,
  isLoadingStatus: false,
  statusError: null,

  async fetchStatus(accessToken) {
    set({ isLoadingStatus: true, statusError: null });
    try {
      const status = await getRiderStatus(accessToken);
      set({ status, isLoadingStatus: false });
      return status;
    } catch (err) {
      set({
        isLoadingStatus: false,
        statusError: err instanceof Error ? err.message : "Unable to load your status.",
      });
      return null;
    }
  },

  // On failure (e.g. a not-yet-approved rider going online), the backend's
  // 403 detail is already the specific reason ("Your driving license must
  // be approved...") — surfaced via statusError rather than thrown, so the
  // screen doesn't need its own duplicate error handling.
  async setOnline(accessToken, isOnline) {
    set({ statusError: null });
    try {
      const status = await setRiderOnlineStatus(accessToken, isOnline);
      set({ status });
    } catch (err) {
      set({ statusError: err instanceof Error ? err.message : "Unable to update your status." });
    }
  },

  dashboard: null,
  isLoadingDashboard: false,
  dashboardError: null,

  async fetchDashboard(accessToken) {
    set({ isLoadingDashboard: true, dashboardError: null });
    try {
      const dashboard = await getRiderDashboard(accessToken);
      set({ dashboard, isLoadingDashboard: false });
      return dashboard;
    } catch (err) {
      set({
        isLoadingDashboard: false,
        dashboardError: err instanceof Error ? err.message : "Unable to load your dashboard.",
      });
      return null;
    }
  },

  availableDeliveries: [],
  isLoadingAvailableDeliveries: false,
  availableDeliveriesError: null,

  // A 403 here almost always just means "you're offline" (the backend's own
  // wording) — shown as availableDeliveriesError rather than crashing the
  // section, since it's an expected, common state, not a real failure.
  async fetchAvailableDeliveries(accessToken) {
    set({ isLoadingAvailableDeliveries: true, availableDeliveriesError: null });
    try {
      const availableDeliveries = await listAvailableDeliveries(accessToken);
      set({ availableDeliveries, isLoadingAvailableDeliveries: false });
    } catch (err) {
      set({
        availableDeliveries: [],
        isLoadingAvailableDeliveries: false,
        availableDeliveriesError: err instanceof Error ? err.message : "Unable to load available deliveries.",
      });
    }
  },
}));
