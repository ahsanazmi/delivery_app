import { Redirect, useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import {
    ActivityIndicator,
    Alert,
    Pressable,
    RefreshControl,
    ScrollView,
    StyleSheet,
    Text,
    View,
    type TextStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { useCart } from "@/features/cart/cart-context";
import { ApiError } from "@/services/api/apiClient";
import { listOrders, reorderOrder, type Order, type OrderStatus } from "@/services/api/ordersApi";
import { rupees } from "@/utils/currency";

const PAGE_SIZE = 10;
const TERMINAL_STATUSES: OrderStatus[] = ["delivered", "cancelled", "rejected"];

export default function OrdersScreen() {
  const router = useRouter();
  const { user, accessToken } = useSession();
  const { refresh: refreshCart } = useCart();
  const [orders, setOrders] = useState<Order[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reorderingId, setReorderingId] = useState<string | null>(null);

  const loadFirstPage = useCallback(async () => {
    if (!accessToken) return;
    setError(null);
    try {
      const data = await listOrders(accessToken, { page: 1, limit: PAGE_SIZE });
      setOrders(data);
      setPage(1);
      setHasMore(data.length === PAGE_SIZE);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Unable to load orders.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [accessToken]);

  // Frontend State Synchronization (Phase 19) — refetches on every focus,
  // not just first mount, so returning to this list (e.g. after tracking
  // an order or browsing restaurants) always shows current statuses
  // instead of whatever was true when the screen first loaded.
  useFocusEffect(
    useCallback(() => {
      void loadFirstPage();
    }, [loadFirstPage]),
  );

  async function loadMore() {
    if (!accessToken || loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const nextPage = page + 1;
      const data = await listOrders(accessToken, { page: nextPage, limit: PAGE_SIZE });
      setOrders((current) => [...current, ...data]);
      setPage(nextPage);
      setHasMore(data.length === PAGE_SIZE);
    } catch {
      // keep whatever's already loaded; the user can pull to refresh instead
    } finally {
      setLoadingMore(false);
    }
  }

  function handleRefresh() {
    setRefreshing(true);
    loadFirstPage();
  }

  async function handleReorder(order: Order) {
    if (!accessToken) return;
    setReorderingId(order.id);
    try {
      const cart = await reorderOrder(accessToken, order.id);
      await refreshCart();
      if (cart.items.length === 0) {
        Alert.alert(
          "Nothing to reorder",
          "None of the items from this order are available anymore.",
        );
        return;
      }
      const skipped = cart.removed_items;
      if (skipped.length > 0) {
        Alert.alert(
          "Some items are unavailable",
          `${skipped.join(", ")} could no longer be added. The rest of your order is in your cart.`,
          [{ text: "View cart", onPress: () => router.push("/cart") }],
        );
      } else {
        router.push("/cart");
      }
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : "Unable to reorder right now.";
      Alert.alert("Reorder failed", message);
    } finally {
      setReorderingId(null);
    }
  }

  const currentOrders = useMemo(
    () => orders.filter((order) => !TERMINAL_STATUSES.includes(order.status)),
    [orders],
  );
  const pastOrders = useMemo(
    () => orders.filter((order) => TERMINAL_STATUSES.includes(order.status)),
    [orders],
  );

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

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#FF5A1F" />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable style={styles.retryButton} onPress={loadFirstPage}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
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
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor="#FF5A1F" />}
        >
          {currentOrders.length > 0 && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Current orders</Text>
              {currentOrders.map((order) => (
                <OrderCard key={order.id} order={order} onPress={() => router.push({ pathname: "/orders/[id]", params: { id: order.id } })} />
              ))}
            </View>
          )}

          {pastOrders.length > 0 && (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Past orders</Text>
              {pastOrders.map((order) => (
                <OrderCard
                  key={order.id}
                  order={order}
                  onPress={() => router.push({ pathname: "/orders/[id]", params: { id: order.id } })}
                  onReorder={() => handleReorder(order)}
                  reordering={reorderingId === order.id}
                />
              ))}
            </View>
          )}

          {hasMore && (
            <Pressable style={styles.loadMoreButton} onPress={loadMore} disabled={loadingMore}>
              <Text style={styles.loadMoreText}>{loadingMore ? "Loading…" : "Load more"}</Text>
            </Pressable>
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function OrderCard({
  order,
  onPress,
  onReorder,
  reordering,
}: {
  order: Order;
  onPress: () => void;
  onReorder?: () => void;
  reordering?: boolean;
}) {
  return (
    <Pressable style={styles.card} onPress={onPress}>
      <View style={styles.rowBetween}>
        <Text style={styles.orderNumber}>{order.order_number}</Text>
        <Text style={[styles.status, statusStyle(order.status)]}>
          {order.status.replace(/_/g, " ")}
        </Text>
      </View>
      {order.restaurant_name && (
        <Text style={styles.restaurantName}>{order.restaurant_name}</Text>
      )}
      <View style={styles.rowBetween}>
        <Text style={styles.label}>{order.items.length} items</Text>
        <Text style={styles.total}>{rupees(order.total)}</Text>
      </View>
      <Text style={styles.date}>
        {new Date(order.created_at).toLocaleDateString()}
      </Text>
      {onReorder && (
        <Pressable style={styles.reorderButton} onPress={onReorder} disabled={reordering}>
          <Text style={styles.reorderText}>{reordering ? "Reordering…" : "Reorder"}</Text>
        </Pressable>
      )}
    </Pressable>
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
    case "rejected":
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
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 28 },
  errorText: { color: "#B42318", textAlign: "center", marginBottom: 14, lineHeight: 21 },
  retryButton: {
    backgroundColor: "#FF5A1F",
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
  retryText: { color: "#fff", fontWeight: "800" },
  content: { padding: 20, paddingBottom: 40, gap: 24 },
  section: { gap: 14 },
  sectionTitle: { color: "#241913", fontSize: 19, fontWeight: "800" },
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
  restaurantName: { color: "#5F5049", fontWeight: "700", marginTop: 8 },
  status: { fontSize: 12, fontWeight: "800", textTransform: "capitalize" },
  label: { color: "#6D625D", marginTop: 10 },
  total: { color: "#D83B05", fontWeight: "800", marginTop: 10 },
  date: { color: "#8A7C74", marginTop: 8 },
  reorderButton: {
    marginTop: 12,
    alignSelf: "flex-start",
    backgroundColor: "#FFF0E8",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  reorderText: { color: "#D83B05", fontWeight: "800", fontSize: 13 },
  loadMoreButton: {
    alignSelf: "center",
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: 10,
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  loadMoreText: { color: "#D83B05", fontWeight: "800" },
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
