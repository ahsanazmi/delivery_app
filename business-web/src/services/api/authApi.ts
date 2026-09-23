import { apiFetch } from "./apiClient";

export type UserRole = "CUSTOMER" | "RESTAURANT_OWNER" | "RIDER" | "ADMIN";

export type AuthUser = {
  id: string;
  name: string;
  email: string;
  phone: string | null;
  role: UserRole;
  is_active: boolean;
  created_at: string;
};

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
};

type RegisterPayload = {
  name: string;
  email: string;
  password: string;
  phone?: string;
};

export function register(payload: RegisterPayload) {
  return apiFetch<AuthUser>("/api/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, role: "CUSTOMER" }),
  });
}

export function login(identifier: string, password: string) {
  const trimmed = identifier.trim();
  const isEmail = trimmed.includes("@");

  return apiFetch<TokenPair>("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(
      isEmail ? { email: trimmed, password } : { phone: trimmed, password },
    ),
  });
}

export function refreshAccessToken(refreshToken: string) {
  return apiFetch<TokenPair>("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

export function logout(accessToken: string) {
  return apiFetch<{ message: string }>("/api/v1/auth/logout", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function getCurrentUser(accessToken: string) {
  return apiFetch<AuthUser>("/api/v1/auth/me", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
