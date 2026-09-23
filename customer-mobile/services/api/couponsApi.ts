import { apiFetch } from "./apiClient";

export type AvailableCoupon = {
  code: string;
  discount_type: "percent" | "fixed";
  discount_value: number;
  min_order: number;
  max_discount: number | null;
  end_date: string | null;
  restaurant_id: string | null;
};

function authHeaders(accessToken: string) {
  return { Authorization: `Bearer ${accessToken}` };
}

export function getAvailableCoupons(accessToken: string) {
  return apiFetch<AvailableCoupon[]>("/api/v1/customer/coupons", {
    headers: authHeaders(accessToken),
  });
}
