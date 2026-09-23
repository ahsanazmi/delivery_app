import { apiFetch } from "./apiClient";
import type { Restaurant } from "@/types/restaurant";

export function getFavorites(accessToken: string) {
  return apiFetch<Restaurant[]>("/api/v1/customer/favorites", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function addFavorite(accessToken: string, restaurantId: string) {
  return apiFetch<void>(`/api/v1/customer/favorites/${restaurantId}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function removeFavorite(accessToken: string, restaurantId: string) {
  return apiFetch<void>(`/api/v1/customer/favorites/${restaurantId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
