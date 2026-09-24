import { Redirect, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import {
    ActivityIndicator,
    Pressable,
    ScrollView,
    StyleSheet,
    Text,
    TextInput,
    View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { usePickedPlace } from "@/features/addresses/place-search-context";
import { useSession } from "@/features/auth/session-context";
import { ApiError } from "@/services/api/apiClient";
import { searchPlaces, type PlaceSearchResult } from "@/services/api/locationSearchApi";

// Maps & Location System Phase 9 — Forward Geocoding / Address Search.
// "Home, Shop, Landmark, Street, Locality, Restaurant" per the phase's
// own examples — a free-text query against Photon (OSM-based), not a
// homemade geocoder. Debounced well under the backend's own shared
// throttle (Photon's public instance is limited to ~1 request/second
// across every customer, not just this one device).
const DEBOUNCE_MS = 400;
const MIN_QUERY_LENGTH = 2;

export default function AddressSearchScreen() {
  const router = useRouter();
  const { user, accessToken } = useSession();
  const { setPickedPlace } = usePickedPlace();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PlaceSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    const trimmed = query.trim();
    if (trimmed.length < MIN_QUERY_LENGTH) {
      setResults([]);
      setError(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    debounceRef.current = setTimeout(async () => {
      if (!accessToken) return;
      try {
        const { results: found } = await searchPlaces(accessToken, trimmed);
        setResults(found);
        setError(null);
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : "Unable to search right now.");
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, accessToken]);

  function selectPlace(place: PlaceSearchResult) {
    setPickedPlace(place);
    router.back();
  }

  if (!user || !accessToken) return <Redirect href="/login" />;

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>Search address</Text>
        <View style={styles.headerSpacer} />
      </View>

      <View style={styles.searchBarWrap}>
        <TextInput
          style={styles.searchInput}
          placeholder="Search for a home, shop, landmark, street…"
          value={query}
          onChangeText={setQuery}
          autoFocus
        />
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color="#FF5A1F" />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : query.trim().length < MIN_QUERY_LENGTH ? (
        <View style={styles.center}>
          <Text style={styles.hintText}>Keep typing to search…</Text>
        </View>
      ) : results.length === 0 ? (
        <View style={styles.center}>
          <Text style={styles.hintText}>No places found for "{query.trim()}".</Text>
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.content}>
          {results.map((place, index) => (
            <Pressable
              key={place.place_id ?? `${place.latitude},${place.longitude},${index}`}
              style={styles.resultCard}
              onPress={() => selectPlace(place)}
            >
              <Text style={styles.resultLabel}>{place.label}</Text>
              <Text style={styles.resultMeta}>{place.formatted_address}</Text>
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
  title: { fontSize: 20, fontWeight: "800", color: "#241913" },
  headerSpacer: { width: 40 },
  searchBarWrap: { paddingHorizontal: 20, paddingBottom: 12 },
  searchInput: {
    height: 48,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#E5D9D1",
    backgroundColor: "#fff",
    paddingHorizontal: 14,
    fontSize: 16,
    color: "#17120F",
  },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 28 },
  errorText: { color: "#B42318", textAlign: "center", lineHeight: 21 },
  hintText: { color: "#8A7267", textAlign: "center" },
  content: { padding: 20, paddingTop: 0, gap: 10 },
  resultCard: {
    backgroundColor: "#fff",
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#F0E3DC",
    padding: 14,
  },
  resultLabel: { color: "#241913", fontWeight: "800", fontSize: 15 },
  resultMeta: { color: "#6D625D", marginTop: 4, fontSize: 13 },
});
