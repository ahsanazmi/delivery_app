import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";

import { MAP_ATTRIBUTION_TEXT, MAP_STYLE_URL } from "@/features/restaurant/map-tile-config";

// Maps & Location System Phase 10 — Restaurant Location Map.
// "Restaurant Profile → Location → Map → Marker. Support: View
// location, Set location, Update location." MapLibre GL JS, not Google
// Maps — the same open-source stack already used across every other
// map in this platform (Live Rider Tracking, the customer map picker),
// applied here for consistency rather than introducing a third
// different mapping approach.
//
// One component covers all three required interactions: read-only
// (view) when `editable` is false, draggable-marker + click-to-move
// (set/update) when it's true — the same view/edit split
// RestaurantProfile.tsx already has for the rest of the form.

export type RestaurantLocationMapProps = {
  latitude: number;
  longitude: number;
  editable: boolean;
  onLocationChange?: (latitude: number, longitude: number) => void;
};

export function RestaurantLocationMap({ latitude, longitude, editable, onLocationChange }: RestaurantLocationMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const onLocationChangeRef = useRef(onLocationChange);
  onLocationChangeRef.current = onLocationChange;

  // Map + marker are created once and updated imperatively afterward —
  // recreating a WebGL map on every keystroke while editing lat/lng
  // would be wasteful and would fight the user's own drag gesture.
  useEffect(() => {
    if (!containerRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE_URL,
      center: [longitude, latitude],
      zoom: 14,
      attributionControl: false,
    });
    map.addControl(new maplibregl.AttributionControl({ customAttribution: MAP_ATTRIBUTION_TEXT }));
    if (editable) {
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    }

    const marker = new maplibregl.Marker({ draggable: editable, color: "#FF5A1F" })
      .setLngLat([longitude, latitude])
      .addTo(map);

    if (editable) {
      marker.on("dragend", () => {
        const { lat, lng } = marker.getLngLat();
        onLocationChangeRef.current?.(lat, lng);
      });
      map.on("click", (event) => {
        marker.setLngLat(event.lngLat);
        onLocationChangeRef.current?.(event.lngLat.lat, event.lngLat.lng);
      });
    }

    mapRef.current = map;
    markerRef.current = marker;

    return () => {
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
    };
    // Intentionally created once per editable-mode toggle, not per
    // latitude/longitude change — see the sync effect below for that.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editable]);

  // Keeps the marker (and, if the customer is just viewing, the map
  // center) in sync with externally-changed coordinates — e.g. the
  // owner typing directly into the latitude/longitude number inputs
  // RestaurantProfile.tsx still has alongside this map, or a fresh
  // restaurant record loading in.
  useEffect(() => {
    if (!markerRef.current || !mapRef.current) return;
    const current = markerRef.current.getLngLat();
    if (Math.abs(current.lat - latitude) < 1e-9 && Math.abs(current.lng - longitude) < 1e-9) return;
    markerRef.current.setLngLat([longitude, latitude]);
    if (!editable) {
      mapRef.current.setCenter([longitude, latitude]);
    }
  }, [latitude, longitude, editable]);

  return <div ref={containerRef} style={{ width: "100%", height: 260, borderRadius: 14, overflow: "hidden" }} />;
}
