import { apiFetch } from "./apiClient";

// Notifications & Communication System — hand-maintained mirror of the
// backend's NotificationType enum (app/models/notification.py), the same
// deliberate-sync discipline this codebase already applies to every other
// Python/TypeScript boundary with no code-generation bridge between them.
// A type added on one side without the other is a silent bug, not a
// harmless omission.
export type NotificationType =
  | "order_placed"
  | "order_confirmed"
  | "order_preparing"
  | "order_ready"
  | "rider_assigned"
  | "order_picked_up"
  | "rider_approaching"
  | "order_out_for_delivery"
  | "order_delivered"
  | "order_cancelled"
  | "order_rejected"
  | "payment_update"
  | "promotion"
  | "system"
  | "payment_success"
  | "refund_initiated"
  | "refund_completed"
  | "cod_pending"
  | "cod_collected";

export type Notification = {
  id: string;
  type: NotificationType;
  title: string;
  body: string;
  order_id: string | null;
  // The same deep-link context a live push already carries — present
  // even when re-fetching history, not just on the live push itself.
  data: Record<string, string> | null;
  is_read: boolean;
  created_at: string;
  read_at: string | null;
};

export function getNotifications(accessToken: string) {
  return apiFetch<Notification[]>("/api/v1/customer/notifications", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getUnreadNotificationCount(accessToken: string) {
  return apiFetch<{ unread_count: number }>("/api/v1/customer/notifications/unread-count", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function markNotificationRead(accessToken: string, notificationId: string) {
  return apiFetch<Notification>(`/api/v1/customer/notifications/${notificationId}/read`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function markAllNotificationsRead(accessToken: string) {
  return apiFetch<{ updated: number }>("/api/v1/customer/notifications/read-all", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export type PushTokenPayload = {
  token: string;
  platform?: "expo" | "ios" | "android";
  device_identifier?: string;
};

export type PushTokenRecord = {
  id: string;
  user_id: string;
  token: string;
  platform: string;
  device_identifier: string | null;
  is_active: boolean;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
};

export function registerPushToken(
  accessToken: string,
  payload: PushTokenPayload,
) {
  return apiFetch<PushTokenRecord>("/api/v1/notifications/register", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ ...payload, platform: payload.platform ?? "expo" }),
  });
}

export function unregisterPushToken(accessToken: string, token: string) {
  return apiFetch<void>(`/api/v1/notifications/register?token=${encodeURIComponent(token)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
