import { apiFetch } from "@/services/api/apiClient";

export type RestaurantCategory = {
  id: string;
  restaurant_id: string;
  name: string;
  image_url: string | null;
  display_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type CategoryCreatePayload = {
  name: string;
  display_order?: number;
  image_url?: string | null;
};

export type CategoryUpdatePayload = {
  name?: string;
  display_order?: number;
  image_url?: string | null;
  is_active?: boolean;
};

export function listCategories(accessToken: string) {
  return apiFetch<RestaurantCategory[]>("/api/v1/restaurant/categories", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function createCategory(accessToken: string, payload: CategoryCreatePayload) {
  return apiFetch<RestaurantCategory>("/api/v1/restaurant/categories", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export function updateCategory(accessToken: string, categoryId: string, payload: CategoryUpdatePayload) {
  return apiFetch<RestaurantCategory>(`/api/v1/restaurant/categories/${categoryId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export function deleteCategory(accessToken: string, categoryId: string) {
  return apiFetch<void>(`/api/v1/restaurant/categories/${categoryId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
