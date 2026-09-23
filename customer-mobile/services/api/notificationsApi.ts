import { apiFetch } from "./apiClient";

export type NotificationType =
  | "order_placed"
  | "order_confirmed"
  | "order_preparing"
  | "order_ready"
  | "rider_assigned"
  | "order_picked_up"
  | "order_out_for_delivery"
  | "order_delivered"
  | "order_cancelled"
  | "order_rejected"
  | "payment_update"
  | "promotion"
  | "system";

export type Notification = {
  id: string;
  type: NotificationType;
  title: string;
  body: string;
  order_id: string | null;
  is_read: boolean;
  created_at: string;
};

export function getNotifications(accessToken: string) {
  return apiFetch<Notification[]>("/api/v1/customer/notifications", {
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
};

export type PushTokenRecord = {
  id: string;
  user_id: string;
  token: string;
  platform: string;
  created_at: string;
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
