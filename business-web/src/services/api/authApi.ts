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

export type RestaurantApplicationPayload = {
  owner_name: string;
  email: string;
  password: string;
  owner_phone?: string | null;
  restaurant_name: string;
  description?: string | null;
  restaurant_phone: string;
  address: string;
  latitude: number;
  longitude: number;
};

/** Public "apply as a restaurant partner" — creates the owner login and a
 * PENDING restaurant that customers can't see until an admin approves it. */
export function registerRestaurant(payload: RestaurantApplicationPayload) {
  return apiFetch<{ user: AuthUser }>("/api/v1/auth/register-restaurant", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
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
