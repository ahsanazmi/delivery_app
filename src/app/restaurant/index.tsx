import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import {
    ActivityIndicator,
    Button,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";

import { useSession } from "@/features/auth/session-context";
import {
    getRestaurantPortal,
    type RestaurantSummary,
} from "@/services/api/restaurantApi";

export default function RestaurantDashboardScreen() {
  const router = useRouter();
  const { user, accessToken, signOut } = useSession();
  const [restaurants, setRestaurants] = useState<RestaurantSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) {
      router.replace("/restaurant/login");
      return;
    }

    if (user?.role !== "RESTAURANT") {
      signOut();
      router.replace("/restaurant/login");
      return;
    }

    try {
      setLoading(true);
      const data = await getRestaurantPortal(accessToken);
      const ownedRestaurants = data.filter(
        (restaurant) => restaurant.owner_id === user.id,
      );
      setRestaurants(ownedRestaurants);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to load restaurant data",
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

  const metrics = useMemo(() => {
    const active = restaurants.filter(
      (restaurant) => restaurant.is_active,
    ).length;
    const open = restaurants.filter((restaurant) => restaurant.is_open).length;
    return { active, open };
  }, [restaurants]);

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
        <Text style={styles.title}>Restaurant dashboard</Text>
        <Button
          title="Logout"
          onPress={() => {
            signOut();
            router.replace("/restaurant/login");
          }}
        />
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <View style={styles.statsGrid}>
        <View style={styles.statCard}>
          <Text style={styles.label}>Active</Text>
          <Text style={styles.stat}>{metrics.active}</Text>
        </View>
        <View style={styles.statCard}>
          <Text style={styles.label}>Open now</Text>
          <Text style={styles.stat}>{metrics.open}</Text>
        </View>
      </View>

      <Text style={styles.sectionTitle}>Your restaurants</Text>
      {restaurants.length === 0 ? (
        <Text style={styles.empty}>No restaurant profiles found yet.</Text>
      ) : (
        restaurants.map((restaurant) => (
          <View key={restaurant.id} style={styles.card}>
            <Text style={styles.name}>{restaurant.name}</Text>
            <Text style={styles.muted}>{restaurant.address}</Text>
            <Text style={styles.muted}>Phone: {restaurant.phone}</Text>
            <Text style={styles.muted}>
              Status: {restaurant.is_open ? "Open" : "Closed"} ·{" "}
              {restaurant.is_active ? "Active" : "Inactive"}
            </Text>
            <Text style={styles.muted}>
              Delivery fee: {restaurant.delivery_fee}
            </Text>
            <Text style={styles.muted}>
              Minimum order: {restaurant.minimum_order}
            </Text>
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
  statsGrid: {
    flexDirection: "row",
    gap: 12,
  },
  statCard: {
    flex: 1,
    borderWidth: 1,
    borderColor: "#e5e7eb",
    borderRadius: 12,
    padding: 16,
    backgroundColor: "#f9fafb",
  },
  label: { fontSize: 12, color: "#6b7280" },
  stat: { marginTop: 8, fontSize: 24, fontWeight: "700" },
  sectionTitle: { fontSize: 18, fontWeight: "700" },
  card: {
    borderWidth: 1,
    borderColor: "#d1d5db",
    borderRadius: 12,
    padding: 16,
    gap: 6,
  },
  name: { fontSize: 18, fontWeight: "700" },
  muted: { color: "#4b5563" },
  empty: { color: "#4b5563" },
  error: { color: "#b91c1c" },
});
