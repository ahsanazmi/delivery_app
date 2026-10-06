import { Camera, Map, Marker, type LngLat } from "@maplibre/maplibre-react-native";
import { StyleSheet, Text, View } from "react-native";

import { MAP_ATTRIBUTION_TEXT, MAP_STYLE_URL } from "@/features/tracking/map-tile-config";

// Maps & Location System Phase 19 — Checkout Location Integration:
// "Customer checkout should show: Delivery Address, Map/Location,
// Distance where appropriate." A small, read-only pin preview of the
// selected delivery address — never editable here (picking/updating a
// location is the dedicated map picker, Phase 6) — plus the
// server-computed straight-line distance to the restaurant, when both
// have coordinates. Reuses the same MapLibre + CARTO stack already used
// for live rider tracking, not a new dependency.

export function DeliveryLocationPreview({
  latitude,
  longitude,
  distanceKm,
}: {
  latitude: number;
  longitude: number;
  distanceKm: number | null;
}) {
  const center: LngLat = [longitude, latitude];

  return (
    <View style={styles.wrapper}>
      <View style={styles.map}>
        <Map style={styles.map} mapStyle={MAP_STYLE_URL}>
          <Camera initialViewState={{ center, zoom: 14 }} />
          <Marker id="delivery-location" lngLat={center}>
            <View style={styles.pin} />
          </Marker>
        </Map>
        <View style={styles.attributionBadge}>
          <Text style={styles.attributionText}>{MAP_ATTRIBUTION_TEXT}</Text>
        </View>
      </View>
      {distanceKm != null && (
        <Text style={styles.distanceText}>≈ {distanceKm.toFixed(1)} km from the restaurant</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { marginTop: 10 },
  map: { height: 140, borderRadius: 12, overflow: "hidden" },
  pin: {
    width: 16,
    height: 16,
    borderRadius: 8,
    borderWidth: 3,
    borderColor: "#fff",
    backgroundColor: "#FF5A1F",
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
  distanceText: { color: "#6D625D", fontSize: 12, marginTop: 6 },
});
