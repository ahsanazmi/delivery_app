import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import MapView, { Marker, PROVIDER_GOOGLE, type Region } from "react-native-maps";
import { SafeAreaView } from "react-native-safe-area-context";

import { useLocationPicker } from "@/features/addresses/location-picker-context";

// Maps & Location System Phase 6 — Customer Map Picker.
//
// Deliberately does NOT request device location permission itself (that
// full permission-state handling — granted/denied/permanently-denied/
// GPS-disabled — is Phase 7's own explicit scope); this best-effort
// tries the same navigator.geolocation call checkout.tsx already uses
// for its own one-shot "use my location" button, and falls back to a
// fixed default center (Azamgarh — this platform's actual first launch
// city) if it's unavailable or denied, rather than blocking the picker
// entirely on a permission prompt.
const DEFAULT_REGION: Region = {
  latitude: 26.068,
  longitude: 83.1836,
  latitudeDelta: 0.05,
  longitudeDelta: 0.05,
};

export default function MapPickerScreen() {
  const router = useRouter();
  const { setPickedLocation } = useLocationPicker();
  const [region, setRegion] = useState<Region>(DEFAULT_REGION);
  const [marker, setMarker] = useState({ latitude: DEFAULT_REGION.latitude, longitude: DEFAULT_REGION.longitude });

  useEffect(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const next = { latitude: position.coords.latitude, longitude: position.coords.longitude };
        setMarker(next);
        setRegion({ ...next, latitudeDelta: 0.01, longitudeDelta: 0.01 });
      },
      () => {
        // Silently keep the default region — Phase 7 owns telling the
        // customer why, with real permission-state messaging.
      },
      { enableHighAccuracy: true, timeout: 8000 },
    );
  }, []);

  function handleConfirm() {
    setPickedLocation(marker);
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
        <Pressable style={styles.confirmButton} onPress={handleConfirm}>
          <Text style={styles.confirmLabel}>Confirm location</Text>
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
  confirmButton: {
    height: 48,
    borderRadius: 12,
    backgroundColor: "#FF5A1F",
    alignItems: "center",
    justifyContent: "center",
  },
  confirmLabel: { color: "#fff", fontSize: 16, fontWeight: "800" },
});
