import { apiFetch, WS_BASE } from "./apiClient";
import type { OrderStatus, OrderStatusHistory } from "./ordersApi";

export type Rider = {
  id: string;
  name: string;
  phone: string | null;
};

// Live Rider Tracking Phase 12 — kept in parity with app/schemas/tracking.py
// (the actual shared contract this platform's Python/TypeScript split can
// support — no codegen exists, so this is a hand-maintained mirror, not an
// auto-generated one; a field added to one side without the other is a
// silent bug, so keep both in sync deliberately).
export type RiderLocationState = "live" | "stale" | "offline";

export type RiderLocation = {
  latitude: number;
  longitude: number;
  updated_at: string;
  state: RiderLocationState;
};

// Live Rider Tracking Phase 22/23.
export type EtaSource = "live" | "static" | "unavailable";

export type OrderTracking = {
  order_id: string;
  order_number: string;
  order_status: OrderStatus;
  assignment_status: "unassigned" | "assigned";
  rider: Rider | null;
  rider_location: RiderLocation | null;
  restaurant_name: string | null;
  restaurant_latitude: number | null;
  restaurant_longitude: number | null;
  delivery_address_line: string | null;
  delivery_latitude: number | null;
  delivery_longitude: number | null;
  estimated_delivery_at: string | null;
  eta_source: EtaSource;
  status_history: OrderStatusHistory[];
};

// Live Rider Tracking Phase 23 — ETA Staleness. Derived client-side from
// two signals the backend already provides (eta_source, and the rider's
// own location freshness) rather than the backend guessing what the
// client is currently showing. "Unavailable" takes priority over
// everything else — an ETA computed from a position we no longer trust
// at all must never be shown as current (this phase's own "do not
// present stale ETA as current").
export type EtaDisplayState = "calculating" | "updated" | "updating" | "unavailable";

export function deriveEtaDisplayState(tracking: Pick<OrderTracking, "estimated_delivery_at" | "eta_source" | "rider_location">): EtaDisplayState {
  if (!tracking.estimated_delivery_at) return "calculating";
  if (tracking.eta_source === "unavailable") return "unavailable";
  if (tracking.rider_location?.state === "offline") return "unavailable";
  if (tracking.rider_location?.state === "stale") return "updating";
  return "updated";
}

export function getOrderTracking(accessToken: string, orderId: string) {
  return apiFetch<OrderTracking>(`/api/v1/customer/orders/${orderId}/tracking`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getOrderTrackingSocketUrl(accessToken: string, orderId: string): string {
  return `${WS_BASE}/api/v1/customer/ws/orders/${orderId}?token=${encodeURIComponent(accessToken)}`;
}

export const TERMINAL_ORDER_STATUSES: OrderStatus[] = ["delivered", "cancelled", "rejected"];
