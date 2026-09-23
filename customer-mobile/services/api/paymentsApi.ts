import { apiFetch } from "./apiClient";

export type PaymentMethodOption = {
  method: "cod" | "online";
  label: string;
  available: boolean;
};

export type PaymentStatusValue =
  | "pending"
  | "processing"
  | "paid"
  | "failed"
  | "cancelled"
  | "refund_pending"
  | "partially_refunded"
  | "refunded";

export type Payment = {
  payment_id: string;
  order_id: string;
  amount: number;
  method: "cod" | "online";
  status: PaymentStatusValue;
  transaction_reference: string | null;
  created_at: string;
  updated_at: string;
  // Checkout Payment Decision / Razorpay Order Creation (Phase 6/12) — the
  // public key_id the Razorpay Checkout SDK needs to open the payment
  // sheet for transaction_reference (the provider order id). Never a
  // secret — safe to hold in the app. null for COD.
  razorpay_key_id: string | null;
};

// Payment System Phase 5's generic /api/v1/payments/* shape — distinct
// field names from Payment above (id vs payment_id, provider_order_id vs
// transaction_reference), but the same underlying row. Used here only for
// /verify and the post-verify status refetch (Phase 13), both of which
// only exist on this router, not under /customer/*.
export type PaymentRecord = {
  id: string;
  order_id: string;
  method: "cod" | "razorpay";
  status: PaymentStatusValue;
  amount: number;
  currency: string;
  provider_order_id: string | null;
  provider_payment_id: string | null;
  is_verified: boolean;
  paid_at: string | null;
  created_at: string;
  updated_at: string;
  razorpay_key_id: string | null;
  // Payment Failure Handling (Phase 19) — the specific reason the last
  // attempt failed, so the UI can show something more useful than a bare
  // "failed" status. Always null unless status is "failed".
  failure_reason: string | null;
};

export function getPaymentMethods(accessToken: string) {
  return apiFetch<PaymentMethodOption[]>("/api/v1/customer/payment-methods", {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function recordOrderPayment(accessToken: string, orderId: string) {
  return apiFetch<Payment>(`/api/v1/customer/orders/${orderId}/payment`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Checkout Payment Decision (Phase 13) — sends the Razorpay Checkout
// result to the backend for signature verification. The mobile callback
// alone is never proof of a successful payment; only a 200 here, followed
// by an independent status refetch (getPaymentRecord below), counts.
export function verifyPayment(
  accessToken: string,
  paymentId: string,
  result: { provider_order_id: string; provider_payment_id: string; signature: string },
) {
  return apiFetch<PaymentRecord>(`/api/v1/payments/${paymentId}/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify(result),
  });
}

// Phase 13 step 6 — an independent re-read of the payment's status, used
// after verify() to confirm the final state directly from the backend
// rather than trusting verify()'s own response alone.
export function getPaymentRecord(accessToken: string, paymentId: string) {
  return apiFetch<PaymentRecord>(`/api/v1/payments/${paymentId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Payment Failure Handling (Phase 19) — looked up by order id, for
// screens (the order detail screen) that only know which order they're
// showing, not which payment id belongs to it. 404s until a payment has
// actually been created for the order.
export function getPaymentByOrder(accessToken: string, orderId: string) {
  return apiFetch<PaymentRecord>(`/api/v1/payments/order/${orderId}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Payment Failure Handling (Phase 19) — reopens the SAME provider order
// (never a new one) and resets status back to pending, clearing any prior
// failure_reason. Only valid from pending/failed — the backend itself
// enforces that (409 otherwise, e.g. an already-paid or cod payment) so
// this never needs to duplicate that check client-side to be safe.
export function retryPayment(accessToken: string, paymentId: string) {
  return apiFetch<PaymentRecord>(`/api/v1/payments/${paymentId}/retry`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// Customer Payment History (Phase 26) — the customer/*'s own generic
// shape (payment_id/order_id, not id/order_id like PaymentRecord above),
// matching CustomerPaymentRead on the backend. Always scoped server-side
// to the calling customer's own payments — never accepts a user id here.
export type CustomerPaymentHistoryEntry = {
  payment_id: string;
  order_id: string;
  order_number: string;
  amount: number;
  method: "cod" | "online";
  status: PaymentStatusValue;
  transaction_reference: string | null;
  created_at: string;
  updated_at: string;
};

export function listPaymentHistory(
  accessToken: string,
  options: { page?: number; limit?: number } = {},
) {
  const params = new URLSearchParams();
  if (options.page) params.set("page", String(options.page));
  if (options.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  return apiFetch<CustomerPaymentHistoryEntry[]>(
    `/api/v1/customer/payments${query ? `?${query}` : ""}`,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  );
}
