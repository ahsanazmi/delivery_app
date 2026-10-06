import { Camera, Map, type CameraRef, type LngLat } from "@maplibre/maplibre-react-native";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useLocationPicker } from "@/features/addresses/location-picker-context";
import { usePickedPlace } from "@/features/addresses/place-search-context";
import { useSession } from "@/features/auth/session-context";
import { requestDeviceLocation } from "@/features/location/device-location";
import { MAP_ATTRIBUTION_TEXT, MAP_STYLE_URL } from "@/features/tracking/map-tile-config";
import { reverseGeocode } from "@/services/api/locationSearchApi";

// Maps & Location System Phase 6/7/8/9 — Customer Map Picker + Device
// Location Permission + Reverse Geocoding. Rebuilt on MapLibre Native
// (matching the "no Google Maps" direction confirmed for the rest of
// this platform's location work) — this screen originally used
// react-native-maps/PROVIDER_GOOGLE and was the one map on this platform
// never migrated when that direction was set; it also turned out to
// have no Google Maps API key actually wired into app.config.ts's native
// build config at all (no android.config.googleMaps.apiKey), so it was
// already broken for a real native build, not just inconsistent.
//
// MapLibre Native's own Marker has no drag/onDragEnd support (checked
// against its real .d.ts before writing this, not guessed) — the marker
// picker pattern here is the same one Google Maps/Uber/etc. use for
// their own pickers instead: a pin fixed at the visual center of the
// screen, with the MAP itself panning underneath it. Confirming a pin
// (Phase 8) reverse-geocodes it on the backend, same as before.
const DEFAULT_CENTER: LngLat = [83.1836, 26.068];

export default function MapPickerScreen() {
  const router = useRouter();
  const { accessToken } = useSession();
  const { setPickedLocation } = useLocationPicker();
  const { setPickedPlace } = usePickedPlace();
  const cameraRef = useRef<CameraRef>(null);
  const [center, setCenter] = useState<LngLat>(DEFAULT_CENTER);
  const [usedDefaultCenter, setUsedDefaultCenter] = useState(false);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    let cancelled = false;
    requestDeviceLocation().then((result) => {
      if (cancelled) return;
      if (result.status === "granted") {
        const next: LngLat = [result.longitude, result.latitude];
        setCenter(next);
        cameraRef.current?.easeTo({ center: next, zoom: 16, duration: 0 });
      } else {
        setUsedDefaultCenter(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleConfirm() {
    const marker = { latitude: center[1], longitude: center[0] };
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

      <View style={styles.mapWrap}>
        <Map
          style={styles.map}
          mapStyle={MAP_STYLE_URL}
          onPress={(event) => cameraRef.current?.easeTo({ center: event.nativeEvent.lngLat, duration: 250 })}
          onRegionDidChange={(event) => setCenter(event.nativeEvent.center)}
        >
          <Camera ref={cameraRef} initialViewState={{ center: DEFAULT_CENTER, zoom: 14 }} />
        </Map>
        <View style={styles.centerPinWrap} pointerEvents="none">
          <View style={styles.pin} />
          <View style={styles.pinTip} />
        </View>
        <View style={styles.attributionBadge}>
          <Text style={styles.attributionText}>{MAP_ATTRIBUTION_TEXT}</Text>
        </View>
      </View>

      <View style={styles.footer}>
        <Text style={styles.hint}>Tap the map or drag it to move the delivery location.</Text>
        {usedDefaultCenter && (
          <Text style={styles.locationHint}>
            Couldn't use your current location — move the map to your delivery spot.
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
  mapWrap: { flex: 1 },
  map: { flex: 1 },
  centerPinWrap: {
    position: "absolute",
    top: "50%",
    left: "50%",
    marginLeft: -12,
    marginTop: -30,
    alignItems: "center",
  },
  pin: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: "#FF5A1F",
    borderWidth: 3,
    borderColor: "#fff",
  },
  pinTip: {
    width: 2,
    height: 12,
    backgroundColor: "#FF5A1F",
    marginTop: -2,
  },
  attributionBadge: {
    position: "absolute",
    right: 6,
    bottom: 6,
    backgroundColor: "rgba(255,255,255,0.85)",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  attributionText: { color: "#352C27", fontSize: 9 },
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
