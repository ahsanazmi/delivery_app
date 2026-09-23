import { apiFetch } from "./apiClient";
import { AuthUser } from "./authApi";

export type ProfileUpdatePayload = {
  name?: string | null;
  email?: string | null;
  profile_image?: string | null;
};

export function getProfile(accessToken: string) {
  return apiFetch<AuthUser>("/api/v1/customer/profile", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function updateProfile(
  accessToken: string,
  payload: ProfileUpdatePayload,
) {
  return apiFetch<AuthUser>("/api/v1/customer/profile", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}
