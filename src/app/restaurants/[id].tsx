import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
    ActivityIndicator,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ProductCard } from "@/components/product-card";
import { useCart } from "@/features/cart/cart-context";
import { RestaurantImage } from "@/features/restaurants/restaurant-list";
import { ApiError } from "@/services/api/apiClient";
import { getRestaurant, Restaurant } from "@/services/api/restaurantsApi";
import { deliveryLabel, rupees } from "@/utils/currency";

const sampleMenu = [
  {
    id: "m1",
    name: "Masala Dosa",
    price: 120,
    imageUrl: "",
    isVeg: true,
    isAvailable: true,
  },
  {
    id: "m2",
    name: "Paneer Butter Masala",
    price: 220,
    imageUrl: "",
    isVeg: true,
    isAvailable: true,
  },
  {
    id: "m3",
    name: "Chicken Biryani",
    price: 280,
    imageUrl: "",
    isVeg: false,
    isAvailable: true,
  },
  {
    id: "m4",
    name: "Filter Coffee",
    price: 60,
    imageUrl: "",
    isVeg: true,
    isAvailable: true,
  },
];

export default function RestaurantDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { items, addItem, updateQuantity } = useCart();
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadRestaurant = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      setRestaurant(await getRestaurant(id));
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Unable to load this restaurant.",
      );
    }
  }, [id]);

  useEffect(() => {
    loadRestaurant();
  }, [loadRestaurant]);

  const cartCount = items.reduce((sum, item) => sum + item.quantity, 0);

  return (
    <SafeAreaView style={styles.safeArea} edges={["bottom"]}>
      <Stack.Screen
        options={{
          title: restaurant?.name ?? "Restaurant",
          headerStyle: { backgroundColor: "#FFF8F2" },
          headerShadowVisible: false,
          headerTintColor: "#241913",
        }}
      />
      {!restaurant && !error ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#FF5A1F" />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.error}>{error}</Text>
          <Pressable style={styles.retry} onPress={loadRestaurant}>
            <Text style={styles.retryText}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        restaurant && (
          <>
            <ScrollView contentContainerStyle={styles.content}>
              <RestaurantImage
                uri={restaurant.cover_image_url ?? restaurant.logo_url}
                large
              />
              <View style={styles.body}>
                <View style={styles.heading}>
                  <View style={styles.titleWrap}>
                    <Text style={styles.name}>{restaurant.name}</Text>
                    <Text style={styles.address}>{restaurant.address}</Text>
                  </View>
                  <Text style={styles.rating}>
                    ★ {Number(restaurant.average_rating).toFixed(1)}
                  </Text>
                </View>

                {restaurant.description && (
                  <Text style={styles.description}>
                    {restaurant.description}
                  </Text>
                )}

                <View style={styles.infoRow}>
                  <Info
                    label="Minimum order"
                    value={rupees(restaurant.minimum_order)}
                  />
                  <Info
                    label="Delivery"
                    value={deliveryLabel(restaurant.delivery_fee)}
                  />
                </View>

                <View style={styles.openBadge}>
                  <Text style={styles.openText}>
                    {restaurant.is_open ? "OPEN NOW" : "CURRENTLY CLOSED"}
                  </Text>
                </View>

                <View style={styles.sectionHeader}>
                  <Text style={styles.sectionTitle}>Popular menu</Text>
                  {cartCount > 0 && (
                    <Pressable
                      onPress={() => router.push("/cart")}
                      style={styles.cartBadge}
                    >
                      <Text style={styles.cartBadgeText}>🛒 {cartCount}</Text>
                    </Pressable>
                  )}
                </View>

                <View style={styles.menuList}>
                  {sampleMenu.map((product) => {
                    const cartQuantity =
                      items.find((entry) => entry.productId === product.id)
                        ?.quantity ?? 0;
                    return (
                      <ProductCard
                        key={product.id}
                        product={product}
                        quantity={cartQuantity}
                        onAdd={() =>
                          addItem({
                            productId: product.id,
                            restaurantId: restaurant.id,
                            restaurantName: restaurant.name,
                            productName: product.name,
                            price: product.price,
                            imageUrl: product.imageUrl,
                            quantity: 1,
                          })
                        }
                        onIncrease={() =>
                          addItem({
                            productId: product.id,
                            restaurantId: restaurant.id,
                            restaurantName: restaurant.name,
                            productName: product.name,
                            price: product.price,
                            imageUrl: product.imageUrl,
                            quantity: 1,
                          })
                        }
                        onDecrease={() =>
                          updateQuantity(product.id, cartQuantity - 1)
                        }
                      />
                    );
                  })}
                </View>
              </View>
            </ScrollView>

            {cartCount > 0 && (
              <Pressable
                style={styles.checkoutBar}
                onPress={() => router.push("/cart")}
              >
                <Text style={styles.checkoutCount}>
                  {cartCount} item{cartCount > 1 ? "s" : ""}
                </Text>
                <Text style={styles.checkoutLabel}>View cart</Text>
              </Pressable>
            )}
          </>
        )
      )}
    </SafeAreaView>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <View>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={styles.infoValue}>{value}</Text>
    </View>
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
  content: { paddingBottom: 36 },
  body: { padding: 20, gap: 18 },
  heading: { flexDirection: "row", gap: 12, justifyContent: "space-between" },
  titleWrap: { flex: 1 },
  name: { color: "#241913", fontSize: 26, fontWeight: "800", lineHeight: 32 },
  address: { color: "#81716A", marginTop: 5, lineHeight: 19 },
  rating: {
    alignSelf: "flex-start",
    color: "#157347",
    backgroundColor: "#E8F6EE",
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 8,
    overflow: "hidden",
    fontSize: 13,
    fontWeight: "800",
  },
  description: { color: "#5F5049", lineHeight: 22 },
  infoRow: {
    flexDirection: "row",
    gap: 40,
    paddingVertical: 17,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: "#EADDD6",
  },
  infoLabel: { color: "#8A7C74", fontSize: 12 },
  infoValue: { color: "#241913", fontWeight: "800", marginTop: 4 },
  openBadge: {
    alignSelf: "flex-start",
    backgroundColor: "#E8F6EE",
    borderRadius: 7,
    paddingHorizontal: 9,
    paddingVertical: 6,
  },
  openText: {
    color: "#157347",
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 0.5,
  },
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  sectionTitle: { color: "#241913", fontSize: 19, fontWeight: "800" },
  cartBadge: {
    backgroundColor: "#FF5A1F",
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  cartBadgeText: { color: "#fff", fontWeight: "800" },
  menuList: { gap: 12 },
  checkoutBar: {
    position: "absolute",
    left: 16,
    right: 16,
    bottom: 18,
    backgroundColor: "#241913",
    borderRadius: 16,
    paddingHorizontal: 18,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  checkoutCount: { color: "#fff", fontWeight: "700" },
  checkoutLabel: { color: "#fff", fontWeight: "800" },
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
