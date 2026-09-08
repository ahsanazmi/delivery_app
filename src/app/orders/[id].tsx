import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { cancelOrder, getOrder, type Order } from "@/services/api/ordersApi";
import { rupees } from "@/utils/currency";

export default function OrderDetailScreen() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user, accessToken } = useSession();
  const [order, setOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user || !accessToken || !id) return;
    const loadOrder = async () => {
      try {
        const nextOrder = await getOrder(accessToken, id);
        setOrder(nextOrder);
      } finally {
        setLoading(false);
      }
    };

    loadOrder();
  }, [accessToken, id, user]);

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
      console.error(error);
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

        {order.status !== "cancelled" && order.status !== "delivered" ? (
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
  cancelButton: {
    backgroundColor: "#FEE4E2",
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: "center",
  },
  cancelText: { color: "#B42318", fontWeight: "800" },
  loading: {
    color: "#241913",
    textAlign: "center",
    marginTop: 40,
    fontWeight: "700",
  },
});
