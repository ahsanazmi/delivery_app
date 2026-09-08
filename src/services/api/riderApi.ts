import { apiFetch } from "./apiClient";

export type RiderOrder = {
  id: string;
  user_id: string;
  rider_id: string | null;
  restaurant_id: string | null;
  restaurant_name: string | null;
  restaurant_phone: string | null;
  order_number: string;
  status:
    | "pending"
    | "confirmed"
    | "preparing"
    | "out_for_delivery"
    | "delivered"
    | "cancelled";
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

export function markOrderPickedUp(accessToken: string, orderId: string) {
  return apiFetch<RiderOrder>(`/api/v1/rider/orders/${orderId}/pickup`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function markOrderDelivered(accessToken: string, orderId: string) {
  return apiFetch<RiderOrder>(`/api/v1/rider/orders/${orderId}/deliver`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
