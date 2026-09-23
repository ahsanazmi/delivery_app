import { Redirect, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
    ActivityIndicator,
    Pressable,
    RefreshControl,
    ScrollView,
    StyleSheet,
    Text,
    TextInput,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { useCart } from "@/features/cart/cart-context";
import { ApiError } from "@/services/api/apiClient";
import { getAvailableCoupons, type AvailableCoupon } from "@/services/api/couponsApi";
import { rupees } from "@/utils/currency";

export default function CartScreen() {
  const { user, accessToken } = useSession();
  const {
    restaurant,
    items,
    subtotal,
    deliveryFee,
    tax,
    discount,
    total,
    itemCount,
    loading,
    error,
    removedItems,
    couponCode,
    couponMessage,
    refresh,
    updateQuantity,
    removeItem,
    clearCart,
    applyCoupon,
    removeCoupon,
  } = useCart();
  const router = useRouter();
  const [busyItemId, setBusyItemId] = useState<string | null>(null);
  const [couponInput, setCouponInput] = useState("");
  const [couponBusy, setCouponBusy] = useState(false);
  const [couponError, setCouponError] = useState<string | null>(null);
  const [availableCoupons, setAvailableCoupons] = useState<AvailableCoupon[]>([]);

  useEffect(() => {
    if (!accessToken) return;
    getAvailableCoupons(accessToken)
      .then(setAvailableCoupons)
      .catch(() => setAvailableCoupons([]));
  }, [accessToken]);

  const handleApplyCoupon = useCallback(
    async (code: string) => {
      if (!code.trim()) return;
      setCouponBusy(true);
      setCouponError(null);
      try {
        await applyCoupon(code.trim());
        setCouponInput("");
      } catch (caught) {
        setCouponError(caught instanceof ApiError ? caught.message : "Unable to apply this coupon.");
      } finally {
        setCouponBusy(false);
      }
    },
    [applyCoupon],
  );

  const handleRemoveCoupon = useCallback(async () => {
    setCouponBusy(true);
    setCouponError(null);
    try {
      await removeCoupon();
    } finally {
      setCouponBusy(false);
    }
  }, [removeCoupon]);

  const handleQuantityChange = useCallback(
    async (itemId: string, nextQuantity: number) => {
      setBusyItemId(itemId);
      try {
        await updateQuantity(itemId, nextQuantity);
      } finally {
        setBusyItemId(null);
      }
    },
    [updateQuantity],
  );

  const handleRemove = useCallback(
    async (itemId: string) => {
      setBusyItemId(itemId);
      try {
        await removeItem(itemId);
      } finally {
        setBusyItemId(null);
      }
    },
    [removeItem],
  );

  if (!user) return <Redirect href="/login" />;

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>Cart</Text>
        <Pressable
          onPress={() => clearCart()}
          style={styles.clearButton}
          disabled={items.length === 0}
        >
          <Text style={styles.clearText}>Clear</Text>
        </Pressable>
      </View>

      {removedItems.length > 0 && (
        <View style={styles.noticeBanner}>
          <Text style={styles.noticeText}>
            {removedItems.join(", ")} {removedItems.length > 1 ? "were" : "was"} removed — no
            longer available.
          </Text>
        </View>
      )}

      {couponMessage && (
        <View style={styles.noticeBanner}>
          <Text style={styles.noticeText}>{couponMessage}</Text>
        </View>
      )}

      {loading && items.length === 0 ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#FF5A1F" />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable style={styles.primaryButton} onPress={() => refresh()}>
            <Text style={styles.primaryText}>Try again</Text>
          </Pressable>
        </View>
      ) : items.length === 0 ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyEmoji}>🛒</Text>
          <Text style={styles.emptyTitle}>Your cart is empty</Text>
          <Text style={styles.emptyCopy}>
            Add a few food items to get started.
          </Text>
          <Pressable
            style={styles.primaryButton}
            onPress={() => router.push("/home")}
          >
            <Text style={styles.primaryText}>Browse restaurants</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={loading} onRefresh={refresh} tintColor="#FF5A1F" />}
        >
          {restaurant && <Text style={styles.restaurantName}>{restaurant.name}</Text>}

          {items.map((item) => (
            <View key={item.id} style={styles.itemCard}>
              <View style={styles.itemMeta}>
                <Text style={styles.itemName}>{item.product_name}</Text>
                <Text style={styles.itemPrice}>
                  {rupees(item.unit_price * item.quantity)}
                </Text>
              </View>
              <View style={styles.itemRow}>
                <View style={styles.qtyBox}>
                  <Pressable
                    disabled={busyItemId === item.id}
                    onPress={() => handleQuantityChange(item.id, item.quantity - 1)}
                    style={styles.qtyButton}
                  >
                    <Text style={styles.qtyText}>−</Text>
                  </Pressable>
                  <Text style={styles.qtyValue}>{item.quantity}</Text>
                  <Pressable
                    disabled={busyItemId === item.id}
                    onPress={() => handleQuantityChange(item.id, item.quantity + 1)}
                    style={styles.qtyButton}
                  >
                    <Text style={styles.qtyText}>+</Text>
                  </Pressable>
                </View>
                <Pressable
                  disabled={busyItemId === item.id}
                  onPress={() => handleRemove(item.id)}
                  style={styles.removeButton}
                >
                  <Text style={styles.removeText}>Remove</Text>
                </Pressable>
              </View>
            </View>
          ))}

          <View style={styles.couponBox}>
            <Text style={styles.summaryTitle}>Coupon</Text>
            {couponCode ? (
              <View style={styles.couponAppliedRow}>
                <Text style={styles.couponAppliedText}>{couponCode} applied</Text>
                <Pressable disabled={couponBusy} onPress={handleRemoveCoupon} style={styles.removeButton}>
                  <Text style={styles.removeText}>Remove</Text>
                </Pressable>
              </View>
            ) : (
              <View style={styles.couponInputRow}>
                <TextInput
                  value={couponInput}
                  onChangeText={(text) => setCouponInput(text.toUpperCase())}
                  placeholder="Enter coupon code"
                  placeholderTextColor="#9C9088"
                  autoCapitalize="characters"
                  style={styles.couponInput}
                  editable={!couponBusy}
                />
                <Pressable
                  disabled={couponBusy || !couponInput.trim()}
                  onPress={() => handleApplyCoupon(couponInput)}
                  style={[styles.applyButton, (couponBusy || !couponInput.trim()) && styles.applyButtonDisabled]}
                >
                  <Text style={styles.applyText}>{couponBusy ? "..." : "Apply"}</Text>
                </Pressable>
              </View>
            )}
            {couponError && <Text style={styles.couponErrorText}>{couponError}</Text>}
            {!couponCode && availableCoupons.length > 0 && (
              <View style={styles.availableCoupons}>
                {availableCoupons.map((coupon) => (
                  <Pressable
                    key={coupon.code}
                    disabled={couponBusy}
                    onPress={() => handleApplyCoupon(coupon.code)}
                    style={styles.availableCouponChip}
                  >
                    <Text style={styles.availableCouponCode}>{coupon.code}</Text>
                    <Text style={styles.availableCouponDetail}>
                      {coupon.discount_type === "percent"
                        ? `${coupon.discount_value}% off`
                        : `${rupees(coupon.discount_value)} off`}
                      {coupon.min_order > 0 ? ` on ${rupees(coupon.min_order)}+` : ""}
                    </Text>
                  </Pressable>
                ))}
              </View>
            )}
          </View>

          <View style={styles.summaryBox}>
            <Text style={styles.summaryTitle}>Price summary</Text>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Items ({itemCount})</Text>
              <Text style={styles.summaryValue}>{rupees(subtotal)}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Delivery fee</Text>
              <Text style={styles.summaryValue}>{rupees(deliveryFee)}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Taxes</Text>
              <Text style={styles.summaryValue}>{rupees(tax)}</Text>
            </View>
            {discount > 0 && (
              <View style={styles.summaryRow}>
                <Text style={styles.summaryLabel}>Discount</Text>
                <Text style={styles.summaryValue}>-{rupees(discount)}</Text>
              </View>
            )}
            <View style={[styles.summaryRow, styles.totalRow]}>
              <Text style={styles.totalLabel}>Total</Text>
              <Text style={styles.totalValue}>{rupees(total)}</Text>
            </View>
            <Pressable
              style={styles.primaryButton}
              onPress={() => router.push("/checkout")}
            >
              <Text style={styles.primaryText}>Proceed to checkout</Text>
            </Pressable>
          </View>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#FFF8F2" },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
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
  clearButton: {
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 10,
    backgroundColor: "#FEE4E2",
  },
  clearText: { color: "#B42318", fontWeight: "700" },
  noticeBanner: {
    marginHorizontal: 20,
    marginBottom: 8,
    backgroundColor: "#FFF3EE",
    borderRadius: 10,
    padding: 12,
  },
  noticeText: { color: "#8A4B12", fontSize: 13, lineHeight: 18 },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 28,
  },
  errorText: { color: "#B42318", textAlign: "center", marginBottom: 14, lineHeight: 21 },
  content: { padding: 20, paddingBottom: 36, gap: 16 },
  restaurantName: { color: "#241913", fontSize: 15, fontWeight: "700" },
  itemCard: {
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  itemMeta: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
  },
  itemName: { flex: 1, color: "#241913", fontWeight: "800", fontSize: 16 },
  itemPrice: { color: "#D83B05", fontWeight: "800" },
  itemRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 14,
  },
  qtyBox: {
    flexDirection: "row",
    alignItems: "center",
    borderRadius: 12,
    backgroundColor: "#FFF0E8",
    overflow: "hidden",
  },
  qtyButton: {
    width: 34,
    height: 34,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#FFE4D6",
  },
  qtyText: { color: "#241913", fontSize: 22, fontWeight: "700" },
  qtyValue: {
    minWidth: 28,
    textAlign: "center",
    color: "#241913",
    fontWeight: "800",
  },
  removeButton: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
    backgroundColor: "#FEE4E2",
  },
  removeText: { color: "#B42318", fontWeight: "700" },
  couponBox: {
    backgroundColor: "#fff",
    borderRadius: 18,
    padding: 18,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  couponInputRow: {
    flexDirection: "row",
    gap: 10,
  },
  couponInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: "#F0E3DC",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    color: "#241913",
    fontWeight: "700",
  },
  applyButton: {
    borderRadius: 10,
    backgroundColor: "#FF5A1F",
    paddingHorizontal: 18,
    justifyContent: "center",
    alignItems: "center",
  },
  applyButtonDisabled: { opacity: 0.5 },
  applyText: { color: "#fff", fontWeight: "800" },
  couponAppliedRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#FFF3EE",
    borderRadius: 10,
    padding: 12,
  },
  couponAppliedText: { color: "#8A4B12", fontWeight: "800" },
  couponErrorText: { color: "#B42318", marginTop: 8, fontSize: 13 },
  availableCoupons: { marginTop: 12, gap: 8 },
  availableCouponChip: {
    borderWidth: 1,
    borderColor: "#F0E3DC",
    borderRadius: 10,
    padding: 10,
  },
  availableCouponCode: { color: "#241913", fontWeight: "800" },
  availableCouponDetail: { color: "#6D625D", fontSize: 12, marginTop: 2 },
  summaryBox: {
    backgroundColor: "#fff",
    borderRadius: 18,
    padding: 18,
    borderWidth: 1,
    borderColor: "#F0E3DC",
    marginTop: 8,
  },
  summaryTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: "#241913",
    marginBottom: 12,
  },
  summaryRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  summaryLabel: { color: "#5F5049" },
  summaryValue: { color: "#241913", fontWeight: "700" },
  totalRow: {
    marginTop: 8,
    paddingTop: 10,
    borderTopWidth: 1,
    borderColor: "#F0E3DC",
  },
  totalLabel: { color: "#241913", fontWeight: "800" },
  totalValue: { color: "#D83B05", fontWeight: "900" },
  primaryButton: {
    marginTop: 18,
    borderRadius: 12,
    backgroundColor: "#FF5A1F",
    paddingVertical: 14,
    alignItems: "center",
  },
  primaryText: { color: "#fff", fontWeight: "800" },
  emptyState: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    padding: 28,
  },
  emptyEmoji: { fontSize: 54 },
  emptyTitle: {
    marginTop: 18,
    fontSize: 22,
    fontWeight: "800",
    color: "#241913",
  },
  emptyCopy: {
    marginTop: 8,
    color: "#6D625D",
    textAlign: "center",
    lineHeight: 22,
  },
});
