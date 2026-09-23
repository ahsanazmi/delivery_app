import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
    Pressable,
    RefreshControl,
    ScrollView,
    StyleSheet,
    Text,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { EmptyState, ErrorState, SectionHeader, Skeleton } from "@/components/common/ui";
import { RestaurantCard, RestaurantImage } from "@/features/restaurants/restaurant-list";
import { useSession } from "@/features/auth/session-context";
import { useCart } from "@/features/cart/cart-context";
import { ApiError } from "@/services/api/apiClient";
import { listAddresses, type Address } from "@/services/api/addressesApi";
import { getCategories } from "@/services/api/categoriesApi";
import { getAvailableCoupons, type AvailableCoupon } from "@/services/api/couponsApi";
import { getFavorites } from "@/services/api/favoritesApi";
import { listOrders, type Order } from "@/services/api/ordersApi";
import { getRestaurants } from "@/services/api/restaurantsApi";
import type { Category, Restaurant } from "@/types/restaurant";
import { rupees } from "@/utils/currency";

const CATEGORY_EMOJI: Record<string, string> = {
  burgers: "🍔",
  pizza: "🍕",
  noodles: "🍜",
  healthy: "🥗",
  indian: "🍛",
  cafe: "☕",
  desserts: "🍰",
  wraps: "🌮",
};

function emojiForCategory(name: string): string {
  return CATEGORY_EMOJI[name.trim().toLowerCase()] ?? "🍽️";
}

const POPULAR_PAGE_SIZE = 6;
const FEATURED_LIMIT = 8;

