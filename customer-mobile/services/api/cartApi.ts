import { apiFetch } from "./apiClient";

export type CartItemLine = {
  id: string;
  product_id: string;
  product_name: string;
  unit_price: number;
  quantity: number;
};

export type CartRestaurant = {
  id: string;
  name: string;
  logo_url: string | null;
  minimum_order: number;
  delivery_fee: number;
  is_open: boolean;
};

export type CartResponse = {
  restaurant: CartRestaurant | null;
  items: CartItemLine[];
  subtotal: number;
  delivery_fee: number;
  tax: number;
  discount: number;
  total: number;
  total_items: number;
  removed_items: string[];
  coupon_code: string | null;
  coupon_message: string | null;
};

function authHeaders(accessToken: string) {
  return { Authorization: `Bearer ${accessToken}` };
}

export function getCart(accessToken: string) {
  return apiFetch<CartResponse>("/api/v1/customer/cart", {
    headers: authHeaders(accessToken),
  });
}

export function addCartItem(accessToken: string, productId: string, quantity = 1) {
  return apiFetch<CartResponse>("/api/v1/customer/cart/items", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(accessToken) },
    body: JSON.stringify({ product_id: productId, quantity }),
  });
}

export function updateCartItem(accessToken: string, itemId: string, quantity: number) {
  return apiFetch<CartResponse>(`/api/v1/customer/cart/items/${itemId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders(accessToken) },
    body: JSON.stringify({ quantity }),
  });
}

export function removeCartItem(accessToken: string, itemId: string) {
  return apiFetch<CartResponse>(`/api/v1/customer/cart/items/${itemId}`, {
    method: "DELETE",
    headers: authHeaders(accessToken),
  });
}

export function clearCart(accessToken: string) {
  return apiFetch<CartResponse>("/api/v1/customer/cart", {
    method: "DELETE",
    headers: authHeaders(accessToken),
  });
}

export function applyCoupon(accessToken: string, code: string) {
  return apiFetch<CartResponse>("/api/v1/customer/cart/apply-coupon", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(accessToken) },
    body: JSON.stringify({ code }),
  });
}

export function removeCoupon(accessToken: string) {
  return apiFetch<CartResponse>("/api/v1/customer/cart/coupon", {
    method: "DELETE",
    headers: authHeaders(accessToken),
  });
}
