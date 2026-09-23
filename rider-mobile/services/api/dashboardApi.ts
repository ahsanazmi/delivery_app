import { apiFetch } from "./apiClient";
import type { RiderOrder } from "./riderApi";

export type RiderDashboard = {
  is_online: boolean;
  today_deliveries_count: number;
  completed_deliveries_count: number;
  pending_deliveries_count: number;
  today_earnings: number | string;
  current_assignment: RiderOrder | null;
};

export function getRiderDashboard(accessToken: string) {
  return apiFetch<RiderDashboard>("/api/v1/rider/dashboard", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
