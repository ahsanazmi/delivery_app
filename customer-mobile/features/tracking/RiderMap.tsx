import { Camera, Map, Marker, type CameraRef, type LngLat } from "@maplibre/maplibre-react-native";
import { memo, useEffect, useRef } from "react";
import { StyleSheet, Text, View } from "react-native";

import { distanceKm } from "@/features/tracking/geo";
import { MAP_ATTRIBUTION_TEXT, MAP_STYLE_URL } from "@/features/tracking/map-tile-config";
import type { RiderLocationState } from "@/services/api/trackingApi";

// Live Rider Location Tracking — renders the already-live rider_location
// data (customer-mobile/features/tracking/use-order-tracking.ts's own
// WebSocket hook, unchanged by this work) as a moving marker. MapLibre
// Native chosen specifically to avoid any Google Maps dependency — see
// map-tile-config.ts for the swappable tile-provider rationale.
//
// Live Rider Tracking Phase 17/18 — also shows the restaurant, and moves
// the camera deliberately rather than always easing: a normal, small
// movement between consecutive GPS reports eases smoothly (this phase's
// own "avoid marker jumps... use interpolation"); a large jump (the
// rider's very first reported position, or a real GPS correction after a
// tunnel/signal loss) snaps instantly instead — easing smoothly across a
// jump that big would visually "fake" a path the rider never actually
// drove (this phase's own "do not fake location... do not hide major GPS
// corrections"). And the camera never moves at all in response to a
// STALE/OFFLINE position — "do not continue moving the marker when
// updates are stale."

export type LatLng = { latitude: number; longitude: number };

function toLngLat(point: LatLng): LngLat {
  return [point.longitude, point.latitude];
}

// Beyond any real per-update movement even at highway speed (12s report
// interval × ~55 m/s plausibility ceiling, see the backend's own
// RIDER_LOCATION_MAX_PLAUSIBLE_SPEED_MPS, is under 700m) — a jump past
// this is treated as a correction/first-fix, not continuous travel.
const MAJOR_JUMP_KM = 1.5;
const EASE_DURATION_MS = 800;

// Live Rider Tracking Phase 35 — Performance/Scalability. Memoized so the
// parent screen's 5s "Xs ago" refresh tick (see track/[id].tsx) — which
// re-renders the whole screen purely to update relative-time text, not
// because riderLocation/etc. actually changed — doesn't also re-run this
// component's (and MapLibre's) own render work every time; the location
// props stay referentially stable between real WebSocket/poll updates, so
// memo's default shallow comparison correctly bails out on every tick that
// isn't a genuine new position.
function RiderMapComponent({
  riderLocation,
  riderLocationState,
  restaurantLocation,
  deliveryLocation,
}: {
  riderLocation: LatLng | null;
  riderLocationState?: RiderLocationState;
  restaurantLocation?: LatLng | null;
  deliveryLocation: LatLng | null;
}) {
  const cameraRef = useRef<CameraRef>(null);
  const lastAnimatedTo = useRef<LatLng | null>(null);

  useEffect(() => {
    if (!riderLocation) return;
    // A stale/offline position is the same coordinate the camera already
    // moved to last time (nothing new actually happened) — never trigger
    // movement off of it.
    if (riderLocationState && riderLocationState !== "live") return;

    const previous = lastAnimatedTo.current;
    lastAnimatedTo.current = riderLocation;
    if (!previous) {
      // First position this map has ever shown — nothing to ease from.
      cameraRef.current?.jumpTo({ center: toLngLat(riderLocation) });
      return;
    }

    const jumpDistance = distanceKm(previous.latitude, previous.longitude, riderLocation.latitude, riderLocation.longitude);
    if (jumpDistance > MAJOR_JUMP_KM) {
      cameraRef.current?.jumpTo({ center: toLngLat(riderLocation) });
    } else {
      cameraRef.current?.easeTo({ center: toLngLat(riderLocation), duration: EASE_DURATION_MS });
    }
  }, [riderLocation?.latitude, riderLocation?.longitude, riderLocationState]);

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
        {restaurantLocation && (
          <Marker id="restaurant" lngLat={toLngLat(restaurantLocation)}>
            <View style={[styles.pin, styles.restaurantPin]} />
          </Marker>
        )}
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

export const RiderMap = memo(RiderMapComponent);

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
  restaurantPin: { backgroundColor: "#1D4ED8" },
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
