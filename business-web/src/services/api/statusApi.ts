import { apiFetch } from "@/services/api/apiClient";
import type { OperatingHourRead } from "@/services/api/hoursApi";

export type RestaurantStatus = {
  restaurant_id: string;
  is_open: boolean;
  is_accepting_orders: boolean;
  hours_configured: boolean;
  today: OperatingHourRead | null;
};

export function getRestaurantStatus(accessToken: string) {
  return apiFetch<RestaurantStatus>("/api/v1/restaurant/status", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function updateRestaurantStatus(accessToken: string, isOpen: boolean) {
  return apiFetch<RestaurantStatus>("/api/v1/restaurant/status", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ is_open: isOpen }),
  });
}
