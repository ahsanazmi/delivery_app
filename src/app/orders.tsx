import { Redirect, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    View,
    type TextStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { listOrders, type Order } from "@/services/api/ordersApi";
import { rupees } from "@/utils/currency";

export default function OrdersScreen() {
  const router = useRouter();
  const { user, accessToken } = useSession();
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user || !accessToken) return;
    const loadOrders = async () => {
      try {
        const nextOrders = await listOrders(accessToken);
        setOrders(nextOrders);
      } finally {
        setLoading(false);
      }
    };

    loadOrders();
  }, [accessToken, user]);

  if (!user || !accessToken) return <Redirect href="/login" />;

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>Orders</Text>
        <View style={styles.headerSpacer} />
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        {loading ? (
          <Text style={styles.loadingText}>Loading orders…</Text>
        ) : orders.length === 0 ? (
          <View style={styles.emptyState}>
            <Text style={styles.emptyEmoji}>📦</Text>
            <Text style={styles.emptyTitle}>No orders yet</Text>
            <Text style={styles.emptyCopy}>
              Place a fresh order and your recent delivery history will appear
              here.
            </Text>
          </View>
        ) : (
          orders.map((order) => (
            <Pressable
              key={order.id}
              style={styles.card}
              onPress={() =>
                router.push({
                  pathname: "/orders/[id]",
                  params: { id: order.id },
                })
              }
            >
              <View style={styles.rowBetween}>
                <Text style={styles.orderNumber}>{order.order_number}</Text>
                <Text style={[styles.status, statusStyle(order.status)]}>
                  {order.status}
                </Text>
              </View>
              <View style={styles.rowBetween}>
                <Text style={styles.label}>{order.items.length} items</Text>
                <Text style={styles.total}>{rupees(order.total)}</Text>
              </View>
              <Text style={styles.address}>{order.address_line}</Text>
              <Text style={styles.date}>
                {new Date(order.created_at).toLocaleDateString()}
              </Text>
            </Pressable>
          ))
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function statusStyle(status: string): TextStyle {
  const base: TextStyle = {
    borderRadius: 999,
    overflow: "hidden",
    paddingHorizontal: 8,
    paddingVertical: 4,
    fontWeight: "700",
  };

  switch (status) {
    case "delivered":
      return { ...base, backgroundColor: "#E8F6EE", color: "#157347" };
    case "cancelled":
      return { ...base, backgroundColor: "#FEE4E2", color: "#B42318" };
    default:
      return { ...base, backgroundColor: "#FFF0E8", color: "#D83B05" };
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
  loadingText: { color: "#6D625D", textAlign: "center", marginTop: 16 },
  card: {
    backgroundColor: "#fff",
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "#F0E3DC",
    padding: 16,
  },
  rowBetween: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  orderNumber: { color: "#241913", fontWeight: "800", fontSize: 16 },
  status: { fontSize: 12, fontWeight: "800", textTransform: "capitalize" },
  label: { color: "#6D625D", marginTop: 10 },
  total: { color: "#D83B05", fontWeight: "800", marginTop: 10 },
  address: { color: "#5F5049", marginTop: 10 },
  date: { color: "#8A7C74", marginTop: 8 },
  emptyState: {
    alignItems: "center",
    justifyContent: "center",
    paddingTop: 80,
  },
  emptyEmoji: { fontSize: 48 },
  emptyTitle: {
    color: "#241913",
    fontSize: 22,
    fontWeight: "800",
    marginTop: 12,
  },
  emptyCopy: {
    color: "#6D625D",
    textAlign: "center",
    lineHeight: 22,
    marginTop: 8,
  },
});
