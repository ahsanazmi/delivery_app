import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import MapView, { Marker, PROVIDER_GOOGLE, type Region } from "react-native-maps";
import { SafeAreaView } from "react-native-safe-area-context";

import { useLocationPicker } from "@/features/addresses/location-picker-context";
import { usePickedPlace } from "@/features/addresses/place-search-context";
import { useSession } from "@/features/auth/session-context";
import { requestDeviceLocation } from "@/features/location/device-location";
import { reverseGeocode } from "@/services/api/locationSearchApi";

// Maps & Location System Phase 6/7/8 — Customer Map Picker + Device
// Location Permission + Reverse Geocoding. Auto-centering on the
// customer's real position is purely a convenience here, never a
// requirement — dragging the pin or tapping the map (map selection, per
// Phase 7's own "must remain available" list) works identically
// regardless of permission state, so a denied/disabled/unavailable
// result never blocks anything; it just means the map opens centered on
// the default region (Azamgarh, this platform's actual first launch
// city) with a small inline note instead of a blocking Alert — the
// customer opens this screen specifically to place a pin themselves, so
// interrupting that with a popup every time location is off would be
// the wrong trade-off.
//
// Confirming a pin (Phase 8) reverse-geocodes it on the backend — never
// a client-fabricated address for a coordinate — and hands the full
// result to AddressForm via the same place-search-context Phase 9
// already established, so a map pin now pre-fills the same address text
// fields a search result does. If reverse geocoding finds nothing or
// the service is unavailable, this falls back to Phase 6's original
// behavior (just the coordinate, via location-picker-context) — never
// blocking the confirm action itself.
const DEFAULT_REGION: Region = {
  latitude: 26.068,
  longitude: 83.1836,
  latitudeDelta: 0.05,
  longitudeDelta: 0.05,
};

export default function MapPickerScreen() {
  const router = useRouter();
  const { accessToken } = useSession();
  const { setPickedLocation } = useLocationPicker();
  const { setPickedPlace } = usePickedPlace();
  const [region, setRegion] = useState<Region>(DEFAULT_REGION);
  const [marker, setMarker] = useState({ latitude: DEFAULT_REGION.latitude, longitude: DEFAULT_REGION.longitude });
  const [usedDefaultCenter, setUsedDefaultCenter] = useState(false);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    let cancelled = false;
    requestDeviceLocation().then((result) => {
      if (cancelled) return;
      if (result.status === "granted") {
        const next = { latitude: result.latitude, longitude: result.longitude };
        setMarker(next);
        setRegion({ ...next, latitudeDelta: 0.01, longitudeDelta: 0.01 });
      } else {
        setUsedDefaultCenter(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleConfirm() {
    if (!accessToken) {
      setPickedLocation(marker);
      router.back();
      return;
    }
    setConfirming(true);
    try {
      const { result } = await reverseGeocode(accessToken, marker.latitude, marker.longitude);
      if (result) {
        setPickedPlace(result);
      } else {
        // Nothing found at this exact point (open water, unmapped area)
        // — still confirm the coordinate itself; the customer types the
        // address text by hand, same as before this phase existed.
        setPickedLocation(marker);
      }
    } catch {
      // Reverse geocoding unavailable right now — never block confirming
      // the pin over it.
      setPickedLocation(marker);
    } finally {
      setConfirming(false);
    }
    router.back();
  }

  return (
    <SafeAreaView style={styles.safeArea} edges={["top", "bottom"]}>
      <View style={styles.headerRow}>
        <Pressable onPress={() => router.back()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </Pressable>
        <Text style={styles.title}>Pick location</Text>
        <View style={styles.headerSpacer} />
      </View>

      <MapView
        style={styles.map}
        provider={Platform.OS === "android" ? PROVIDER_GOOGLE : undefined}
        initialRegion={DEFAULT_REGION}
        region={region}
        onPress={(event) => {
          const coordinate = event.nativeEvent.coordinate;
          setMarker(coordinate);
        }}
      >
        <Marker
          coordinate={marker}
          draggable
          onDragEnd={(event) => setMarker(event.nativeEvent.coordinate)}
        />
      </MapView>

      <View style={styles.footer}>
        <Text style={styles.hint}>Tap the map or drag the pin to move the delivery location.</Text>
        {usedDefaultCenter && (
          <Text style={styles.locationHint}>
            Couldn't use your current location — move the pin to your delivery spot.
          </Text>
        )}
        <Pressable style={styles.confirmButton} onPress={handleConfirm} disabled={confirming}>
          {confirming ? <ActivityIndicator color="#fff" /> : <Text style={styles.confirmLabel}>Confirm location</Text>}
        </Pressable>
      </View>
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
  map: { flex: 1 },
  footer: {
    padding: 18,
    backgroundColor: "#fff",
    borderTopWidth: 1,
    borderColor: "#F0E3DC",
  },
  hint: { color: "#6D625D", fontSize: 13, textAlign: "center", marginBottom: 12 },
  locationHint: { color: "#8A4B12", fontSize: 12, textAlign: "center", marginBottom: 12, marginTop: -8 },
  confirmButton: {
    height: 48,
    borderRadius: 12,
    backgroundColor: "#FF5A1F",
    alignItems: "center",
    justifyContent: "center",
  },
  confirmLabel: { color: "#fff", fontSize: 16, fontWeight: "800" },
});
