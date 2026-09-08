import { apiFetch } from "./apiClient";

export type CartLine = {
  id: string;
  product_id: string;
  restaurant_id: string;
  product_name: string;
  unit_price: number;
  quantity: number;
};

export type CartResponse = {
  id: string;
  user_id: string;
  restaurant_id: string | null;
  items: CartLine[];
  subtotal: number;
  total_items: number;
  total: number;
};

export function getCart() {
  return apiFetch<CartResponse>("/api/v1/cart");
}

export function addCartItem(payload: {
  product_id: string;
  restaurant_id: string;
  product_name: string;
  unit_price: number;
  quantity: number;
}) {
  return apiFetch<CartResponse>("/api/v1/cart/items", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateCartItem(itemId: string, quantity: number) {
  return apiFetch<CartResponse>(`/api/v1/cart/items/${itemId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ quantity }),
  });
}

export function removeCartItem(itemId: string) {
  return apiFetch<CartResponse>(`/api/v1/cart/items/${itemId}`, {
    method: "DELETE",
  });
}

export function clearCart() {
  return apiFetch<CartResponse>("/api/v1/cart", { method: "DELETE" });
}
