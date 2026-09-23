import { apiFetch } from "./apiClient";
import type { CartResponse } from "./cartApi";

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

export type OrderItem = {
  id: string;
  order_id: string;
  product_id: string;
  restaurant_id: string;
  product_name: string;
  unit_price: number;
  quantity: number;
  created_at: string;
};

export type OrderStatusHistory = {
  id: string;
  order_id: string;
  status: OrderStatus;
  note: string | null;
  created_at: string;
};

export type Order = {
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
  subtotal: number;
  delivery_fee: number;
  tax: number;
  discount: number;
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
  payment_status: string;
  is_paid: boolean;
  created_at: string;
  updated_at: string;
  items: OrderItem[];
  status_history: OrderStatusHistory[];
};

export type OrderPayload = {
  address_id: string;
  payment_method?: "cod" | "razorpay";
  delivery_instructions?: string | null;
};

export type OrderListParams = {
  status?: OrderStatus;
  page?: number;
  limit?: number;
  dateFrom?: string;
  dateTo?: string;
};

export function listOrders(accessToken: string, params: OrderListParams = {}) {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.page) query.set("page", String(params.page));
  if (params.limit) query.set("limit", String(params.limit));
  if (params.dateFrom) query.set("date_from", params.dateFrom);
  if (params.dateTo) query.set("date_to", params.dateTo);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<Order[]>(`/api/v1/customer/orders${suffix}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function createOrder(accessToken: string, payload: OrderPayload) {
  return apiFetch<Order>("/api/v1/customer/orders", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export function getOrder(accessToken: string, orderId: string) {
  return apiFetch<Order>(`/api/v1/customer/orders/${orderId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function cancelOrder(
  accessToken: string,
  orderId: string,
  reason?: string,
) {
  const query = reason ? `?reason=${encodeURIComponent(reason)}` : "";
  return apiFetch<Order>(`/api/v1/customer/orders/${orderId}/cancel${query}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function reorderOrder(accessToken: string, orderId: string) {
  return apiFetch<CartResponse>(`/api/v1/customer/orders/${orderId}/reorder`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
