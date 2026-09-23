import { Stack, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
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

import { getCategories } from "@/services/api/categoriesApi";
import { ApiError } from "@/services/api/apiClient";
import { searchCustomer } from "@/services/api/searchApi";
import type { Category, Restaurant } from "@/types/restaurant";
import type { Product } from "@/types/product";
import { rupees } from "@/utils/currency";

const MAX_RECENT_SEARCHES = 6;
const DEBOUNCE_MS = 350;

export default function SearchScreen() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [categories, setCategories] = useState<Category[]>([]);
  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(null);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    getCategories()
      .then(setCategories)
      .catch(() => setCategories([]));
  }, []);

  const runSearch = useCallback(
    async (searchTerm: string, categoryId: string | null) => {
      if (!searchTerm.trim() && !categoryId) {
        setRestaurants([]);
        setProducts([]);
        setHasSearched(false);
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const result = await searchCustomer({
          q: searchTerm.trim() || undefined,
          categoryId: categoryId ?? undefined,
        });
        setRestaurants(result.restaurants);
        setProducts(result.products);
        setHasSearched(true);
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : "Unable to search right now.");
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      runSearch(query, selectedCategoryId);
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, selectedCategoryId, runSearch]);

  const commitRecentSearch = useCallback((term: string) => {
    const trimmed = term.trim();
    if (!trimmed) return;
    setRecentSearches((current) => {
      const next = [trimmed, ...current.filter((entry) => entry.toLowerCase() !== trimmed.toLowerCase())];
      return next.slice(0, MAX_RECENT_SEARCHES);
    });
  }, []);

  const handleSubmit = () => {
    commitRecentSearch(query);
    runSearch(query, selectedCategoryId);
  };

  const handleRecentPress = (term: string) => {
    setQuery(term);
    runSearch(term, selectedCategoryId);
  };

  const toggleCategory = (categoryId: string) => {
    setSelectedCategoryId((current) => (current === categoryId ? null : categoryId));
  };

  const showRecent = !query.trim() && !selectedCategoryId && !hasSearched;
  const showEmpty =
    !loading && !error && hasSearched && restaurants.length === 0 && products.length === 0;

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <Stack.Screen options={{ headerShown: false }} />
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <View style={styles.searchBar}>
          <Text style={styles.searchIcon}>⌕</Text>
          <TextInput
            autoFocus
            value={query}
            onChangeText={setQuery}
            onSubmitEditing={handleSubmit}
            placeholder="Search for restaurants or dishes"
            placeholderTextColor="#8A7267"
            style={styles.searchInput}
            returnKeyType="search"
          />
        </View>
      </View>

      {categories.length > 0 && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.categoryRow}
        >
          {categories.map((category) => {
            const active = category.id === selectedCategoryId;
            return (
              <Pressable
                key={category.id}
                onPress={() => toggleCategory(category.id)}
                style={[styles.categoryChip, active && styles.categoryChipActive]}
              >
                <Text style={[styles.categoryChipText, active && styles.categoryChipTextActive]}>
                  {category.name}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      )}

      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        {showRecent ? (
          <RecentSearches
            terms={recentSearches}
            onSelect={handleRecentPress}
          />
        ) : loading ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color="#FF5A1F" />
          </View>
        ) : error ? (
          <View style={styles.center}>
            <Text style={styles.error}>{error}</Text>
            <Pressable style={styles.retry} onPress={() => runSearch(query, selectedCategoryId)}>
              <Text style={styles.retryText}>Try again</Text>
            </Pressable>
          </View>
        ) : showEmpty ? (
          <View style={styles.center}>
            <Text style={styles.emptyEmoji}>🔍</Text>
            <Text style={styles.emptyTitle}>No results found</Text>
            <Text style={styles.emptyCopy}>Try a different search term or category.</Text>
          </View>
        ) : (
          <>
            {restaurants.length > 0 && (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Restaurants</Text>
                {restaurants.map((restaurant) => (
                  <Pressable
                    key={restaurant.id}
                    style={styles.resultRow}
                    onPress={() => {
                      commitRecentSearch(query);
                      router.push({ pathname: "/restaurants/[id]", params: { id: restaurant.id } });
                    }}
                  >
                    {restaurant.cover_image_url ? (
                      <Image source={{ uri: restaurant.cover_image_url }} style={styles.resultImage} />
                    ) : (
                      <View style={[styles.resultImage, styles.resultImageFallback]}>
                        <Text>🍽️</Text>
                      </View>
                    )}
                    <View style={styles.resultBody}>
                      <Text style={styles.resultTitle}>{restaurant.name}</Text>
                      <Text style={styles.resultMeta} numberOfLines={1}>
                        {restaurant.address}
                      </Text>
                    </View>
                  </Pressable>
                ))}
              </View>
            )}

            {products.length > 0 && (
              <View style={styles.section}>
                <Text style={styles.sectionTitle}>Dishes</Text>
                {products.map((product) => (
                  <Pressable
                    key={product.id}
                    style={styles.resultRow}
                    onPress={() => {
                      commitRecentSearch(query);
                      router.push({
                        pathname: "/restaurants/[id]",
                        params: { id: product.restaurant_id },
                      });
                    }}
                  >
                    {product.image_url ? (
                      <Image source={{ uri: product.image_url }} style={styles.resultImage} />
                    ) : (
                      <View style={[styles.resultImage, styles.resultImageFallback]}>
                        <Text>🍲</Text>
                      </View>
                    )}
                    <View style={styles.resultBody}>
                      <Text style={styles.resultTitle}>{product.name}</Text>
                      <Text style={styles.resultMeta}>{rupees(product.price)}</Text>
                    </View>
                  </Pressable>
                ))}
              </View>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function RecentSearches({
  terms,
  onSelect,
}: {
  terms: string[];
  onSelect: (term: string) => void;
}) {
  if (terms.length === 0) {
    return (
      <View style={styles.center}>
        <Text style={styles.emptyEmoji}>🔍</Text>
        <Text style={styles.emptyTitle}>Search for restaurants or dishes</Text>
        <Text style={styles.emptyCopy}>Your recent searches will show up here.</Text>
      </View>
    );
  }

  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>Recent searches</Text>
      {terms.map((term) => (
        <Pressable key={term} style={styles.recentRow} onPress={() => onSelect(term)}>
          <Text style={styles.recentIcon}>⟲</Text>
          <Text style={styles.recentText}>{term}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#FFF8F2" },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 12,
    gap: 10,
  },
  backButton: {
    width: 40,
    height: 40,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  backText: { fontSize: 20, color: "#241913" },
  searchBar: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: "#F2E7E0",
    borderRadius: 16,
    paddingHorizontal: 14,
    minHeight: 48,
  },
  searchIcon: { fontSize: 20, color: "#8A7267", marginRight: 8 },
  searchInput: { flex: 1, color: "#241913", fontSize: 15, paddingVertical: 10 },
  categoryRow: { paddingHorizontal: 16, paddingBottom: 12, gap: 10 },
  categoryChip: {
    backgroundColor: "#fff",
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 9,
    marginRight: 10,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  categoryChipActive: { backgroundColor: "#FF5A1F", borderColor: "#FF5A1F" },
  categoryChipText: { color: "#4B342E", fontWeight: "700", fontSize: 12 },
  categoryChipTextActive: { color: "#fff" },
  content: { paddingHorizontal: 20, paddingBottom: 40 },
  center: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 60,
    paddingHorizontal: 24,
  },
  emptyEmoji: { fontSize: 40, marginBottom: 10 },
  emptyTitle: { color: "#241913", fontWeight: "800", fontSize: 16, textAlign: "center" },
  emptyCopy: { color: "#81716A", marginTop: 6, textAlign: "center", lineHeight: 20 },
  error: { color: "#B42318", textAlign: "center", lineHeight: 21 },
  retry: {
    backgroundColor: "#FF5A1F",
    marginTop: 14,
    borderRadius: 10,
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
  retryText: { color: "#fff", fontWeight: "800" },
  section: { marginBottom: 22 },
  sectionTitle: { color: "#241913", fontSize: 17, fontWeight: "800", marginBottom: 12 },
  resultRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: "#fff",
    borderRadius: 14,
    padding: 10,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: "#F0E3DC",
  },
  resultImage: { width: 52, height: 52, borderRadius: 10 },
  resultImageFallback: {
    backgroundColor: "#FFE4D6",
    alignItems: "center",
    justifyContent: "center",
  },
  resultBody: { flex: 1 },
  resultTitle: { color: "#241913", fontWeight: "700", fontSize: 15 },
  resultMeta: { color: "#81716A", fontSize: 13, marginTop: 3 },
  recentRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
  },
  recentIcon: { fontSize: 15, color: "#8A7267" },
  recentText: { color: "#241913", fontSize: 14, fontWeight: "600" },
});
