import { apiFetch } from "./apiClient";
import type { RiderApprovalStatus } from "./riderApi";

export type RiderStatus = {
  approval_status: RiderApprovalStatus;
  is_online: boolean;
  can_go_online: boolean;
  online_blocked_reason: string | null;
  updated_at: string;
};

export function getRiderStatus(accessToken: string) {
  return apiFetch<RiderStatus>("/api/v1/rider/status", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function setRiderOnlineStatus(accessToken: string, isOnline: boolean) {
  return apiFetch<RiderStatus>("/api/v1/rider/status", {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ is_online: isOnline }),
  });
}
