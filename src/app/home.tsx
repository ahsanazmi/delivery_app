import { useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
    ActivityIndicator,
    Image,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    TextInput,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useSession } from "@/features/auth/session-context";
import { useCart } from "@/features/cart/cart-context";
import { getRestaurants, type Restaurant } from "@/services/api/restaurantsApi";

const categories = [
  { emoji: "🍔", label: "Burgers" },
  { emoji: "🍕", label: "Pizza" },
  { emoji: "🍜", label: "Noodles" },
  { emoji: "🥗", label: "Healthy" },
  { emoji: "🍛", label: "Indian" },
  { emoji: "☕", label: "Cafe" },
  { emoji: "🍰", label: "Desserts" },
  { emoji: "🌮", label: "Wraps" },
];

const quickFilters = ["Popular", "Fast delivery", "Veg only", "Top rated"];

export default function HomeScreen() {
  const { user } = useSession();
  const router = useRouter();
  const { itemCount } = useCart();
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  const userName = user?.name?.split(" ")[0] ?? "friend";

  useEffect(() => {
    const loadRestaurants = async () => {
      try {
        const data = await getRestaurants();
        setRestaurants(data);
      } catch (error) {
        setRestaurants([]);
      } finally {
        setLoading(false);
      }
    };

    loadRestaurants();
  }, []);

  const filteredRestaurants = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return restaurants;

    return restaurants.filter(
      (restaurant) =>
        restaurant.name.toLowerCase().includes(query) ||
        (restaurant.address ?? "").toLowerCase().includes(query) ||
        (restaurant.description ?? "").toLowerCase().includes(query),
    );
  }, [restaurants, search]);

  return (
    <SafeAreaView style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.topRow}>
          <View>
            <Text style={styles.brand}>SAY HI CHAI</Text>
            <Text style={styles.locationText}>Deliver to</Text>
            <Text style={styles.locationValue}>Banjara Hills, Hyderabad</Text>
          </View>

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

        <View style={styles.searchBar}>
          <Text style={styles.searchIcon}>⌕</Text>
          <TextInput
            value={search}
            onChangeText={setSearch}
            placeholder="Search for restaurants or dishes"
            placeholderTextColor="#8A7267"
            style={styles.searchInput}
          />
        </View>

        <View style={styles.filterList}>
          {quickFilters.map((filter) => (
            <Pressable key={filter} style={styles.filterPill}>
              <Text style={styles.filterText}>{filter}</Text>
            </Pressable>
          ))}
        </View>

        <Pressable
          onPress={() => router.push("/restaurants")}
          style={styles.heroCard}
        >
          <View style={styles.heroCopyWrap}>
            <Text style={styles.heroLabel}>
              Free delivery on orders above ₹199
            </Text>
            <Text style={styles.heroTitle}>Grab the best bites nearby</Text>
          </View>
          <View style={styles.heroBadge}>
            <Text style={styles.heroBadgeText}>30% OFF</Text>
          </View>
        </Pressable>

        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Popular categories</Text>
          <Text style={styles.sectionLink}>See all</Text>
        </View>

        <View style={styles.categoryGrid}>
          {categories.map((category) => (
            <Pressable key={category.label} style={styles.categoryCard}>
              <Text style={styles.categoryEmoji}>{category.emoji}</Text>
              <Text style={styles.categoryName}>{category.label}</Text>
            </Pressable>
          ))}
        </View>

        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Popular near you</Text>
          <Pressable onPress={() => router.push("/restaurants")}>
            <Text style={styles.sectionLink}>View all</Text>
          </Pressable>
        </View>

        {loading ? (
          <View style={styles.centerBlock}>
            <ActivityIndicator size="large" color="#FF5A1F" />
          </View>
        ) : filteredRestaurants.length === 0 ? (
          <View style={styles.centerBlock}>
            <Text style={styles.emptyState}>
              No restaurants match your search.
            </Text>
          </View>
        ) : (
          filteredRestaurants.map((restaurant) => (
            <Pressable
              key={restaurant.id}
              onPress={() =>
                router.push({
                  pathname: "/restaurants/[id]",
                  params: { id: restaurant.id },
                })
              }
              style={styles.restaurantCard}
            >
              <View style={styles.restaurantImageWrap}>
                {restaurant.cover_image_url ? (
                  <Image
                    source={{ uri: restaurant.cover_image_url }}
                    style={styles.restaurantImage}
                  />
                ) : (
                  <View
                    style={[
                      styles.restaurantImage,
                      styles.restaurantPlaceholder,
                    ]}
                  >
                    <Text style={styles.restaurantPlaceholderText}>🍽️</Text>
                  </View>
                )}
                <View style={styles.restaurantTag}>
                  <Text style={styles.restaurantTagText}>Open</Text>
                </View>
              </View>

              <View style={styles.restaurantBody}>
                <View style={styles.restaurantHeader}>
                  <Text style={styles.restaurantName}>{restaurant.name}</Text>
                  <View style={styles.ratingPill}>
                    <Text style={styles.ratingText}>
                      ★ {Number(restaurant.average_rating || 4.5).toFixed(1)}
                    </Text>
                  </View>
                </View>

                <Text style={styles.restaurantMeta} numberOfLines={2}>
                  {restaurant.description || restaurant.address}
                </Text>

                <View style={styles.restaurantFooter}>
                  <Text style={styles.metaMuted}>{restaurant.address}</Text>
                  <Text style={styles.metaMuted}>
                    ₹{Number(restaurant.minimum_order || 0)} min
                  </Text>
                </View>
              </View>
            </Pressable>
          ))
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
  },
  topRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    marginBottom: 18,
  },
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
  },
  searchIcon: {
    fontSize: 22,
    color: "#8A7267",
    marginRight: 8,
  },
  searchInput: {
    flex: 1,
    color: "#241913",
    fontSize: 15,
    paddingVertical: 12,
  },
  filterList: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginTop: 18,
    marginBottom: 18,
  },
  filterPill: {
    backgroundColor: "#F9EFE9",
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 9,
    marginRight: 10,
    marginBottom: 10,
  },
  filterText: {
    color: "#4B342E",
    fontWeight: "700",
    fontSize: 12,
  },
  heroCard: {
    backgroundColor: "#FF5A1F",
    borderRadius: 22,
    padding: 20,
    minHeight: 150,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    overflow: "hidden",
    marginBottom: 18,
  },
  heroCopyWrap: {
    flex: 1,
    paddingRight: 12,
  },
  heroLabel: {
    color: "#FFE9E0",
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.4,
  },
  heroTitle: {
    color: "#fff",
    fontSize: 26,
    fontWeight: "800",
    marginTop: 8,
    lineHeight: 32,
  },
  heroBadge: {
    backgroundColor: "#fff",
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  heroBadgeText: {
    color: "#FF5A1F",
    fontWeight: "900",
    fontSize: 12,
  },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 10,
    marginBottom: 14,
  },
  sectionTitle: {
    color: "#241913",
    fontSize: 20,
    fontWeight: "800",
  },
  sectionLink: {
    color: "#D83B05",
    fontWeight: "700",
    fontSize: 13,
  },
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
  centerBlock: {
    minHeight: 120,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 28,
  },
  emptyState: {
    color: "#81716A",
    fontSize: 14,
    textAlign: "center",
  },
  restaurantCard: {
    backgroundColor: "#fff",
    borderRadius: 20,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: "#F4E7E0",
    marginTop: 14,
  },
  restaurantImageWrap: {
    position: "relative",
    height: 170,
  },
  restaurantImage: {
    width: "100%",
    height: "100%",
  },
  restaurantPlaceholder: {
    backgroundColor: "#FDE7DD",
    alignItems: "center",
    justifyContent: "center",
  },
  restaurantPlaceholderText: {
    fontSize: 42,
  },
  restaurantTag: {
    position: "absolute",
    left: 12,
    top: 12,
    backgroundColor: "#fff",
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  restaurantTagText: {
    color: "#1D8E4E",
    fontSize: 11,
    fontWeight: "800",
  },
  restaurantBody: {
    padding: 14,
  },
  restaurantHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  restaurantName: {
    color: "#241913",
    fontSize: 18,
    fontWeight: "800",
    flex: 1,
    marginRight: 12,
  },
  ratingPill: {
    backgroundColor: "#F6E7D7",
    borderRadius: 999,
    paddingHorizontal: 8,
    paddingVertical: 6,
  },
  ratingText: {
    color: "#6B3D11",
    fontWeight: "800",
    fontSize: 11,
  },
  restaurantMeta: {
    color: "#5B4F49",
    fontSize: 13,
    lineHeight: 18,
    marginTop: 8,
  },
  restaurantFooter: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 12,
  },
  metaMuted: {
    color: "#8A7267",
    fontSize: 12,
    fontWeight: "600",
  },
});
