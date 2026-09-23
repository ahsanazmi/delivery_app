import RazorpayCheckout, {
    type ErrorResponse as RazorpayErrorResponse,
    type SuccessResponse as RazorpaySuccessResponse,
} from "react-native-razorpay";

import { getPaymentRecord, verifyPayment } from "@/services/api/paymentsApi";

// Payment Failure Handling (Phase 19) — the shared open-Razorpay-then-
// verify-then-refetch flow, extracted from checkout.tsx (Phase 13) so the
// order detail screen's "Retry Payment" button can reuse the exact same,
// already-proven steps 3-6 instead of duplicating them. Never treats the
// mobile callback or verify()'s own response as proof by itself — only
// the final, independent refetch decides the outcome.

export type RazorpayCheckoutInput = {
  paymentId: string;
  razorpayKeyId: string | null;
  providerOrderId: string | null;
  amount: number;
};

export type RazorpayFlowOutcome =
  | { status: "paid" }
  // API & Frontend Validation (Phase 37) — genuinely distinct from
  // "failed": the backend confirmed a real status for this payment and
  // it's neither PAID nor FAILED (most commonly still PENDING/PROCESSING
  // — verification hasn't been definitively resolved yet, e.g. a slow
  // webhook or a momentary provider hiccup). Previously this was folded
  // into "failed", which showed the customer a false "Payment not
  // completed" for a payment that might simply still be settling.
  | { status: "pending" }
  | { status: "failed"; reason: string | null }
  | { status: "unavailable" }
  | { status: "unknown" };

export async function openAndVerifyRazorpayPayment(
  accessToken: string,
  payment: RazorpayCheckoutInput,
  prefill: { name?: string; email?: string; phone?: string | null },
): Promise<RazorpayFlowOutcome> {
  if (!payment.razorpayKeyId || !payment.providerOrderId) {
    return { status: "unavailable" };
  }

  let result: RazorpaySuccessResponse;
  try {
    result = await RazorpayCheckout.open({
      key: payment.razorpayKeyId,
      amount: Math.round(payment.amount * 100),
      currency: "INR",
      name: "Say Hi Chai",
      description: "Order payment",
      order_id: payment.providerOrderId,
      prefill: {
        name: prefill.name,
        email: prefill.email,
        contact: prefill.phone ?? undefined,
      },
    });
  } catch (caught) {
    const rzpError = caught as RazorpayErrorResponse;
    return { status: "failed", reason: rzpError?.description || null };
  }

  // The mobile callback (`result`) is never treated as proof by itself —
  // it's only ever handed to the backend to verify.
  try {
    await verifyPayment(accessToken, payment.paymentId, {
      provider_order_id: result.razorpay_order_id,
      provider_payment_id: result.razorpay_payment_id,
      signature: result.razorpay_signature,
    });
  } catch {
    // Verification failing here doesn't necessarily mean the payment
    // failed outright — fall through to the independent status refetch
    // below, which is the actual source of truth either way.
  }

  // An independent re-read of the payment's own status, straight from
  // the backend, regardless of how verify() above resolved.
  try {
    const refreshed = await getPaymentRecord(accessToken, payment.paymentId);
    if (refreshed.status === "paid") return { status: "paid" };
    if (refreshed.status === "failed") return { status: "failed", reason: refreshed.failure_reason };
    // Any other real, confirmed status (pending/processing, most
    // commonly) is genuinely unresolved, not a failure — never claim
    // "not completed" for a payment that may still settle shortly.
    return { status: "pending" };
  } catch {
    return { status: "unknown" };
  }
}
