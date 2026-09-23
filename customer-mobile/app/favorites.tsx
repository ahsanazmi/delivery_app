import { Redirect, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
    ActivityIndicator,
    Pressable,
    RefreshControl,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { RestaurantImage } from "@/features/restaurants/restaurant-list";
import { ApiError } from "@/services/api/apiClient";
import { getFavorites, removeFavorite } from "@/services/api/favoritesApi";
import type { Restaurant } from "@/types/restaurant";
import { deliveryLabel, rupees } from "@/utils/currency";

export default function FavoritesScreen() {
  const router = useRouter();
  const { user, accessToken } = useSession();
  const [favorites, setFavorites] = useState<Restaurant[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accessToken) return;
    setError(null);
    try {
      const data = await getFavorites(accessToken);
      setFavorites(data);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Unable to load favorites.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [accessToken]);

  useEffect(() => {
    load();
  }, [load]);

  function handleRefresh() {
    setRefreshing(true);
    load();
  }

  async function handleRemove(restaurantId: string) {
    if (!accessToken) return;
    setRemovingId(restaurantId);
    try {
      await removeFavorite(accessToken, restaurantId);
      setFavorites((current) => current.filter((r) => r.id !== restaurantId));
    } catch {
      // leave the list as-is; the user can retry
    } finally {
      setRemovingId(null);
    }
  }

  if (!user || !accessToken) return <Redirect href="/login" />;

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>Favorites</Text>
        <View style={styles.headerSpacer} />
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#FF5A1F" />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable style={styles.retryButton} onPress={load}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : favorites.length === 0 ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyEmoji}>🤍</Text>
          <Text style={styles.emptyTitle}>No favorites yet</Text>
          <Text style={styles.emptyCopy}>
            Tap the heart on a restaurant to save it here for quick access.
          </Text>
          <Pressable style={styles.browseButton} onPress={() => router.push("/home")}>
            <Text style={styles.browseText}>Browse restaurants</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor="#FF5A1F" />}
        >
          {favorites.map((restaurant) => (
            <Pressable
              key={restaurant.id}
              style={styles.card}
              onPress={() => router.push({ pathname: "/restaurants/[id]", params: { id: restaurant.id } })}
            >
              <RestaurantImage uri={restaurant.cover_image_url ?? restaurant.logo_url} />
              <View style={styles.cardBody}>
                <View style={styles.cardHeading}>
                  <Text numberOfLines={1} style={styles.name}>
                    {restaurant.name}
                  </Text>
                  <Text style={styles.rating}>★ {Number(restaurant.rating).toFixed(1)}</Text>
                </View>
                <Text numberOfLines={1} style={styles.address}>
                  {restaurant.address}
                </Text>
                <View style={styles.metaRow}>
                  <Text style={styles.meta}>Min. order {rupees(restaurant.minimum_order)}</Text>
                  <Text style={styles.dot}>•</Text>
                  <Text style={styles.meta}>{deliveryLabel(restaurant.delivery_fee)}</Text>
                </View>
                <Pressable
                  style={styles.removeButton}
                  disabled={removingId === restaurant.id}
                  onPress={() => handleRemove(restaurant.id)}
                >
                  <Text style={styles.removeText}>
                    {removingId === restaurant.id ? "Removing…" : "Remove from favorites"}
                  </Text>
                </Pressable>
              </View>
            </Pressable>
          ))}
        </ScrollView>
      )}
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
  retryButton: {
    backgroundColor: "#FF5A1F",
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
  retryText: { color: "#fff", fontWeight: "800" },
  content: { padding: 20, paddingBottom: 40, gap: 14 },
  card: {
    backgroundColor: "#fff",
    borderRadius: 18,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  cardBody: { padding: 14, gap: 6 },
  cardHeading: { flexDirection: "row", gap: 8, alignItems: "center" },
  name: { flex: 1, color: "#241913", fontSize: 17, fontWeight: "800" },
  rating: {
    color: "#157347",
    backgroundColor: "#E8F6EE",
    borderRadius: 7,
    overflow: "hidden",
    paddingHorizontal: 7,
    paddingVertical: 3,
    fontSize: 12,
    fontWeight: "800",
  },
  address: { color: "#81716A", fontSize: 13 },
  metaRow: { flexDirection: "row", gap: 7, alignItems: "center" },
  meta: { color: "#5F5049", fontSize: 13, fontWeight: "700" },
  dot: { color: "#B5A9A3" },
  removeButton: {
    marginTop: 6,
    alignSelf: "flex-start",
    backgroundColor: "#FEE4E2",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  removeText: { color: "#B42318", fontWeight: "700", fontSize: 12 },
  emptyState: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
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
  browseButton: {
    marginTop: 20,
    borderRadius: 12,
    backgroundColor: "#FF5A1F",
    paddingHorizontal: 20,
    paddingVertical: 13,
  },
  browseText: { color: "#fff", fontWeight: "800" },
});
