import { apiFetch, WS_BASE } from "./apiClient";
import type { OrderStatus, OrderStatusHistory } from "./ordersApi";

export type Rider = {
  id: string;
  name: string;
  phone: string | null;
};

export type RiderLocation = {
  latitude: number;
  longitude: number;
  updated_at: string;
};

export type OrderTracking = {
  order_id: string;
  order_number: string;
  order_status: OrderStatus;
  assignment_status: "unassigned" | "assigned";
  rider: Rider | null;
  rider_location: RiderLocation | null;
  delivery_latitude: number | null;
  delivery_longitude: number | null;
  estimated_delivery_at: string | null;
  status_history: OrderStatusHistory[];
};

export function getOrderTracking(accessToken: string, orderId: string) {
  return apiFetch<OrderTracking>(`/api/v1/customer/orders/${orderId}/tracking`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getOrderTrackingSocketUrl(accessToken: string, orderId: string): string {
  return `${WS_BASE}/api/v1/customer/ws/orders/${orderId}?token=${encodeURIComponent(accessToken)}`;
}

export const TERMINAL_ORDER_STATUSES: OrderStatus[] = ["delivered", "cancelled", "rejected"];
