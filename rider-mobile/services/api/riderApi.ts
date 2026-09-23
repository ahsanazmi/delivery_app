import { apiFetch } from "./apiClient";
import type { AuthUser } from "./authApi";

export type RiderProfileUpdate = {
  name?: string;
  phone?: string;
  email?: string;
  profile_image?: string;
};

export function getRiderProfile(accessToken: string) {
  return apiFetch<AuthUser>("/api/v1/rider/profile", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function updateRiderProfile(accessToken: string, payload: RiderProfileUpdate) {
  return apiFetch<AuthUser>("/api/v1/rider/profile", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export type RiderApprovalStatus = "PENDING" | "APPROVED" | "REJECTED" | "SUSPENDED";

export type RiderVerification = {
  approval_status: RiderApprovalStatus;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
};

export function getRiderVerification(accessToken: string) {
  return apiFetch<RiderVerification>("/api/v1/rider/verification", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function resubmitRiderVerification(accessToken: string) {
  return apiFetch<RiderVerification>("/api/v1/rider/verification/resubmit", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export type RiderOrder = {
  id: string;
  user_id: string;
  rider_id: string | null;
  restaurant_id: string | null;
  restaurant_name: string | null;
  restaurant_phone: string | null;
  order_number: string;
  status:
    | "placed"
    | "confirmed"
    | "preparing"
    | "ready_for_pickup"
    | "rider_assigned"
    | "picked_up"
    | "out_for_delivery"
    | "delivered"
    | "cancelled"
    | "rejected";
  payment_method: string;
  subtotal: number;
  delivery_fee: number;
  total: number;
  item_count: number;
  address_line: string;
  city: string;
  state: string | null;
  postal_code: string;
  landmark: string | null;
  latitude: number | null;
  longitude: number | null;
  delivery_instructions: string | null;
  cancelled_reason: string | null;
  is_paid: boolean;
  created_at: string;
  updated_at: string;
  items: any[];
  status_history: any[];
};

export function listRiderOrders(accessToken: string) {
  return apiFetch<RiderOrder[]>("/api/v1/rider/orders", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export type RiderLocationAck = {
  // Nullable: the backend accepts (200s) but silently drops a report from a
  // rider who is neither ONLINE nor on an active delivery — see
  // rider_location.py's eligibility gate. Nothing was stored, so there's
  // nothing to echo back.
  latitude: number | null;
  longitude: number | null;
  accuracy: number | null;
  heading: number | null;
  speed: number | null;
  updated_at: string | null;
};

export type LocationReportOptions = {
  accuracy?: number | null;
  heading?: number | null;
  speed?: number | null;
};

export function updateRiderLocation(
  accessToken: string,
  latitude: number,
  longitude: number,
  options?: LocationReportOptions,
) {
  return apiFetch<RiderLocationAck>("/api/v1/rider/location", {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({
      latitude,
      longitude,
      accuracy: options?.accuracy ?? null,
      heading: options?.heading ?? null,
      speed: options?.speed ?? null,
    }),
  });
}

// Orders in these statuses are the ones a rider is actively delivering — the
// only window where reporting a live GPS position means anything (matches
// the backend's LOCATION_VISIBLE_STATUSES gate).
export const ACTIVE_DELIVERY_STATUSES: RiderOrder["status"][] = ["rider_assigned", "picked_up", "out_for_delivery"];
