import { Camera, Map, Marker, type LngLat } from "@maplibre/maplibre-react-native";
import { StyleSheet, Text, View } from "react-native";

import { MAP_ATTRIBUTION_TEXT, MAP_STYLE_URL } from "@/features/location/map-tile-config";

// Maps & Location System Phase 21 — Rider Map Foundation: "Rider should
// be able to see: Current location, Restaurant location, Customer
// delivery location, for the active delivery where authorized." Read-
// only — no drag, no click-to-move (a rider inspects locations here,
// never sets one). MapLibre Native, matching every other map already
// built on this platform.
//
// This is deliberately NOT wired to the continuous background location
// reporter this app already has (use-location-reporter.ts /
// background-location-task.ts, built earlier under different work) —
// this map's "current location" pin comes from its own one-shot,
// foreground-only fetch (device-location.ts, Phase 22), used purely for
// local display, never transmitted anywhere. "Do NOT continuously
// transmit rider GPS yet" (this phase's own instruction) is already the
// case for what THIS component does; the separate continuous reporter
// keeps running independently of whether this map is even on screen.
export type LatLng = { latitude: number; longitude: number };

function toLngLat(point: LatLng): LngLat {
  return [point.longitude, point.latitude];
}

export function DeliveryMap({
  currentLocation,
  restaurantLocation,
  customerLocation,
}: {
  currentLocation: LatLng | null;
  restaurantLocation: LatLng | null;
  customerLocation: LatLng | null;
}) {
  const initialCenter = currentLocation ?? restaurantLocation ?? customerLocation;

  if (!initialCenter) {
    return (
      <View style={[styles.map, styles.placeholder]}>
        <Text style={styles.placeholderText}>No location available yet.</Text>
      </View>
    );
  }

  return (
    <View style={styles.map}>
      <Map style={styles.map} mapStyle={MAP_STYLE_URL}>
        <Camera initialViewState={{ center: toLngLat(initialCenter), zoom: 13 }} />
        {restaurantLocation && (
          <Marker id="restaurant" lngLat={toLngLat(restaurantLocation)}>
            <View style={[styles.pin, styles.restaurantPin]} />
          </Marker>
        )}
        {customerLocation && (
          <Marker id="customer" lngLat={toLngLat(customerLocation)}>
            <View style={[styles.pin, styles.customerPin]} />
          </Marker>
        )}
        {currentLocation && (
          <Marker id="rider" lngLat={toLngLat(currentLocation)}>
            <View style={[styles.pin, styles.riderPin]} />
          </Marker>
        )}
      </Map>
      <View style={styles.legend}>
        <LegendRow color={styles.riderPin.backgroundColor} label="You" />
        <LegendRow color={styles.restaurantPin.backgroundColor} label="Restaurant" />
        <LegendRow color={styles.customerPin.backgroundColor} label="Customer" />
      </View>
      <View style={styles.attributionBadge}>
        <Text style={styles.attributionText}>{MAP_ATTRIBUTION_TEXT}</Text>
      </View>
    </View>
  );
}

function LegendRow({ color, label }: { color: string; label: string }) {
  return (
    <View style={styles.legendRow}>
      <View style={[styles.legendDot, { backgroundColor: color }]} />
      <Text style={styles.legendText}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  map: { flex: 1, minHeight: 220 },
  placeholder: {
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#F0E3DC",
  },
  placeholderText: { color: "#6D625D", fontSize: 13 },
  pin: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 3,
    borderColor: "#fff",
  },
  riderPin: { backgroundColor: "#FF5A1F" },
  restaurantPin: { backgroundColor: "#1D4ED8" },
  customerPin: { backgroundColor: "#157347" },
  legend: {
    position: "absolute",
    left: 8,
    top: 8,
    backgroundColor: "rgba(255,255,255,0.9)",
    borderRadius: 8,
    padding: 6,
    gap: 4,
  },
  legendRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  legendDot: { width: 10, height: 10, borderRadius: 5 },
  legendText: { fontSize: 11, color: "#241913" },
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
});
