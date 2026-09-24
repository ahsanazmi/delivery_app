import { Redirect, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
    ActivityIndicator,
    Alert,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    TextInput,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { useCart } from "@/features/cart/cart-context";
import { presentDeviceLocationAlert, requestDeviceLocation } from "@/features/location/device-location";
import { openAndVerifyRazorpayPayment } from "@/features/payments/razorpay-flow";
import { createAddress, type Address } from "@/services/api/addressesApi";
import { ApiError } from "@/services/api/apiClient";
import { getCheckout, validateOrder, type CheckoutResponse } from "@/services/api/checkoutApi";
import { createOrder } from "@/services/api/ordersApi";
import { getPaymentMethods, recordOrderPayment, type PaymentMethodOption } from "@/services/api/paymentsApi";
import { rupees } from "@/utils/currency";

const emptyForm = {
  label: "Home",
  recipientName: "",
  phone: "",
  addressLine: "",
  city: "",
  state: "",
  postalCode: "",
  landmark: "",
  latitude: "",
  longitude: "",
  deliveryInstructions: "",
};

export default function CheckoutScreen() {
  const router = useRouter();
  const { user, accessToken } = useSession();
  const { refresh: refreshCart } = useCart();
  const [checkout, setCheckout] = useState<CheckoutResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedAddressId, setSelectedAddressId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [placing, setPlacing] = useState(false);
  const [paymentMethods, setPaymentMethods] = useState<PaymentMethodOption[]>([]);
  const [paymentMethod, setPaymentMethod] = useState<"cod" | "razorpay">("cod");

  const loadCheckout = useCallback(async () => {
    if (!accessToken) return;
    setLoading(true);
    setLoadError(null);
    try {
      const [data, methods] = await Promise.all([
        getCheckout(accessToken),
        getPaymentMethods(accessToken).catch(() => []),
      ]);
      setCheckout(data);
      setPaymentMethods(methods);
      setSelectedAddressId((current) => {
        if (current && data.addresses.some((a: Address) => a.id === current)) return current;
        return data.selected_address?.id ?? data.addresses[0]?.id ?? null;
      });
    } catch (caught) {
      setLoadError(caught instanceof ApiError ? caught.message : "Unable to load checkout.");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    loadCheckout();
  }, [loadCheckout]);

  useEffect(() => {
    const online = paymentMethods.find((m) => m.method === "online");
    if (paymentMethod === "razorpay" && !online?.available) {
      setPaymentMethod("cod");
    }
  }, [paymentMethods, paymentMethod]);

  if (!user || !accessToken) return <Redirect href="/login" />;

  async function requestCurrentLocation() {
    // Maps & Location System Phase 7 — one-shot only, never continuous;
    // manual entry (every field below) stays fully usable regardless of
    // what this returns, for every one of the five states it can report.
    const result = await requestDeviceLocation();
    if (result.status === "granted") {
      setForm((current) => ({
        ...current,
        latitude: String(result.latitude),
        longitude: String(result.longitude),
      }));
      return;
    }
    presentDeviceLocationAlert(result);
  }

  async function saveAddress() {
    if (!accessToken) return;

    if (
      !form.addressLine ||
      !form.city ||
      !form.state ||
      !form.postalCode ||
      !form.recipientName ||
      !form.phone
    ) {
      Alert.alert(
        "Incomplete address",
        "Please fill in the delivery details before saving.",
      );
      return;
    }

    try {
      setSaving(true);
      const nextAddress = await createAddress(accessToken, {
        label: form.label || "Home",
        recipient_name: form.recipientName,
        phone: form.phone,
        address_line: form.addressLine,
        city: form.city,
        state: form.state,
        postal_code: form.postalCode,
        landmark: form.landmark || null,
        latitude: form.latitude ? Number(form.latitude) : null,
        longitude: form.longitude ? Number(form.longitude) : null,
      });
      setSelectedAddressId(nextAddress.id);
      setForm((current) => ({
        ...current,
        label: "Home",
        landmark: "",
        latitude: "",
        longitude: "",
      }));
      await loadCheckout();
      Alert.alert(
        "Address saved",
        "Your delivery address is ready for checkout.",
      );
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Unable to save the address.";
      Alert.alert("Address error", message);
    } finally {
      setSaving(false);
    }
  }

  async function placeOrder() {
    if (!checkout || !accessToken) return;

    if (!selectedAddressId) {
      Alert.alert("Address required", "Choose or add a delivery address before placing the order.");
      return;
    }

    try {
      setPlacing(true);
      const validation = await validateOrder(accessToken, selectedAddressId);
      if (!validation.valid) {
        Alert.alert("Can't place this order", validation.issues.join("\n"));
        await loadCheckout();
        return;
      }

      const newOrder = await createOrder(accessToken, {
        address_id: selectedAddressId,
        payment_method: paymentMethod,
        delivery_instructions: form.deliveryInstructions || null,
      });

      if (paymentMethod === "razorpay") {
        // Steps 1-2 — request payment initialization and receive the
        // checkout information (key_id, provider order id, amount) back
        // from the backend. The order already exists at this point — a
        // failure here is a payment-step problem, never a reason to tell
        // the customer their order itself failed (Payment Failure
        // Handling, Phase 19: never leave the customer thinking they
        // need to place a second order).
        let payment;
        try {
          payment = await recordOrderPayment(accessToken, newOrder.id);
        } catch {
          await Promise.all([refreshCart(), loadCheckout()]);
          Alert.alert(
            "Order placed",
            "Your order was placed, but online payment couldn't be started right now. You can retry payment from your order.",
          );
          router.replace("/orders");
          return;
        }

        const outcome = await openAndVerifyRazorpayPayment(
          accessToken,
          {
            paymentId: payment.payment_id,
            razorpayKeyId: payment.razorpay_key_id,
            providerOrderId: payment.transaction_reference,
            amount: payment.amount,
          },
          { name: user?.name, email: user?.email, phone: user?.phone },
        );
        await Promise.all([refreshCart(), loadCheckout()]);
        if (outcome.status === "paid") {
          Alert.alert("Payment successful", "Your order has been placed.");
        } else if (outcome.status === "pending") {
          Alert.alert(
            "Your payment is still processing",
            "Your order has been placed. We'll update your order once payment is confirmed.",
          );
        } else if (outcome.status === "unknown") {
          Alert.alert(
            "We're confirming your payment",
            "Your order was placed. Check the order's status shortly to confirm payment.",
          );
        } else {
          Alert.alert(
            "Payment not completed",
            outcome.status === "failed" && outcome.reason
              ? `${outcome.reason} Your order was placed — you can retry payment from your order.`
              : "Your order was placed, but the payment wasn't completed. You can retry payment from your order.",
          );
        }
        router.replace("/orders");
        return;
      }

      // Record the COD payment tracking row; failure here shouldn't block the
      // customer from seeing their order — it's a background bookkeeping step.
      recordOrderPayment(accessToken, newOrder.id).catch(() => undefined);
      await Promise.all([refreshCart(), loadCheckout()]);
      router.replace("/orders");
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Unable to place the order.";
      Alert.alert("Order failed", message);
    } finally {
      setPlacing(false);
    }
  }

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>Checkout</Text>
        <View style={styles.headerSpacer} />
      </View>

      {loading && !checkout ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#FF5A1F" />
        </View>
      ) : loadError ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{loadError}</Text>
          <Pressable style={styles.primaryButton} onPress={loadCheckout}>
            <Text style={styles.primaryText}>Try again</Text>
          </Pressable>
        </View>
      ) : checkout ? (
        <ScrollView contentContainerStyle={styles.content}>
          {checkout.issues.length > 0 && (
            <View style={styles.issuesBanner}>
              {checkout.issues.map((issue) => (
                <Text key={issue} style={styles.issueText}>
                  • {issue}
                </Text>
              ))}
            </View>
          )}

          <View style={styles.card}>
            <Text style={styles.sectionTitle}>
              {checkout.restaurant?.name ?? "Your order"}
            </Text>
            {checkout.items.length === 0 ? (
              <Text style={styles.muted}>No items in your cart.</Text>
            ) : (
              checkout.items.map((item) => (
                <View key={item.id} style={styles.orderItemRow}>
                  <Text style={styles.orderItemName}>
                    {item.product_name} × {item.quantity}
                  </Text>
                  <Text style={styles.value}>{rupees(item.unit_price * item.quantity)}</Text>
                </View>
              ))
            )}
          </View>

          <View style={styles.summaryBox}>
            <Text style={styles.sectionTitle}>Bill summary</Text>
            <View style={styles.summaryRow}>
              <Text style={styles.label}>Items total</Text>
              <Text style={styles.value}>{rupees(checkout.subtotal)}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.label}>Delivery fee</Text>
              <Text style={styles.value}>{rupees(checkout.delivery_fee)}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.label}>Taxes</Text>
              <Text style={styles.value}>{rupees(checkout.tax)}</Text>
            </View>
            {checkout.discount > 0 && (
              <View style={styles.summaryRow}>
                <Text style={styles.label}>
                  Discount{checkout.coupon_code ? ` (${checkout.coupon_code})` : ""}
                </Text>
                <Text style={styles.value}>-{rupees(checkout.discount)}</Text>
              </View>
            )}
            <View style={[styles.summaryRow, styles.totalRow]}>
              <Text style={styles.totalLabel}>Total</Text>
              <Text style={styles.totalValue}>{rupees(checkout.total)}</Text>
            </View>
          </View>

          <View style={styles.card}>
            <Text style={styles.sectionTitle}>Payment method</Text>
            <Pressable
              style={styles.paymentRow}
              onPress={() => setPaymentMethod("cod")}
            >
              <Text style={styles.paymentIcon}>💵</Text>
              <View style={styles.paymentTextWrap}>
                <Text style={styles.paymentTitle}>Cash on Delivery</Text>
                <Text style={styles.paymentSubtitle}>Amount to Pay: {rupees(checkout.total)}</Text>
              </View>
              {paymentMethod === "cod" && <Text style={styles.paymentCheck}>✓</Text>}
            </Pressable>
            {(() => {
              const online = paymentMethods.find((m) => m.method === "online");
              if (!online) return null;
              return (
                <Pressable
                  style={[styles.paymentRow, styles.paymentRowSpaced, !online.available && styles.paymentRowDisabled]}
                  onPress={() => online.available && setPaymentMethod("razorpay")}
                  disabled={!online.available}
                >
                  <Text style={styles.paymentIcon}>💳</Text>
                  <View style={styles.paymentTextWrap}>
                    <Text style={styles.paymentTitle}>{online.label}</Text>
                    <Text style={styles.paymentSubtitle}>
                      {online.available
                        ? `Amount to Pay: ${rupees(checkout.total)}`
                        : "Currently unavailable"}
                    </Text>
                  </View>
                  {paymentMethod === "razorpay" && <Text style={styles.paymentCheck}>✓</Text>}
                </Pressable>
              );
            })()}
          </View>

          <View style={styles.card}>
            <Text style={styles.sectionTitle}>Saved addresses</Text>
            {checkout.addresses.length === 0 ? (
              <Text style={styles.muted}>
                No saved addresses yet. Add one below.
              </Text>
            ) : (
              checkout.addresses.map((address) => (
                <Pressable
                  key={address.id}
                  style={[
                    styles.addressOption,
                    selectedAddressId === address.id &&
                      styles.addressOptionSelected,
                  ]}
                  onPress={() => setSelectedAddressId(address.id)}
                >
                  <View style={styles.addressRow}>
                    <Text style={styles.addressLabel}>{address.label}</Text>
                    {address.is_default ? (
                      <Text style={styles.badge}>Default</Text>
                    ) : null}
                  </View>
                  <Text style={styles.addressText}>{address.recipient_name}</Text>
                  <Text style={styles.addressText}>{address.address_line}</Text>
                  <Text style={styles.addressText}>
                    {address.city}, {address.state}
                  </Text>
                </Pressable>
              ))
            )}
          </View>

          <View style={styles.card}>
            <View style={styles.inlineHeader}>
              <Text style={styles.sectionTitle}>Address details</Text>
              <Pressable
                onPress={requestCurrentLocation}
                style={styles.linkButton}
              >
                <Text style={styles.linkText}>Use current location</Text>
              </Pressable>
            </View>

            <TextInput
              placeholder="Address label"
              value={form.label}
              onChangeText={(value) =>
                setForm((current) => ({ ...current, label: value }))
              }
              style={styles.input}
            />
            <TextInput
              placeholder="Recipient name"
              value={form.recipientName}
              onChangeText={(value) =>
                setForm((current) => ({ ...current, recipientName: value }))
              }
              style={styles.input}
            />
            <TextInput
              placeholder="Phone number"
              keyboardType="phone-pad"
              value={form.phone}
              onChangeText={(value) =>
                setForm((current) => ({ ...current, phone: value }))
              }
              style={styles.input}
            />
            <TextInput
              placeholder="House / street"
              value={form.addressLine}
              onChangeText={(value) =>
                setForm((current) => ({ ...current, addressLine: value }))
              }
              style={styles.input}
            />
            <TextInput
              placeholder="Landmark"
              value={form.landmark}
              onChangeText={(value) =>
                setForm((current) => ({ ...current, landmark: value }))
              }
              style={styles.input}
            />
            <View style={styles.splitRow}>
              <TextInput
                placeholder="City"
                value={form.city}
                onChangeText={(value) =>
                  setForm((current) => ({ ...current, city: value }))
                }
                style={[styles.input, styles.halfInput]}
              />
              <TextInput
                placeholder="State"
                value={form.state}
                onChangeText={(value) =>
                  setForm((current) => ({ ...current, state: value }))
                }
                style={[styles.input, styles.halfInput]}
              />
            </View>
            <View style={styles.splitRow}>
              <TextInput
                placeholder="Postal code"
                value={form.postalCode}
                onChangeText={(value) =>
                  setForm((current) => ({ ...current, postalCode: value }))
                }
                style={[styles.input, styles.halfInput]}
              />
              <TextInput
                placeholder="Lat"
                value={form.latitude}
                onChangeText={(value) =>
                  setForm((current) => ({ ...current, latitude: value }))
                }
                style={[styles.input, styles.halfInput]}
                keyboardType="numeric"
              />
            </View>
            <TextInput
              placeholder="Longitude"
              value={form.longitude}
              onChangeText={(value) =>
                setForm((current) => ({ ...current, longitude: value }))
              }
              style={styles.input}
              keyboardType="numeric"
            />
            <TextInput
              placeholder="Delivery instructions"
              value={form.deliveryInstructions}
              onChangeText={(value) =>
                setForm((current) => ({
                  ...current,
                  deliveryInstructions: value,
                }))
              }
              style={styles.input}
            />
            <Pressable
              style={styles.secondaryButton}
              onPress={saveAddress}
              disabled={saving}
            >
              <Text style={styles.secondaryText}>
                {saving ? "Saving…" : "Save address"}
              </Text>
            </Pressable>
          </View>

          <Pressable
            style={[
              styles.primaryButton,
              (placing || checkout.issues.length > 0) && styles.primaryButtonDisabled,
            ]}
            onPress={placeOrder}
            disabled={placing || checkout.issues.length > 0}
          >
            <Text style={styles.primaryText}>
              {placing ? "Placing order…" : `Place order · ${rupees(checkout.total)}`}
            </Text>
          </Pressable>
        </ScrollView>
      ) : null}
    </SafeAreaView>
  );
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
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 28 },
  errorText: { color: "#B42318", textAlign: "center", marginBottom: 14, lineHeight: 21 },
  content: { padding: 20, paddingBottom: 40, gap: 16 },
  issuesBanner: {
    backgroundColor: "#FEE4E2",
    borderRadius: 12,
    padding: 14,
  },
  issueText: { color: "#B42318", fontSize: 13, lineHeight: 19 },
  summaryBox: {
    backgroundColor: "#fff",
    borderRadius: 18,
    padding: 16,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  sectionTitle: {
    color: "#241913",
    fontSize: 18,
    fontWeight: "800",
    marginBottom: 8,
  },
  muted: { color: "#6D625D", marginBottom: 8 },
  mutedSmall: { color: "#8A7267", fontSize: 12, marginTop: 10 },
  orderItemRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 8,
  },
  orderItemName: { color: "#5F5049", flex: 1, marginRight: 12 },
  summaryRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 8,
  },
  label: { color: "#5F5049" },
  value: { color: "#241913", fontWeight: "700" },
  totalRow: {
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
    borderColor: "#F0E3DC",
  },
  totalLabel: { color: "#241913", fontWeight: "800" },
  totalValue: { color: "#D83B05", fontWeight: "900" },
  card: {
    backgroundColor: "#fff",
    borderRadius: 18,
    padding: 16,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  paymentRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: "#FFF3EE",
    borderRadius: 12,
    padding: 12,
  },
  paymentRowSpaced: { marginTop: 10 },
  paymentRowDisabled: { opacity: 0.5 },
  paymentIcon: { fontSize: 22 },
  paymentTextWrap: { flex: 1 },
  paymentTitle: { color: "#241913", fontWeight: "800" },
  paymentSubtitle: { color: "#6D625D", fontSize: 12, marginTop: 2 },
  paymentCheck: { color: "#1D8E4E", fontSize: 18, fontWeight: "900" },
  addressOption: {
    borderWidth: 1,
    borderColor: "#EADDD6",
    borderRadius: 12,
    padding: 12,
    marginTop: 10,
  },
  addressOptionSelected: { borderColor: "#FF5A1F", backgroundColor: "#FFF3EE" },
  addressRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  addressLabel: { color: "#241913", fontWeight: "800", fontSize: 15 },
  addressText: { color: "#5F5049", marginTop: 4 },
  badge: {
    backgroundColor: "#FFE4D6",
    color: "#D83B05",
    fontWeight: "800",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 999,
    overflow: "hidden",
  },
  inlineHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  linkButton: { paddingHorizontal: 8, paddingVertical: 6 },
  linkText: { color: "#D83B05", fontWeight: "700" },
  input: {
    backgroundColor: "#FFF8F5",
    borderColor: "#EADDD6",
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 11,
    marginTop: 10,
    color: "#241913",
  },
  splitRow: { flexDirection: "row", gap: 8 },
  halfInput: { flex: 1 },
  secondaryButton: {
    backgroundColor: "#FFF0E8",
    borderRadius: 12,
    paddingVertical: 12,
    alignItems: "center",
    marginTop: 12,
  },
  secondaryText: { color: "#D83B05", fontWeight: "800" },
  primaryButton: {
    marginTop: 8,
    borderRadius: 12,
    backgroundColor: "#FF5A1F",
    paddingVertical: 14,
    alignItems: "center",
  },
  primaryButtonDisabled: { opacity: 0.5 },
  primaryText: { color: "#fff", fontWeight: "800" },
});
