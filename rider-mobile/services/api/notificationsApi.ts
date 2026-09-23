import { apiFetch } from "./apiClient";

export type NotificationType =
  | "order_confirmed"
  | "order_preparing"
  | "order_ready"
  | "rider_assigned"
  | "order_out_for_delivery"
  | "order_delivered"
  | "order_cancelled"
  | "order_rejected"
  | "promotion"
  | "system"
  | "new_delivery"
  | "delivery_cancelled"
  | "delivery_updated"
  | "payment_update"
  | "earning_update"
  | "account_approved"
  | "account_suspended";

export type RiderNotification = {
  id: string;
  type: NotificationType;
  title: string;
  body: string;
  order_id: string | null;
  is_read: boolean;
  created_at: string;
};

export function getRiderNotifications(accessToken: string) {
  return apiFetch<RiderNotification[]>("/api/v1/rider/notifications", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function markRiderNotificationRead(accessToken: string, notificationId: string) {
  return apiFetch<RiderNotification>(`/api/v1/rider/notifications/${notificationId}/read`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function markAllRiderNotificationsRead(accessToken: string) {
  return apiFetch<{ updated: number }>("/api/v1/rider/notifications/read-all", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export type PushTokenPayload = {
  token: string;
  platform?: "expo" | "ios" | "android";
};

export type PushTokenRecord = {
  id: string;
  user_id: string;
  token: string;
  platform: string;
  created_at: string;
};

// Shared with every other portal's identical endpoint — a push token isn't
// rider-specific, it's just "this device belongs to this authenticated
// user," so /api/v1/notifications/register (not /rider/...) is correct here.
export function registerPushToken(accessToken: string, payload: PushTokenPayload) {
  return apiFetch<PushTokenRecord>("/api/v1/notifications/register", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ ...payload, platform: payload.platform ?? "expo" }),
  });
}

export function unregisterPushToken(accessToken: string, token: string) {
  return apiFetch<void>(`/api/v1/notifications/register?token=${encodeURIComponent(token)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
