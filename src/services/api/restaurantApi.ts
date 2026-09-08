import { apiFetch } from "@/services/api/apiClient";

export type RestaurantSummary = {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  phone: string;
  address: string;
  latitude: number | string;
  longitude: number | string;
  logo_url: string | null;
  cover_image_url: string | null;
  minimum_order: number | string;
  delivery_fee: number | string;
  average_rating: number | string;
  is_open: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export function getRestaurantPortal(accessToken: string) {
  return apiFetch<RestaurantSummary[]>("/api/v1/restaurants?open_only=false", {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  });
}

export function createRestaurantProfile(
  accessToken: string,
  payload: {
    name: string;
    description?: string | null;
    phone: string;
    address: string;
    latitude: number;
    longitude: number;
    minimum_order?: number;
    delivery_fee?: number;
    owner_id?: string;
  },
) {
  return apiFetch<RestaurantSummary>("/api/v1/restaurants", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}
