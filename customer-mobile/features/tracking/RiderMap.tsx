import { Camera, Map, Marker, type CameraRef, type LngLat } from "@maplibre/maplibre-react-native";
import { useEffect, useRef } from "react";
import { StyleSheet, Text, View } from "react-native";

import { MAP_ATTRIBUTION_TEXT, MAP_STYLE_URL } from "@/features/tracking/map-tile-config";

// Live Rider Location Tracking — renders the already-live rider_location
// data (customer-mobile/features/tracking/use-order-tracking.ts's own
// WebSocket hook, unchanged by this work) as a moving marker. MapLibre
// Native chosen specifically to avoid any Google Maps dependency — see
// map-tile-config.ts for the swappable tile-provider rationale.

export type LatLng = { latitude: number; longitude: number };

function toLngLat(point: LatLng): LngLat {
  return [point.longitude, point.latitude];
}

export function RiderMap({
  riderLocation,
  deliveryLocation,
}: {
  riderLocation: LatLng | null;
  deliveryLocation: LatLng | null;
}) {
  const cameraRef = useRef<CameraRef>(null);

  // Re-centers (eased, not a hard jump) every time a fresh rider position
  // arrives over the socket — this is the "moving marker without
  // refreshing" requirement; no polling or manual re-render trigger
  // needed, since riderLocation itself already updates live.
  useEffect(() => {
    if (!riderLocation) return;
    cameraRef.current?.easeTo({ center: toLngLat(riderLocation), duration: 800 });
  }, [riderLocation?.latitude, riderLocation?.longitude]);

  const initialCenter = riderLocation ?? deliveryLocation;

  if (!initialCenter) {
    return (
      <View style={[styles.map, styles.placeholder]}>
        <Text style={styles.placeholderText}>Waiting for the rider's location…</Text>
      </View>
    );
  }

  return (
    <View style={styles.map}>
      <Map style={styles.map} mapStyle={MAP_STYLE_URL}>
        <Camera
          ref={cameraRef}
          initialViewState={{ center: toLngLat(initialCenter), zoom: 14 }}
        />
        {deliveryLocation && (
          <Marker id="delivery" lngLat={toLngLat(deliveryLocation)}>
            <View style={[styles.pin, styles.deliveryPin]} />
          </Marker>
        )}
        {riderLocation && (
          <Marker id="rider" lngLat={toLngLat(riderLocation)}>
            <View style={[styles.pin, styles.riderPin]} />
          </Marker>
        )}
      </Map>
      <View style={styles.attributionBadge}>
        <Text style={styles.attributionText}>{MAP_ATTRIBUTION_TEXT}</Text>
      </View>
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
  deliveryPin: { backgroundColor: "#157347" },
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
