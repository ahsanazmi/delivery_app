import { Redirect, useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { OrderReviewSection } from "@/components/order-review";
import { useSession } from "@/features/auth/session-context";
import { useCart } from "@/features/cart/cart-context";
import { openAndVerifyRazorpayPayment } from "@/features/payments/razorpay-flow";
import { ApiError } from "@/services/api/apiClient";
import { cancelOrder, getOrder, reorderOrder, type Order, type OrderStatus } from "@/services/api/ordersApi";
import { getPaymentByOrder, recordOrderPayment, retryPayment, type PaymentRecord } from "@/services/api/paymentsApi";
import { rupees } from "@/utils/currency";
import { isPaymentActionable, paymentStatusMeta } from "@/utils/paymentStatus";

const CUSTOMER_CANCELLABLE_STATUSES: OrderStatus[] = ["placed", "confirmed"];
const TERMINAL_STATUSES: OrderStatus[] = ["delivered", "cancelled", "rejected"];

export default function OrderDetailScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user, accessToken } = useSession();
  const { refresh: refreshCart } = useCart();
  const [order, setOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [reordering, setReordering] = useState(false);
  const [payment, setPayment] = useState<PaymentRecord | null>(null);
  const [paymentLoading, setPaymentLoading] = useState(false);
  const [retrying, setRetrying] = useState(false);

  // Frontend State Synchronization (Phase 19) — refetches every time this
  // screen regains focus (e.g. the customer navigates here, away, and back),
  // not just once on first mount, so a status change made elsewhere (the
  // restaurant accepting, a rider picking up) is never left stale here.
  // Live, no-navigation-required updates are the /track/[id] screen's job
  // (WebSocket-backed, see features/tracking/use-order-tracking.ts); this
  // is the same focus-refetch pattern rider-mobile already uses throughout.
  const loadOrder = useCallback(async () => {
    if (!user || !accessToken || !id) return;
    try {
      const nextOrder = await getOrder(accessToken, id);
      setOrder(nextOrder);
      // Payment Failure Handling (Phase 19) — an online order's own
      // payment state (pending/failed/paid, and why) lives on the
      // Payment record, not the order itself; fetched alongside so the
      // payment card below always reflects the current, real state.
      if (nextOrder.payment_method !== "cod") {
        setPaymentLoading(true);
        try {
          const record = await getPaymentByOrder(accessToken, nextOrder.id);
          setPayment(record);
        } catch {
          // No payment record yet (e.g. the checkout-time creation call
          // itself failed) — the card below handles a null payment for
          // an online order as its own, retryable state.
          setPayment(null);
        } finally {
          setPaymentLoading(false);
        }
      } else {
        setPayment(null);
      }
    } finally {
      setLoading(false);
    }
  }, [accessToken, id, user]);

  useFocusEffect(
    useCallback(() => {
      void loadOrder();
    }, [loadOrder]),
  );

  // Payment Failure Handling (Phase 19) — the single payment-action entry
  // point, covering every retryable state this screen can show:
  //   - no payment record at all (e.g. the checkout-time creation call
  //     itself failed) -> record_order_payment() is idempotent, so
  //     calling it here either creates the missing record or returns the
  //     one that already exists, safely either way.
  //   - FAILED -> reset back to pending via /retry first (reopening the
  //     SAME provider order, never a new one), then reopen checkout.
  //   - PENDING -> nothing to reset; reopen the same checkout directly.
  // Either way, the mobile callback is never trusted alone — the same
  // open-then-verify-then-refetch flow checkout.tsx itself uses
  // (Phase 13) decides the outcome.
  async function handlePaymentAction() {
    if (!accessToken || !order) return;
    setRetrying(true);
    try {
      let input: { paymentId: string; razorpayKeyId: string | null; providerOrderId: string | null; amount: number };
      if (!payment) {
        const created = await recordOrderPayment(accessToken, order.id);
        input = {
          paymentId: created.payment_id,
          razorpayKeyId: created.razorpay_key_id,
          providerOrderId: created.transaction_reference,
          amount: created.amount,
        };
      } else if (payment.status === "failed") {
        const retried = await retryPayment(accessToken, payment.id);
        setPayment(retried);
        input = {
          paymentId: retried.id, razorpayKeyId: retried.razorpay_key_id,
          providerOrderId: retried.provider_order_id, amount: retried.amount,
        };
      } else {
        input = {
          paymentId: payment.id, razorpayKeyId: payment.razorpay_key_id,
          providerOrderId: payment.provider_order_id, amount: payment.amount,
        };
      }

      const outcome = await openAndVerifyRazorpayPayment(accessToken, input, {
        name: user?.name, email: user?.email, phone: user?.phone,
      });
      if (outcome.status === "paid") {
        Alert.alert("Payment successful", "Your payment has been confirmed.");
      } else if (outcome.status === "pending") {
        Alert.alert("Your payment is still processing", "We'll update your order once it's confirmed.");
      } else if (outcome.status === "unknown") {
        Alert.alert("We're confirming your payment", "Check back shortly to confirm payment status.");
      } else if (outcome.status === "unavailable") {
        Alert.alert("Unable to retry", "This payment can't be retried right now.");
      } else {
        Alert.alert("Payment not completed", outcome.reason || "Please try again.");
      }
      await loadOrder();
    } catch (error) {
      Alert.alert("Unable to retry", error instanceof ApiError ? error.message : "Please try again.");
    } finally {
      setRetrying(false);
    }
  }

  if (!user || !accessToken) return <Redirect href="/login" />;
  if (!id) return <Redirect href="/orders" />;

  async function handleCancel() {
    if (!accessToken || !order) return;
    try {
      const nextOrder = await cancelOrder(
        accessToken,
        order.id,
        "Customer cancelled order",
      );
      setOrder(nextOrder);
    } catch (error) {
      Alert.alert(
        "Unable to cancel",
        error instanceof ApiError ? error.message : "Please try again.",
      );
    }
  }

  async function handleReorder() {
    if (!order || !accessToken) return;
    setReordering(true);
    try {
      const cart = await reorderOrder(accessToken, order.id);
      await refreshCart();
      if (cart.items.length === 0) {
        Alert.alert("Nothing to reorder", "None of the items from this order are available anymore.");
        return;
      }
      if (cart.removed_items.length > 0) {
        Alert.alert(
          "Some items are unavailable",
          `${cart.removed_items.join(", ")} could no longer be added. The rest of your order is in your cart.`,
          [{ text: "View cart", onPress: () => router.push("/cart") }],
        );
      } else {
        router.push("/cart");
      }
    } catch (error) {
      Alert.alert("Reorder failed", error instanceof ApiError ? error.message : "Unable to reorder right now.");
    } finally {
      setReordering(false);
    }
  }

  if (loading) {
    return (
      <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
        <Text style={styles.loading}>Loading order…</Text>
      </SafeAreaView>
    );
  }

  if (!order) {
    return (
      <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
        <Text style={styles.loading}>Order not found.</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>Order</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.card}>
          <View style={styles.rowBetween}>
            <Text style={styles.orderNumber}>{order.order_number}</Text>
            <Text style={[styles.status, orderStatusStyle(order.status)]}>
              {order.status}
            </Text>
          </View>
          <Text style={styles.meta}>
            {new Date(order.created_at).toLocaleString()}
          </Text>
        </View>

        {!TERMINAL_STATUSES.includes(order.status) && (
          <Pressable
            style={styles.trackButton}
            onPress={() => router.push({ pathname: "/track/[id]", params: { id: order.id } })}
          >
            <Text style={styles.trackButtonText}>Track order</Text>
          </Pressable>
        )}

        {order.restaurant_name && (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>Restaurant</Text>
            <Text style={styles.meta}>{order.restaurant_name}</Text>
            {order.restaurant_address && (
              <Text style={styles.meta}>{order.restaurant_address}</Text>
            )}
            {order.restaurant_phone && (
              <Text style={styles.meta}>{order.restaurant_phone}</Text>
            )}
          </View>
        )}

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Delivery address</Text>
          <Text style={styles.meta}>{order.address_line}</Text>
          <Text style={styles.meta}>
            {order.city}, {order.state ?? "N/A"} {order.postal_code}
          </Text>
          {order.landmark ? (
            <Text style={styles.meta}>Landmark: {order.landmark}</Text>
          ) : null}
          {order.delivery_instructions ? (
            <Text style={styles.meta}>
              Instructions: {order.delivery_instructions}
            </Text>
          ) : null}
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Items</Text>
          {order.items.map((item) => (
            <View key={item.id} style={styles.itemRow}>
              <Text style={styles.itemName}>{item.product_name}</Text>
              <Text style={styles.itemMeta}>
                {item.quantity} × {rupees(item.unit_price)}
              </Text>
            </View>
          ))}
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Bill summary</Text>
          <View style={styles.summaryRow}>
            <Text style={styles.label}>Subtotal</Text>
            <Text style={styles.value}>{rupees(order.subtotal)}</Text>
          </View>
          <View style={styles.summaryRow}>
            <Text style={styles.label}>Delivery</Text>
            <Text style={styles.value}>{rupees(order.delivery_fee)}</Text>
          </View>
          <View style={[styles.summaryRow, styles.totalRow]}>
            <Text style={styles.totalLabel}>Total</Text>
            <Text style={styles.totalValue}>{rupees(order.total)}</Text>
          </View>
        </View>

        {order.payment_method === "cod" && (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>Payment</Text>
            <View style={styles.paymentRow}>
              <Text style={styles.paymentIcon}>💵</Text>
              <View style={styles.paymentTextWrap}>
                <Text style={styles.paymentTitle}>Cash on Delivery</Text>
                <Text style={styles.paymentAmount}>Amount to Pay: {rupees(order.total)}</Text>
              </View>
              <Text
                style={[
                  styles.paymentStatusBadge,
                  order.is_paid ? styles.paymentStatusPaid : styles.paymentStatusPending,
                ]}
              >
                {order.is_paid ? "Paid" : "Pending"}
              </Text>
            </View>
          </View>
        )}

        {order.payment_method !== "cod" && (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>Payment</Text>
            {paymentLoading ? (
              <ActivityIndicator color="#FF5A1F" />
            ) : (
              <>
                <View style={styles.paymentRow}>
                  <Text style={styles.paymentIcon}>💳</Text>
                  <View style={styles.paymentTextWrap}>
                    <Text style={styles.paymentTitle}>
                      {payment ? "Online payment" : "Payment not started"}
                    </Text>
                    <Text style={styles.paymentAmount}>Amount: {rupees(order.total)}</Text>
                    {payment?.status === "failed" && payment.failure_reason && (
                      <Text style={styles.paymentFailureReason}>{payment.failure_reason}</Text>
                    )}
                    {payment?.status === "refund_pending" && (
                      <Text style={styles.paymentFailureReason}>
                        Your refund is being processed and will reach you soon.
                      </Text>
                    )}
                  </View>
                  <Text
                    style={[
                      styles.paymentStatusBadge,
                      payment
                        ? {
                            color: paymentStatusMeta(payment.status).color,
                            backgroundColor: paymentStatusMeta(payment.status).backgroundColor,
                          }
                        : styles.paymentStatusPending,
                    ]}
                  >
                    {payment ? paymentStatusMeta(payment.status).label : "Pending"}
                  </Text>
                </View>
                {isPaymentActionable(payment?.status) && !TERMINAL_STATUSES.includes(order.status) && (
                  <Pressable
                    style={[styles.retryPaymentButton, retrying && styles.retryPaymentButtonDisabled]}
                    onPress={handlePaymentAction}
                    disabled={retrying}
                  >
                    <Text style={styles.retryPaymentText}>
                      {retrying ? "Please wait…" : payment?.status === "failed" ? "Retry Payment" : "Complete Payment"}
                    </Text>
                  </Pressable>
                )}
              </>
            )}
          </View>
        )}

        {order.status === "delivered" && (
          <OrderReviewSection accessToken={accessToken} orderId={order.id} />
        )}

        {TERMINAL_STATUSES.includes(order.status) ? (
          <Pressable style={styles.reorderButton} onPress={handleReorder} disabled={reordering}>
            <Text style={styles.reorderText}>{reordering ? "Reordering…" : "Reorder"}</Text>
          </Pressable>
        ) : null}

        {CUSTOMER_CANCELLABLE_STATUSES.includes(order.status) ? (
          <Pressable style={styles.cancelButton} onPress={handleCancel}>
            <Text style={styles.cancelText}>Cancel order</Text>
          </Pressable>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function orderStatusStyle(status: string) {
  switch (status) {
    case "delivered":
      return { backgroundColor: "#E8F6EE", color: "#157347" };
    case "cancelled":
    case "rejected":
      return { backgroundColor: "#FEE4E2", color: "#B42318" };
    default:
      return { backgroundColor: "#FFF0E8", color: "#D83B05" };
  }
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#FFF8F2" },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 18,
    paddingTop: 16,
    paddingBottom: 8,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: "#fff",
    justifyContent: "center",
    alignItems: "center",
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  backText: { color: "#241913", fontSize: 24, fontWeight: "700" },
  title: { fontSize: 28, fontWeight: "800", color: "#241913" },
  headerSpacer: { width: 40 },
  content: { padding: 20, paddingBottom: 40, gap: 16 },
  card: {
    backgroundColor: "#fff",
    borderRadius: 18,
    padding: 16,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  rowBetween: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  orderNumber: { color: "#241913", fontWeight: "800", fontSize: 16 },
  status: {
    borderRadius: 999,
    overflow: "hidden",
    paddingHorizontal: 8,
    paddingVertical: 4,
    fontWeight: "800",
    textTransform: "capitalize",
    fontSize: 12,
  },
  meta: { color: "#5F5049", marginTop: 6 },
  sectionTitle: {
    color: "#241913",
    fontWeight: "800",
    fontSize: 17,
    marginBottom: 8,
  },
  itemRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 8,
  },
  itemName: { color: "#241913", fontWeight: "700" },
  itemMeta: { color: "#6D625D" },
  summaryRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 10,
  },
  label: { color: "#5F5049" },
  value: { color: "#241913", fontWeight: "700" },
  totalRow: { borderTopWidth: 1, borderColor: "#F0E3DC", paddingTop: 10 },
  totalLabel: { color: "#241913", fontWeight: "800" },
  totalValue: { color: "#D83B05", fontWeight: "900" },
  paymentRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: "#FFF3EE",
    borderRadius: 12,
    padding: 12,
  },
  paymentIcon: { fontSize: 22 },
  paymentTextWrap: { flex: 1 },
  paymentTitle: { color: "#241913", fontWeight: "800" },
  paymentAmount: { color: "#5F5049", fontSize: 13, marginTop: 3 },
  paymentStatusBadge: {
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 5,
    fontSize: 12,
    fontWeight: "800",
    overflow: "hidden",
  },
  paymentStatusPending: { backgroundColor: "#FFE4D6", color: "#D83B05" },
  paymentStatusPaid: { backgroundColor: "#E8F6EE", color: "#157347" },
  paymentFailureReason: { color: "#B42318", fontSize: 12, marginTop: 4 },
  retryPaymentButton: {
    backgroundColor: "#FF5A1F",
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 12,
  },
  retryPaymentButtonDisabled: { opacity: 0.6 },
  retryPaymentText: { color: "#fff", fontWeight: "800" },
  cancelButton: {
    backgroundColor: "#FEE4E2",
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  cancelText: { color: "#B42318", fontWeight: "800" },
  reorderButton: {
    backgroundColor: "#FFF0E8",
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  reorderText: { color: "#D83B05", fontWeight: "800" },
  trackButton: {
    backgroundColor: "#241913",
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  trackButtonText: { color: "#fff", fontWeight: "800" },
  loading: {
    color: "#241913",
    textAlign: "center",
    marginTop: 40,
    fontWeight: "700",
  },
});
