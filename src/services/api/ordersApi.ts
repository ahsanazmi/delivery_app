import { apiFetch } from "./apiClient";

export type OrderStatus =
  | "pending"
  | "confirmed"
  | "preparing"
  | "out_for_delivery"
  | "delivered"
  | "cancelled";

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
  restaurant_id: string | null;
  restaurant_name: string | null;
  restaurant_phone: string | null;
  order_number: string;
  status: OrderStatus;
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
  items: OrderItem[];
  status_history: OrderStatusHistory[];
};

export type OrderPayload = {
  restaurant_name?: string | null;
  restaurant_phone?: string | null;
  address_line: string;
  city: string;
  state?: string | null;
  postal_code: string;
  landmark?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  delivery_instructions?: string | null;
  payment_method?: string;
};

export function listOrders(accessToken: string) {
  return apiFetch<Order[]>("/api/v1/orders", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function createOrder(accessToken: string, payload: OrderPayload) {
  return apiFetch<Order>("/api/v1/orders", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export function getOrder(accessToken: string, orderId: string) {
  return apiFetch<Order>(`/api/v1/orders/${orderId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function cancelOrder(
  accessToken: string,
  orderId: string,
  reason?: string,
) {
  const query = reason ? `?reason=${encodeURIComponent(reason)}` : "";
  return apiFetch<Order>(`/api/v1/orders/${orderId}/cancel${query}`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
