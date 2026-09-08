import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
    ActivityIndicator,
    Alert,
    Button,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";

import { useSession } from "@/features/auth/session-context";
import {
    assignRiderToOrder,
    getAdminDashboard,
    getAdminOrders,
    getAdminRiders,
    updateAdminOrderStatus,
} from "@/services/api/adminApi";

export default function AdminDashboardScreen() {
  const router = useRouter();
  const { user, accessToken, signOut } = useSession();
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<any>(null);
  const [orders, setOrders] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) {
      router.replace("/admin/login");
      return;
    }

    if (user?.role !== "ADMIN") {
      signOut();
      router.replace("/admin/login");
      return;
    }

    try {
      setLoading(true);
      const [dashboardData, ordersData] = await Promise.all([
        getAdminDashboard(accessToken),
        getAdminOrders(accessToken),
      ]);
      setStats(dashboardData);
      setOrders(ordersData);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to load admin dashboard",
      );
    } finally {
      setLoading(false);
    }
  }, [accessToken, router, signOut, user]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  async function markDelivered(orderId: string) {
    if (!accessToken) return;
    try {
      await updateAdminOrderStatus(
        accessToken,
        orderId,
        "delivered",
        "Delivered by admin dashboard",
      );
      await load();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to update order status",
      );
    }
  }

  async function assignRider(orderId: string) {
    if (!accessToken) return;
    try {
      const riders = await getAdminRiders(accessToken);
      if (!riders.length) {
        Alert.alert("No riders available", "Create a rider account first.");
        return;
      }

      Alert.alert("Select Rider", "Choose a delivery partner", [
        ...riders.map((rider) => ({
          text: rider.name,
          onPress: async () => {
            await assignRiderToOrder(accessToken, orderId, rider.id);
            await load();
          },
        })),
        { text: "Cancel", style: "cancel" },
      ]);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to load rider list",
      );
    }
  }

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <View style={styles.headerRow}>
        <Text style={styles.title}>Admin dashboard</Text>
        <Button
          title="Logout"
          onPress={() => {
            signOut();
            router.replace("/admin/login");
          }}
        />
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <View style={styles.statsGrid}>
        <View style={styles.statCard}>
          <Text style={styles.label}>Total orders</Text>
          <Text style={styles.stat}>{stats?.total_orders ?? 0}</Text>
        </View>
        <View style={styles.statCard}>
          <Text style={styles.label}>Pending</Text>
          <Text style={styles.stat}>{stats?.pending_orders ?? 0}</Text>
        </View>
        <View style={styles.statCard}>
          <Text style={styles.label}>Customers</Text>
          <Text style={styles.stat}>{stats?.total_customers ?? 0}</Text>
        </View>
        <View style={styles.statCard}>
          <Text style={styles.label}>Restaurants</Text>
          <Text style={styles.stat}>{stats?.active_restaurants ?? 0}</Text>
        </View>
      </View>

      <Button
        title="Open rider portal"
        onPress={() => router.push("/rider/login")}
      />

      <Text style={styles.sectionTitle}>Recent orders</Text>
      {orders.length === 0 ? (
        <Text>No orders yet.</Text>
      ) : (
        orders.map((order) => (
          <View key={order.id} style={styles.orderCard}>
            <Text style={styles.orderTitle}>{order.order_number}</Text>
            <Text>{order.restaurant_name ?? "Walk-in order"}</Text>
            <Text>Status: {order.status}</Text>
            <Text>Total: {order.total}</Text>
            <Text>Customer: {order.address_line}</Text>
            <Button
              title="Assign rider"
              onPress={() => assignRider(order.id)}
            />
            <Button
              title="Mark delivered"
              onPress={() => markDelivered(order.id)}
            />
          </View>
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  centered: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
  },
  container: {
    padding: 20,
    gap: 16,
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  title: {
    fontSize: 26,
    fontWeight: "700",
  },
  statsGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 12,
  },
  statCard: {
    width: "48%",
    borderWidth: 1,
    borderColor: "#e5e7eb",
    borderRadius: 12,
    padding: 16,
    backgroundColor: "#f9fafb",
  },
  label: {
    fontSize: 12,
    color: "#6b7280",
  },
  stat: {
    marginTop: 8,
    fontSize: 26,
    fontWeight: "700",
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "700",
  },
  orderCard: {
    borderWidth: 1,
    borderColor: "#e5e7eb",
    borderRadius: 12,
    padding: 14,
    gap: 6,
  },
  orderTitle: {
    fontWeight: "700",
  },
  error: {
    color: "#b91c1c",
  },
});