export default function HomeScreen() {
  const { user, accessToken } = useSession();
  const router = useRouter();
  const { itemCount } = useCart();

  const [categories, setCategories] = useState<Category[]>([]);
  const [featured, setFeatured] = useState<Restaurant[]>([]);
  const [popular, setPopular] = useState<Restaurant[]>([]);
  const [coreLoading, setCoreLoading] = useState(true);
  const [coreError, setCoreError] = useState<string | null>(null);

  const [defaultAddress, setDefaultAddress] = useState<Address | null>(null);
  const [recentOrders, setRecentOrders] = useState<Order[]>([]);
  const [favorites, setFavorites] = useState<Restaurant[]>([]);
  const [offers, setOffers] = useState<AvailableCoupon[]>([]);
  const [personalizedLoading, setPersonalizedLoading] = useState(false);

  const [refreshing, setRefreshing] = useState(false);

  const userName = user?.name?.split(" ")[0] ?? "friend";

  const loadCore = useCallback(async () => {
    setCoreError(null);
    try {
      const [categoryData, featuredData, popularData] = await Promise.all([
        getCategories(),
        getRestaurants({ openOnly: true, limit: FEATURED_LIMIT }),
        getRestaurants({ limit: POPULAR_PAGE_SIZE }),
      ]);
      setCategories(categoryData);
      setFeatured(featuredData);
      setPopular(popularData);
    } catch (error) {
      setCoreError(
        error instanceof ApiError ? error.message : "Unable to load the home screen right now.",
      );
    }
  }, []);

  const loadPersonalized = useCallback(async () => {
    if (!accessToken) {
      setDefaultAddress(null);
      setRecentOrders([]);
      setFavorites([]);
      setOffers([]);
      return;
    }
    setPersonalizedLoading(true);
    const [addressesResult, ordersResult, favoritesResult, offersResult] = await Promise.allSettled([
      listAddresses(accessToken),
      listOrders(accessToken, { limit: 3 }),
      getFavorites(accessToken),
      getAvailableCoupons(accessToken),
    ]);

    if (addressesResult.status === "fulfilled") {
      const addresses = addressesResult.value;
      setDefaultAddress(addresses.find((address) => address.is_default) ?? addresses[0] ?? null);
    } else {
      setDefaultAddress(null);
    }
    setRecentOrders(ordersResult.status === "fulfilled" ? ordersResult.value : []);
    setFavorites(favoritesResult.status === "fulfilled" ? favoritesResult.value : []);
    setOffers(offersResult.status === "fulfilled" ? offersResult.value : []);
    setPersonalizedLoading(false);
  }, [accessToken]);

  const loadAll = useCallback(async () => {
    await Promise.all([loadCore(), loadPersonalized()]);
  }, [loadCore, loadPersonalized]);

  useEffect(() => {
    setCoreLoading(true);
    loadAll().finally(() => setCoreLoading(false));
  }, [loadAll]);

  function handleRefresh() {
    setRefreshing(true);
    loadAll().finally(() => setRefreshing(false));
  }

  const locationLabel = accessToken
    ? defaultAddress
      ? `${defaultAddress.label}, ${defaultAddress.city}`
      : "Add a delivery address"
    : "Sign in to set your location";

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor="#FF5A1F" />}
      >
        <View style={styles.topRow}>
          <Pressable
            style={styles.locationWrap}
            onPress={() => router.push(accessToken ? "/checkout" : "/login")}
          >
            <Text style={styles.brand}>SAY HI CHAI</Text>
            <Text style={styles.locationText}>Deliver to</Text>
            <Text style={styles.locationValue}>{locationLabel}</Text>
          </Pressable>

          <View style={styles.topRowActions}>
            <Pressable
              onPress={() => router.push("/notifications")}
              style={styles.cartButton}
            >
              <Text style={styles.cartText}>🔔</Text>
            </Pressable>

            <Pressable
              onPress={() => router.push("/favorites")}
              style={styles.cartButton}
            >
              <Text style={styles.cartText}>🤍</Text>
            </Pressable>

            <Pressable
              onPress={() => router.push("/cart")}
              style={styles.cartButton}
            >
              <Text style={styles.cartText}>🛒</Text>
              {itemCount > 0 && (
                <View style={styles.cartBadge}>
                  <Text style={styles.cartBadgeText}>{itemCount}</Text>
                </View>
              )}
            </Pressable>
          </View>
        </View>

        <View style={styles.greetingRow}>
          <View style={styles.greetingTextWrap}>
            <Text style={styles.title}>Hi, {userName} 👋</Text>
            <Text style={styles.subtitle}>
              Craving something delicious today?
            </Text>
          </View>
          {user ? (
            <Pressable
              onPress={() => router.push("/profile")}
              style={styles.avatarButton}
            >
              <Text style={styles.avatarText}>
                {user.name.charAt(0).toUpperCase()}
              </Text>
            </Pressable>
          ) : (
            <Pressable
              onPress={() => router.push("/login")}
              style={styles.avatarButton}
            >
              <Text style={styles.avatarText}>→</Text>
            </Pressable>
          )}
        </View>

        <Pressable
          style={styles.searchBar}
          onPress={() => router.push("/search")}
        >
          <Text style={styles.searchIcon}>⌕</Text>
          <Text style={styles.searchPlaceholder}>
            Search for restaurants or dishes
          </Text>
        </Pressable>

        {coreError ? (
          <View style={styles.coreErrorWrap}>
            <ErrorState message={coreError} onRetry={() => { setCoreLoading(true); loadAll().finally(() => setCoreLoading(false)); }} />
          </View>
        ) : (
          <>
            <SectionHeader title="Categories" />
            {coreLoading ? (
              <View style={styles.categoryGrid}>
                {Array.from({ length: 8 }).map((_, index) => (
                  <Skeleton key={index} style={styles.categorySkeleton} />
                ))}
              </View>
            ) : categories.length === 0 ? (
              <EmptyState compact emoji="🗂️" title="No categories available" />
            ) : (
              <View style={styles.categoryGrid}>
                {categories.map((category) => (
                  <Pressable
                    key={category.id}
                    style={styles.categoryCard}
                    onPress={() =>
                      router.push({
                        pathname: "/category/[id]",
                        params: { id: category.id, name: category.name },
                      })
                    }
                  >
                    <Text style={styles.categoryEmoji}>
                      {emojiForCategory(category.name)}
                    </Text>
                    <Text style={styles.categoryName}>{category.name}</Text>
                  </Pressable>
                ))}
              </View>
            )}

            {accessToken && (
              <>
                <SectionHeader title="Offers for you" />
                {coreLoading || personalizedLoading ? (
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.horizontalList}>
                    {Array.from({ length: 3 }).map((_, index) => (
                      <Skeleton key={index} style={styles.offerSkeleton} />
                    ))}
                  </ScrollView>
                ) : offers.length === 0 ? (
                  <EmptyState compact emoji="🏷️" title="No active offers right now" />
                ) : (
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.horizontalList}>
                    {offers.map((offer) => (
                      <Pressable
                        key={offer.code}
                        style={styles.offerCard}
                        onPress={() => router.push("/restaurants")}
                      >
                        <Text style={styles.offerCode}>{offer.code}</Text>
                        <Text style={styles.offerDetail}>
                          {offer.discount_type === "percent"
                            ? `${offer.discount_value}% off`
                            : `${rupees(offer.discount_value)} off`}
                        </Text>
                        {offer.min_order > 0 && (
                          <Text style={styles.offerMeta}>On orders above {rupees(offer.min_order)}</Text>
                        )}
                      </Pressable>
                    ))}
                  </ScrollView>
                )}
              </>
            )}

            {(coreLoading || featured.length > 0) && (
              <>
                <SectionHeader title="Featured restaurants" />
                {coreLoading ? (
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.horizontalList}>
                    {Array.from({ length: 3 }).map((_, index) => (
                      <Skeleton key={index} style={styles.featuredSkeleton} />
                    ))}
                  </ScrollView>
                ) : (
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.horizontalList}>
                    {featured.map((restaurant) => (
                      <Pressable
                        key={restaurant.id}
                        style={styles.featuredCard}
                        onPress={() => router.push({ pathname: "/restaurants/[id]", params: { id: restaurant.id } })}
                      >
                        <RestaurantImage uri={restaurant.cover_image_url ?? restaurant.logo_url} />
                        <Text style={styles.featuredName} numberOfLines={1}>{restaurant.name}</Text>
                        <Text style={styles.featuredMeta}>★ {Number(restaurant.rating).toFixed(1)}</Text>
                      </Pressable>
                    ))}
                  </ScrollView>
                )}
              </>
            )}

            {accessToken && (
              <>
                <SectionHeader title="Recent orders" actionLabel={recentOrders.length > 0 ? "See all" : undefined} onAction={() => router.push("/orders")} />
                {coreLoading || personalizedLoading ? (
                  <Skeleton style={styles.rowSkeleton} />
                ) : recentOrders.length === 0 ? (
                  <EmptyState
                    compact
                    emoji="📦"
                    title="No orders yet"
                    message="Place your first order to see it here."
                  />
                ) : (
                  recentOrders.map((order) => (
                    <Pressable
                      key={order.id}
                      style={styles.orderRow}
                      onPress={() => router.push({ pathname: "/orders/[id]", params: { id: order.id } })}
                    >
                      <View style={styles.orderRowBody}>
                        <Text style={styles.orderRowTitle} numberOfLines={1}>
                          {order.restaurant_name ?? order.order_number}
                        </Text>
                        <Text style={styles.orderRowMeta}>
                          {order.status.replace(/_/g, " ")} • {rupees(order.total)}
                        </Text>
                      </View>
                      <Text style={styles.orderRowChevron}>›</Text>
                    </Pressable>
                  ))
                )}
              </>
            )}

            {accessToken && (
              <>
                <SectionHeader title="Your favorites" actionLabel={favorites.length > 0 ? "See all" : undefined} onAction={() => router.push("/favorites")} />
                {coreLoading || personalizedLoading ? (
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.horizontalList}>
                    {Array.from({ length: 3 }).map((_, index) => (
                      <Skeleton key={index} style={styles.favoriteSkeleton} />
                    ))}
                  </ScrollView>
                ) : favorites.length === 0 ? (
                  <EmptyState compact emoji="🤍" title="Tap ♡ on a restaurant to save it here" />
                ) : (
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.horizontalList}>
                    {favorites.map((restaurant) => (
                      <Pressable
                        key={restaurant.id}
                        style={styles.favoriteCard}
                        onPress={() => router.push({ pathname: "/restaurants/[id]", params: { id: restaurant.id } })}
                      >
                        <RestaurantImage uri={restaurant.cover_image_url ?? restaurant.logo_url} />
                        <Text style={styles.featuredName} numberOfLines={1}>{restaurant.name}</Text>
                      </Pressable>
                    ))}
                  </ScrollView>
                )}
              </>
            )}

            <SectionHeader
              title="Popular near you"
              actionLabel="View all"
              onAction={() => router.push("/restaurants")}
            />

            {coreLoading ? (
              <View style={{ gap: 14 }}>
                {Array.from({ length: 3 }).map((_, index) => (
                  <View key={index} style={styles.popularSkeletonCard}>
                    <Skeleton style={styles.popularSkeletonImage} />
                    <Skeleton style={styles.skeletonLineWide} />
                    <Skeleton style={styles.skeletonLineNarrow} />
                  </View>
                ))}
              </View>
            ) : popular.length === 0 ? (
              <EmptyState
                emoji="🍽️"
                title="No restaurants are available right now"
                message="Pull down to refresh, or check back shortly."
              />
            ) : (
              popular.map((restaurant) => (
                <RestaurantCard
                  key={restaurant.id}
                  restaurant={restaurant}
                  onPress={() => router.push({ pathname: "/restaurants/[id]", params: { id: restaurant.id } })}
                />
              ))
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: "#FFF8F2",
  },
  content: {
    paddingHorizontal: 20,
    paddingBottom: 28,
    paddingTop: 12,
    maxWidth: 560,
    width: "100%",
    alignSelf: "center",
    gap: 4,
  },
  topRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: 18,
  },
  locationWrap: { flexShrink: 1 },
  brand: {
    color: "#D83B05",
    fontWeight: "900",
    fontSize: 11,
    letterSpacing: 1.5,
  },
  locationText: {
    color: "#8A7267",
    fontSize: 12,
    marginTop: 8,
  },
  locationValue: {
    color: "#241913",
    fontWeight: "700",
    marginTop: 2,
    fontSize: 14,
  },
  topRowActions: {
    flexDirection: "row",
    gap: 10,
  },
  cartButton: {
    position: "relative",
    width: 44,
    height: 44,
    borderRadius: 14,
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#F1E1D7",
    justifyContent: "center",
    alignItems: "center",
    shadowColor: "#000",
    shadowOpacity: 0.04,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
  },
  cartText: {
    fontSize: 20,
  },
  cartBadge: {
    position: "absolute",
    right: -7,
    top: -7,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: "#FF5A1F",
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 4,
  },
  cartBadgeText: {
    color: "#fff",
    fontWeight: "800",
    fontSize: 10,
  },
  greetingRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 18,
  },
  greetingTextWrap: {
    flex: 1,
    paddingRight: 12,
  },
  title: {
    color: "#241913",
    fontSize: 30,
    lineHeight: 38,
    fontWeight: "800",
  },
  subtitle: {
    color: "#81716A",
    fontSize: 15,
    marginTop: 5,
  },
  avatarButton: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: "#FDE7DD",
    justifyContent: "center",
    alignItems: "center",
  },
  avatarText: {
    color: "#D83B05",
    fontWeight: "900",
    fontSize: 17,
  },
  searchBar: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#F2E7E0",
    borderRadius: 16,
    paddingHorizontal: 14,
    minHeight: 52,
    marginBottom: 18,
  },
  searchIcon: {
    fontSize: 22,
    color: "#8A7267",
    marginRight: 8,
  },
  searchPlaceholder: {
    flex: 1,
    color: "#8A7267",
    fontSize: 15,
    paddingVertical: 12,
  },
  coreErrorWrap: { marginTop: 12 },
  categoryGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginBottom: 8,
  },
  categoryCard: {
    width: "23%",
    backgroundColor: "#fff",
    borderRadius: 18,
    paddingVertical: 16,
    marginRight: "2%",
    marginBottom: 12,
    alignItems: "center",
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  categorySkeleton: {
    width: "23%",
    height: 74,
    borderRadius: 18,
    marginRight: "2%",
    marginBottom: 12,
  },
  categoryEmoji: {
    fontSize: 26,
    marginBottom: 6,
  },
  categoryName: {
    color: "#241913",
    fontSize: 11,
    fontWeight: "700",
    textAlign: "center",
  },
  horizontalList: {
    gap: 12,
    paddingBottom: 4,
    marginBottom: 8,
  },
  offerCard: {
    backgroundColor: "#241913",
    borderRadius: 16,
    padding: 16,
    width: 170,
    justifyContent: "center",
  },
  offerSkeleton: { width: 170, height: 88, borderRadius: 16 },
  offerCode: { color: "#fff", fontWeight: "900", fontSize: 15, letterSpacing: 0.5 },
  offerDetail: { color: "#FFD9C2", fontWeight: "700", fontSize: 13, marginTop: 8 },
  offerMeta: { color: "#C8B8B0", fontSize: 11, marginTop: 6 },
  featuredCard: {
    width: 160,
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 10,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  featuredSkeleton: { width: 160, height: 150, borderRadius: 16 },
  featuredName: { color: "#241913", fontWeight: "800", fontSize: 13, marginTop: 8 },
  featuredMeta: { color: "#6B3D11", fontWeight: "700", fontSize: 12, marginTop: 4 },
  favoriteCard: {
    width: 130,
    backgroundColor: "#fff",
    borderRadius: 16,
    padding: 10,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  favoriteSkeleton: { width: 130, height: 110, borderRadius: 16 },
  rowSkeleton: { height: 64, borderRadius: 14, marginBottom: 8 },
  orderRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#fff",
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#F0E3DC",
    padding: 14,
    marginBottom: 10,
  },
  orderRowBody: { flex: 1 },
  orderRowTitle: { color: "#241913", fontWeight: "800", fontSize: 14 },
  orderRowMeta: { color: "#81716A", fontSize: 12, marginTop: 4, textTransform: "capitalize" },
  orderRowChevron: { color: "#B5A9A3", fontSize: 22, fontWeight: "700" },
  popularSkeletonCard: {
    backgroundColor: "#fff",
    borderRadius: 20,
    padding: 14,
    borderWidth: 1,
    borderColor: "#F4E7E0",
    gap: 10,
  },
  popularSkeletonImage: { height: 132, borderRadius: 14 },
  skeletonLineWide: { height: 16, width: "70%", borderRadius: 8 },
  skeletonLineNarrow: { height: 12, width: "45%", borderRadius: 8 },
});
