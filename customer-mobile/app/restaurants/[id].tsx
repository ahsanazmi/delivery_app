import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
    ActivityIndicator,
    Alert,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { ProductCard } from "@/components/product-card";
import { useSession } from "@/features/auth/session-context";
import { useCart } from "@/features/cart/cart-context";
import { RestaurantImage } from "@/features/restaurants/restaurant-list";
import { ApiError } from "@/services/api/apiClient";
import { addFavorite, getFavorites, removeFavorite } from "@/services/api/favoritesApi";
import {
    getRestaurantMenuCategories,
    getRestaurantProducts,
} from "@/services/api/productsApi";
import { getRestaurant, Restaurant } from "@/services/api/restaurantsApi";
import type { MenuCategory, Product, ProductCardData } from "@/types/product";
import { deliveryLabel, rupees } from "@/utils/currency";

function toCardData(product: Product): ProductCardData {
  return {
    id: product.id,
    name: product.name,
    price: Number(product.price),
    imageUrl: product.image_url,
    isVeg: true,
    isAvailable: product.is_available,
  };
}

export default function RestaurantDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { user, accessToken } = useSession();
  const {
    itemCount,
    restaurant: cartRestaurant,
    getQuantityForProduct,
    addItem,
    decreaseProductQuantity,
    clearCart,
  } = useCart();
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [categories, setCategories] = useState<MenuCategory[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isFavorite, setIsFavorite] = useState(false);
  const [favoriteBusy, setFavoriteBusy] = useState(false);

  const loadRestaurant = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const [restaurantData, categoryData, productData] = await Promise.all([
        getRestaurant(id),
        getRestaurantMenuCategories(id),
        getRestaurantProducts(id),
      ]);
      setRestaurant(restaurantData);
      setCategories(categoryData);
      setProducts(productData);
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

  useEffect(() => {
    if (!accessToken || !id) return;
    getFavorites(accessToken)
      .then((favorites) => setIsFavorite(favorites.some((r) => r.id === id)))
      .catch(() => undefined);
  }, [accessToken, id]);

  const toggleFavorite = useCallback(async () => {
    if (!user) {
      router.push("/login");
      return;
    }
    if (!accessToken || !id || favoriteBusy) return;
    setFavoriteBusy(true);
    const nextValue = !isFavorite;
    setIsFavorite(nextValue);
    try {
      if (nextValue) {
        await addFavorite(accessToken, id);
      } else {
        await removeFavorite(accessToken, id);
      }
    } catch {
      setIsFavorite(!nextValue);
    } finally {
      setFavoriteBusy(false);
    }
  }, [user, accessToken, id, isFavorite, favoriteBusy, router]);

  const menuSections = useMemo(() => {
    const sections: { key: string; title: string; products: Product[] }[] = [];
    for (const category of categories) {
      const categoryProducts = products.filter((p) => p.category_id === category.id);
      if (categoryProducts.length > 0) {
        sections.push({ key: category.id, title: category.name, products: categoryProducts });
      }
    }
    const uncategorized = products.filter(
      (p) => !categories.some((c) => c.id === p.category_id),
    );
    if (uncategorized.length > 0) {
      sections.push({ key: "uncategorized", title: "Menu", products: uncategorized });
    }
    return sections;
  }, [categories, products]);

  const cartCount = itemCount;

  const addToCart = useCallback(
    async (productId: string) => {
      if (!user) {
        router.push("/login");
        return;
      }
      try {
        await addItem(productId, 1);
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 409) {
          Alert.alert(
            "Start a new cart?",
            `Your cart has items from ${cartRestaurant?.name ?? "another restaurant"}. Clear it and add this item instead?`,
            [
              { text: "Cancel", style: "cancel" },
              {
                text: "Clear cart",
                style: "destructive",
                onPress: async () => {
                  await clearCart();
                  await addItem(productId, 1);
                },
              },
            ],
          );
          return;
        }
        Alert.alert(
          "Unable to add item",
          caught instanceof ApiError ? caught.message : "Please try again.",
        );
      }
    },
    [user, router, addItem, cartRestaurant, clearCart],
  );

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
                  <View style={styles.headerActions}>
                    <Text style={styles.rating}>
                      ★ {Number(restaurant.rating).toFixed(1)}
                    </Text>
                    <Pressable onPress={toggleFavorite} style={styles.favoriteButton}>
                      <Text style={styles.favoriteIcon}>{isFavorite ? "❤️" : "🤍"}</Text>
                    </Pressable>
                  </View>
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
                  <Info
                    label="Delivery time"
                    value={`${restaurant.delivery_time_minutes} min`}
                  />
                </View>

                <View
                  style={[
                    styles.openBadge,
                    !restaurant.is_open && styles.closedBadge,
                  ]}
                >
                  <Text
                    style={[
                      styles.openText,
                      !restaurant.is_open && styles.closedText,
                    ]}
                  >
                    {restaurant.is_open ? "OPEN NOW" : "CURRENTLY CLOSED"}
                  </Text>
                </View>

                <View style={styles.sectionHeader}>
                  <Text style={styles.sectionTitle}>Menu</Text>
                  {cartCount > 0 && (
                    <Pressable
                      onPress={() => router.push("/cart")}
                      style={styles.cartBadge}
                    >
                      <Text style={styles.cartBadgeText}>🛒 {cartCount}</Text>
                    </Pressable>
                  )}
                </View>

                {menuSections.length === 0 ? (
                  <Text style={styles.emptyMenu}>
                    This restaurant hasn&apos;t added its menu yet.
                  </Text>
                ) : (
                  menuSections.map((section) => (
                    <View key={section.key} style={styles.menuSection}>
                      <Text style={styles.menuSectionTitle}>{section.title}</Text>
                      <View style={styles.menuList}>
                        {section.products.map((product) => {
                          const card = toCardData(product);
                          const cartQuantity = getQuantityForProduct(product.id);
                          return (
                            <ProductCard
                              key={product.id}
                              product={card}
                              quantity={cartQuantity}
                              onAdd={() => addToCart(product.id)}
                              onIncrease={() => addToCart(product.id)}
                              onDecrease={() => decreaseProductQuantity(product.id)}
                            />
                          );
                        })}
                      </View>
                    </View>
                  ))
                )}
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
  headerActions: { flexDirection: "row", alignItems: "center", gap: 8 },
  favoriteButton: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: "#FFF3EE",
    alignItems: "center",
    justifyContent: "center",
  },
  favoriteIcon: { fontSize: 16 },
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
    gap: 32,
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
  closedBadge: {
    backgroundColor: "#FEE4E2",
  },
  openText: {
    color: "#157347",
    fontSize: 11,
    fontWeight: "900",
    letterSpacing: 0.5,
  },
  closedText: {
    color: "#B42318",
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
  emptyMenu: { color: "#81716A", lineHeight: 20 },
  menuSection: { gap: 10 },
  menuSectionTitle: { color: "#241913", fontSize: 15, fontWeight: "800" },
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
