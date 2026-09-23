import { apiFetch } from "./apiClient";
import type { Address } from "./addressesApi";
import type { CartItemLine, CartRestaurant } from "./cartApi";

export type CheckoutResponse = {
  addresses: Address[];
  selected_address: Address | null;
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
  issues: string[];
};

export type OrderValidateResponse = {
  valid: boolean;
  issues: string[];
  address: Address | null;
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
};

export function getCheckout(accessToken: string) {
  return apiFetch<CheckoutResponse>("/api/v1/customer/checkout", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function validateOrder(accessToken: string, addressId: string) {
  return apiFetch<OrderValidateResponse>("/api/v1/customer/orders/validate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ address_id: addressId }),
  });
}
