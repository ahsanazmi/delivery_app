import { apiFetch } from "./apiClient";

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
