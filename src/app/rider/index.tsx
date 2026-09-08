import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import {
    ActivityIndicator,
    Button,
    Linking,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";

import { useSession } from "@/features/auth/session-context";
import { listRiderOrders, type RiderOrder } from "@/services/api/riderApi";

export default function RiderDashboardScreen() {
  const router = useRouter();
  const { user, accessToken, signOut } = useSession();
  const [orders, setOrders] = useState<RiderOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) {
      router.replace("/rider/login");
      return;
    }
    if (user?.role !== "RIDER") {
      signOut();
      router.replace("/rider/login");
      return;
    }

    try {
      setLoading(true);
      const data = await listRiderOrders(accessToken);
      setOrders(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to load rider orders",
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
        <Text style={styles.title}>Available Orders</Text>
        <Button
          title="Logout"
          onPress={() => {
            signOut();
            router.replace("/rider/login");
          }}
        />
      </View>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {orders.length === 0 ? (
        <Text style={styles.empty}>No delivery assignments yet.</Text>
      ) : (
        orders.map((order) => (
          <View key={order.id} style={styles.card}>
            <Text style={styles.orderNumber}>{order.order_number}</Text>
            <Text style={styles.muted}>
              {order.restaurant_name ?? "Restaurant"}
            </Text>
            <Text style={styles.muted}>Customer: {order.address_line}</Text>
            <Text style={styles.muted}>Status: {order.status}</Text>
            <Button
              title="Open delivery"
              onPress={() =>
                router.push({
                  pathname: "/rider/[id]",
                  params: { id: order.id },
                })
              }
            />
            <Button
              title="Open Google Maps"
              onPress={() => {
                const query = encodeURIComponent(
                  `${order.address_line}, ${order.city}`,
                );
                void Linking.openURL(
                  `https://www.google.com/maps/search/?api=1&query=${query}`,
                );
              }}
            />
          </View>
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, justifyContent: "center", alignItems: "center" },
  container: { padding: 20, gap: 16 },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  title: { fontSize: 26, fontWeight: "700" },
  card: {
    borderWidth: 1,
    borderColor: "#d1d5db",
    borderRadius: 12,
    padding: 16,
    gap: 8,
  },
  orderNumber: { fontSize: 18, fontWeight: "700" },
  muted: { color: "#4b5563" },
  empty: { color: "#4b5563" },
  error: { color: "#b91c1c" },
});
