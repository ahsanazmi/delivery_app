import { apiFetch } from "@/services/api/apiClient";

// Notifications & Communication System Phase 12 — Restaurant Owner
// Notifications. Hand-maintained mirror of the backend's NotificationType
// enum (app/models/notification.py) — only the values a restaurant owner
// can actually receive, the same "mirror what this client can receive,
// not the full catalog" convention customer-mobile/rider-mobile already
// follow for their own equivalents.
export type NotificationType =
  | "restaurant_new_order"
  | "restaurant_order_cancelled"
  | "rider_assigned"
  | "payment_update"
  // Notifications & Communication System Phase 19 — Restaurant Order
  // Notifications. Reused from the rider's own "reassigned away" type
  // (role is what distinguishes this row) for the restaurant's own
  // "your delivery partner changed" delivery-exception alert.
  | "delivery_updated"
  // Notifications & Communication System Phase 23 — Live Delivery
  // Notifications. Reused from the customer's own ORDER_DELIVERED type.
  | "order_delivered"
  | "system";

export type Notification = {
  id: string;
  type: NotificationType;
  title: string;
  body: string;
  order_id: string | null;
  data: Record<string, string> | null;
  is_read: boolean;
  created_at: string;
  read_at: string | null;
};

export function listRestaurantNotifications(accessToken: string) {
  return apiFetch<Notification[]>("/api/v1/restaurant/notifications", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getUnreadRestaurantNotificationCount(accessToken: string) {
  return apiFetch<{ unread_count: number }>("/api/v1/restaurant/notifications/unread-count", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function markRestaurantNotificationRead(accessToken: string, notificationId: string) {
  return apiFetch<Notification>(`/api/v1/restaurant/notifications/${notificationId}/read`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function markAllRestaurantNotificationsRead(accessToken: string) {
  return apiFetch<{ updated: number }>("/api/v1/restaurant/notifications/read-all", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
