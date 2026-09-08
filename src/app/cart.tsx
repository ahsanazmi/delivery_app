import { Redirect, useRouter } from "expo-router";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { useCart } from "@/features/cart/cart-context";
import { rupees } from "@/utils/currency";

export default function CartScreen() {
  const { user } = useSession();
  const { items, subtotal, itemCount, updateQuantity, removeItem, clearCart } =
    useCart();
  const router = useRouter();

  if (!user) return <Redirect href="/login" />;

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>Cart</Text>
        <Pressable onPress={clearCart} style={styles.clearButton}>
          <Text style={styles.clearText}>Clear</Text>
        </Pressable>
      </View>

      {items.length === 0 ? (
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
        <ScrollView contentContainerStyle={styles.content}>
          {items.map((item) => (
            <View key={item.id} style={styles.itemCard}>
              <View style={styles.itemMeta}>
                <Text style={styles.itemName}>{item.productName}</Text>
                <Text style={styles.itemPrice}>
                  {rupees(item.price * item.quantity)}
                </Text>
              </View>
              <View style={styles.itemRow}>
                <View style={styles.qtyBox}>
                  <Pressable
                    onPress={() =>
                      updateQuantity(item.productId, item.quantity - 1)
                    }
                    style={styles.qtyButton}
                  >
                    <Text style={styles.qtyText}>−</Text>
                  </Pressable>
                  <Text style={styles.qtyValue}>{item.quantity}</Text>
                  <Pressable
                    onPress={() =>
                      updateQuantity(item.productId, item.quantity + 1)
                    }
                    style={styles.qtyButton}
                  >
                    <Text style={styles.qtyText}>+</Text>
                  </Pressable>
                </View>
                <Pressable
                  onPress={() => removeItem(item.productId)}
                  style={styles.removeButton}
                >
                  <Text style={styles.removeText}>Remove</Text>
                </Pressable>
              </View>
            </View>
          ))}

          <View style={styles.summaryBox}>
            <Text style={styles.summaryTitle}>Price summary</Text>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Items ({itemCount})</Text>
              <Text style={styles.summaryValue}>{rupees(subtotal)}</Text>
            </View>
            <View style={styles.summaryRow}>
              <Text style={styles.summaryLabel}>Delivery</Text>
              <Text style={styles.summaryValue}>{rupees(0)}</Text>
            </View>
            <View style={[styles.summaryRow, styles.totalRow]}>
              <Text style={styles.totalLabel}>Total</Text>
              <Text style={styles.totalValue}>{rupees(subtotal)}</Text>
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
  content: { padding: 20, paddingBottom: 36, gap: 16 },
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
