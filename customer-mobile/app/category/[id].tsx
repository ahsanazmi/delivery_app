import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { RestaurantList } from "@/features/restaurants/restaurant-list";
import { ApiError } from "@/services/api/apiClient";
import { getCategory } from "@/services/api/categoriesApi";
import { getRestaurants } from "@/services/api/restaurantsApi";
import type { Category, Restaurant } from "@/types/restaurant";

export default function CategoryDetailScreen() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const router = useRouter();
  const [category, setCategory] = useState<Category | null>(null);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const [categoryData, restaurantData] = await Promise.all([
        getCategory(id),
        getRestaurants({ categoryId: id }),
      ]);
      setCategory(categoryData);
      setRestaurants(restaurantData);
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Unable to load this category.",
      );
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <SafeAreaView style={styles.safeArea} edges={["bottom"]}>
      <Stack.Screen
        options={{
          title: category?.name ?? name ?? "Category",
          headerStyle: { backgroundColor: "#FFF8F2" },
          headerShadowVisible: false,
          headerTintColor: "#241913",
        }}
      />
      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#FF5A1F" />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.error}>{error}</Text>
          <Pressable style={styles.retry} onPress={load}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <RestaurantList
          restaurants={restaurants}
          refreshing={loading}
          onRefresh={load}
          onSelect={(restaurant) =>
            router.push({
              pathname: "/restaurants/[id]",
              params: { id: restaurant.id },
            })
          }
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#FFF8F2" },
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 28,
  },
  error: { color: "#B42318", textAlign: "center", lineHeight: 21 },
  retry: {
    backgroundColor: "#FF5A1F",
    marginTop: 14,
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
  retryText: { color: "#fff", fontWeight: "800" },
});
