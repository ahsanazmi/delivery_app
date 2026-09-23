import { apiFetch } from "./apiClient";

export type OrderReview = {
  id: string;
  order_id: string;
  user_id: string;
  restaurant_rating: number;
  delivery_rating: number;
  comment: string | null;
  created_at: string;
  updated_at: string;
};

export type OrderReviewPayload = {
  restaurant_rating: number;
  delivery_rating: number;
  comment?: string | null;
};

export function getOrderReview(accessToken: string, orderId: string) {
  return apiFetch<OrderReview | null>(`/api/v1/customer/orders/${orderId}/review`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function createOrderReview(accessToken: string, orderId: string, payload: OrderReviewPayload) {
  return apiFetch<OrderReview>(`/api/v1/customer/orders/${orderId}/review`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}

export function updateOrderReview(
  accessToken: string,
  reviewId: string,
  payload: Partial<OrderReviewPayload>,
) {
  return apiFetch<OrderReview>(`/api/v1/customer/reviews/${reviewId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
}
