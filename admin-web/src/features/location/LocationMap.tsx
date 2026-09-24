import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";

import { MAP_ATTRIBUTION_TEXT, MAP_STYLE_URL } from "@/features/location/map-tile-config";

// Maps & Location System Phase 11 — Admin Location Visibility. "Admin should
// be able to see: Restaurant location, Customer delivery location, Service
// area, where operationally appropriate." Admins only ever inspect a
// location here — they never set or move one (that's the restaurant owner's
// own Phase 10 map) — so this is intentionally read-only, no drag, no
// click-to-move, unlike business-web's RestaurantLocationMap.

export type LocationMapProps = {
  latitude: number;
  longitude: number;
  markerColor?: string;
};

export function LocationMap({ latitude, longitude, markerColor = "#FF5A1F" }: LocationMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE_URL,
      center: [longitude, latitude],
      zoom: 14,
      attributionControl: false,
      interactive: true,
    });
    map.addControl(new maplibregl.AttributionControl({ customAttribution: MAP_ATTRIBUTION_TEXT }));
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    const marker = new maplibregl.Marker({ draggable: false, color: markerColor }).setLngLat([longitude, latitude]).addTo(map);

    mapRef.current = map;
    markerRef.current = marker;

    return () => {
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!markerRef.current || !mapRef.current) return;
    markerRef.current.setLngLat([longitude, latitude]);
    mapRef.current.setCenter([longitude, latitude]);
  }, [latitude, longitude]);

  return <div ref={containerRef} style={{ width: "100%", height: 240, borderRadius: 14, overflow: "hidden" }} />;
}
