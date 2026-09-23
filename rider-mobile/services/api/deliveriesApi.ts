import { apiFetch } from "./apiClient";
import type { RiderOrder } from "./riderApi";

export type AvailableDelivery = {
  assignment_id: string;
  order_id: string;
  restaurant_name: string;
  restaurant_address: string;
  restaurant_latitude: number | string | null;
  restaurant_longitude: number | string | null;
  customer_area: string;
  estimated_distance_km: number | null;
  estimated_earning: number | string;
  ready_since: string;
};

export function listAvailableDeliveries(accessToken: string) {
  return apiFetch<AvailableDelivery[]>("/api/v1/rider/deliveries/available", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function acceptDelivery(accessToken: string, orderId: string) {
  return apiFetch<RiderOrder>(`/api/v1/rider/deliveries/${orderId}/accept`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export type AssignmentStatus =
  | "ACCEPTED"
  | "REJECTED"
  | "ARRIVED_AT_RESTAURANT"
  | "PICKED_UP"
  | "OUT_FOR_DELIVERY"
  | "DELIVERED"
  | "CANCELLED";

export type DeliveryAssignment = {
  id: string;
  order_id: string;
  rider_id: string;
  status: AssignmentStatus;
  accepted_at: string | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  arrived_at: string | null;
  picked_up_at: string | null;
  out_for_delivery_at: string | null;
  delivered_at: string | null;
  cancelled_at: string | null;
};

export function rejectDelivery(accessToken: string, orderId: string, reason?: string) {
  return apiFetch<DeliveryAssignment>(`/api/v1/rider/deliveries/${orderId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ reason: reason || null }),
  });
}

export type DeliveryItem = {
  id: string;
  order_id: string;
  product_id: string;
  restaurant_id: string;
  product_name: string;
  unit_price: number | string;
  quantity: number;
  created_at: string;
};

export type DeliveryDetail = {
  order_id: string;
  order_number: string;
  status: RiderOrder["status"];
  assignment_status: AssignmentStatus | null;
  restaurant_name: string;
  restaurant_phone: string | null;
  restaurant_address: string;
  restaurant_latitude: number | string | null;
  restaurant_longitude: number | string | null;
  customer_name: string;
  customer_phone: string | null;
  delivery_address_line: string;
  delivery_city: string;
  delivery_state: string | null;
  delivery_postal_code: string;
  delivery_landmark: string | null;
  delivery_latitude: number | string | null;
  delivery_longitude: number | string | null;
  delivery_instructions: string | null;
  items: DeliveryItem[];
  subtotal: number | string;
  delivery_fee: number | string;
  total: number | string;
  payment_method: string;
  is_paid: boolean;
  cod_amount: number | string | null;
  created_at: string;
};

export function getDeliveryDetail(accessToken: string, orderId: string) {
  return apiFetch<DeliveryDetail>(`/api/v1/rider/deliveries/${orderId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function markArrivedAtRestaurant(accessToken: string, orderId: string) {
  return apiFetch<DeliveryAssignment>(`/api/v1/rider/deliveries/${orderId}/arrived`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function pickupDelivery(accessToken: string, orderId: string) {
  return apiFetch<RiderOrder>(`/api/v1/rider/deliveries/${orderId}/pickup`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function startDelivery(accessToken: string, orderId: string) {
  return apiFetch<RiderOrder>(`/api/v1/rider/deliveries/${orderId}/start`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export type CodCollection = {
  order_id: string;
  payment_id: string;
  amount: number | string;
  // Rider Payment/COD Visibility (Phase 29) — matches the backend's full
  // PaymentStatus enum, not just the subset collect_cod_payment() happens
  // to return today (always "paid"), so this type doesn't silently go
  // stale if that ever changes.
  payment_status:
    | "pending"
    | "processing"
    | "paid"
    | "failed"
    | "cancelled"
    | "refund_pending"
    | "partially_refunded"
    | "refunded";
  collected_by_rider_id: string;
  collected_at: string;
};

// No request body — the amount is always the order's own total, resolved
// server-side. There is nothing here a rider could send to change it.
export function collectCodPayment(accessToken: string, orderId: string) {
  return apiFetch<CodCollection>(`/api/v1/rider/deliveries/${orderId}/cod-collect`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function completeDelivery(accessToken: string, orderId: string) {
  return apiFetch<RiderOrder>(`/api/v1/rider/deliveries/${orderId}/complete`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
