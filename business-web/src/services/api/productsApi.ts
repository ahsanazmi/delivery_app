import { apiFetch } from "@/services/api/apiClient";

export type RestaurantProduct = {
  id: string;
  restaurant_id: string;
  category_id: string | null;
  name: string;
  description: string | null;
  image_url: string | null;
  price: number | string;
  is_available: boolean;
  created_at: string;
  updated_at: string;
};

export type ProductCreatePayload = {
  name: string;
  description?: string | null;
  category_id?: string | null;
  price: number;
  image_url?: string | null;
  is_available?: boolean;
};

export type ProductUpdatePayload = {
  name?: string;
  description?: string | null;
  category_id?: string | null;
  price?: number;
  image_url?: string | null;
  is_available?: boolean;
};

export function listProducts(accessToken: string) {
  return apiFetch<RestaurantProduct[]>("/api/v1/restaurant/products", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function createProduct(accessToken: string, payload: ProductCreatePayload) {
  return apiFetch<RestaurantProduct>("/api/v1/restaurant/products", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export function updateProduct(accessToken: string, productId: string, payload: ProductUpdatePayload) {
  return apiFetch<RestaurantProduct>(`/api/v1/restaurant/products/${productId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export function deleteProduct(accessToken: string, productId: string) {
  return apiFetch<void>(`/api/v1/restaurant/products/${productId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}
