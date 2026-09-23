import { apiFetch } from "@/services/api/apiClient";

export type OrderStatus =
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

export type StatusFilter = "pending" | "confirmed" | "preparing" | "ready" | "completed" | "cancelled";

export type OrderListItem = {
  id: string;
  order_number: string;
  customer_name_masked: string;
  item_count: number;
  total: number | string;
  payment_method: string;
  // Restaurant Payment Visibility (Phase 28) — Order.payment_status, not
  // Payment's own richer enum; see the backend schema's own note on why
  // this never joins in the Payment model at all.
  payment_status: string;
  status: OrderStatus;
  created_at: string;
  // Restaurant Payment Visibility (Phase 28) — frozen at order-creation
  // time (see backend's compute_restaurant_financials()); never
  // recomputed from a commission rate that may have changed since.
  restaurant_earning: number | string;
  commission: number | string;
  net_amount: number | string;
};

export type OrderItemDetail = {
  id: string;
  order_id: string;
  product_id: string;
  restaurant_id: string;
  product_name: string;
  unit_price: number | string;
  quantity: number;
  created_at: string;
};

export type OrderStatusHistoryEntry = {
  id: string;
  order_id: string;
  status: OrderStatus;
  note: string | null;
  created_at: string;
};

export type OrderDetail = {
  id: string;
  user_id: string;
  rider_id: string | null;
  customer_name: string;
  customer_email: string;
  customer_phone: string | null;
  restaurant_id: string | null;
  restaurant_name: string | null;
  restaurant_phone: string | null;
  restaurant_address: string | null;
  order_number: string;
  status: OrderStatus;
  payment_method: string;
  subtotal: number | string;
  delivery_fee: number | string;
  tax: number | string;
  discount: number | string;
  total: number | string;
  item_count: number;
  address_line: string;
  city: string;
  state: string | null;
  postal_code: string;
  landmark: string | null;
  latitude: number | string | null;
  longitude: number | string | null;
  delivery_instructions: string | null;
  cancelled_reason: string | null;
  payment_status: string;
  is_paid: boolean;
  created_at: string;
  updated_at: string;
  items: OrderItemDetail[];
  status_history: OrderStatusHistoryEntry[];
  // Restaurant Payment Visibility (Phase 28) — see OrderListItem's own
  // note; same fields, same stability guarantee.
  restaurant_earning: number | string;
  commission: number | string;
  net_amount: number | string;
};

export function listRestaurantOrders(accessToken: string, statusFilter?: StatusFilter, page = 1, limit = 20) {
  const query = new URLSearchParams();
  if (statusFilter) query.set("status", statusFilter);
  query.set("page", String(page));
  query.set("limit", String(limit));
  return apiFetch<OrderListItem[]>(`/api/v1/restaurant/orders?${query.toString()}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getRestaurantOrder(accessToken: string, orderId: string) {
  return apiFetch<OrderDetail>(`/api/v1/restaurant/orders/${orderId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function acceptOrder(accessToken: string, orderId: string) {
  return apiFetch<OrderDetail>(`/api/v1/restaurant/orders/${orderId}/accept`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function rejectOrder(accessToken: string, orderId: string, reason?: string) {
  return apiFetch<OrderDetail>(`/api/v1/restaurant/orders/${orderId}/reject`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ reason: reason || null }),
  });
}

export function markOrderPreparing(accessToken: string, orderId: string) {
  return apiFetch<OrderDetail>(`/api/v1/restaurant/orders/${orderId}/preparing`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function markOrderReady(accessToken: string, orderId: string) {
  return apiFetch<OrderDetail>(`/api/v1/restaurant/orders/${orderId}/ready`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
