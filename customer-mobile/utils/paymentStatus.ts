import type { PaymentStatusValue } from "@/services/api/paymentsApi";

// API & Frontend Validation (Phase 37) — the single source of truth for
// how a payment status is shown to the customer, reused by every screen
// that renders one (order detail, payment history). Before this, each
// screen had its own separate, disagreeing mapping — orders/[id].tsx in
// particular had no case at all for "cancelled"/"refund_pending"/
// "partially_refunded"/"refunded", so all four silently rendered as a
// generic "Payment pending" — exactly the ambiguity this phase's own
// "customer UI should clearly distinguish" requirement calls out.
export type PaymentStatusMeta = {
  label: string;
  color: string;
  backgroundColor: string;
};

export function paymentStatusMeta(status: PaymentStatusValue | null | undefined): PaymentStatusMeta {
  switch (status) {
    case "paid":
      return { label: "Paid", color: "#157347", backgroundColor: "#E8F6EE" };
    case "processing":
      return { label: "Payment processing", color: "#D83B05", backgroundColor: "#FFF0E8" };
    case "failed":
      return { label: "Payment failed", color: "#B42318", backgroundColor: "#FEE4E2" };
    // Cancelled is deliberately its own neutral gray, not the same red as
    // "failed" — a cancelled payment isn't an error, and lumping it with
    // "failed" reads as an alarming problem the customer needs to fix.
    case "cancelled":
      return { label: "Cancelled", color: "#6D625D", backgroundColor: "#F0E3DC" };
    // The three refund-related states each get their own color, not one
    // shared "refund" bucket — a customer checking whether their refund
    // has actually landed needs "pending" and "completed" to look
    // different at a glance, not just read different in small text.
    case "refund_pending":
      return { label: "Refund pending", color: "#6B46C1", backgroundColor: "#F3E8FF" };
    case "partially_refunded":
      return { label: "Partially refunded", color: "#3B4FCC", backgroundColor: "#EFF3FF" };
    case "refunded":
      return { label: "Refunded", color: "#0F766E", backgroundColor: "#E6FFFA" };
    case "pending":
    default:
      return { label: "Payment pending", color: "#D83B05", backgroundColor: "#FFF0E8" };
  }
}

// Only these states are genuinely actionable by the customer — every
// other state (paid, cancelled, and every refund-related state) must
// never show a "pay again" button. Before this, orders/[id].tsx's own
// retry button showed for *any* non-"paid" status, including a
// partially/fully refunded payment, mislabeled "Complete Payment".
// `null`/`undefined` (no payment record started yet at all) is also
// actionable — that's the very first "Complete Payment" tap.
export function isPaymentActionable(status: PaymentStatusValue | null | undefined): boolean {
  return status == null || status === "pending" || status === "processing" || status === "failed";
}
