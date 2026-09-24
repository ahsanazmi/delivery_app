// Maps & Location System Phase 10 — Restaurant Location Map. Same free/
// open-source tile provider as the mobile apps' MapLibre integrations
// (Live Rider Tracking, the customer map picker) — CARTO's free Voyager
// style, kept in its own config file, separate from the map-rendering
// component, so a provider swap is a one-line env var change rather
// than a code change (the same reasoning documented at length in
// customer-mobile/features/tracking/map-tile-config.ts, not repeated
// here — see that file for the full terms/limits rationale).
export const DEFAULT_MAP_STYLE_URL = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json";

export const MAP_STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL?.trim() || DEFAULT_MAP_STYLE_URL;

export const MAP_ATTRIBUTION_TEXT = "© CARTO, © OpenStreetMap contributors";
