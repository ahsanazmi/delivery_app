// Maps & Location System Phase 21 — Rider Map Foundation. Same free/
// open-source tile provider as every other map on this platform (customer-
// mobile's tracking map and address picker, business-web, admin-web) —
// CARTO's free Voyager style, kept in its own config file, separate from
// the map-rendering component, so a provider swap is a one-line env var
// change rather than a code change. See customer-mobile's own
// map-tile-config.ts / .env.example for the full terms/limits rationale.
export const DEFAULT_MAP_STYLE_URL = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json";

export const MAP_STYLE_URL = process.env.EXPO_PUBLIC_MAP_STYLE_URL?.trim() || DEFAULT_MAP_STYLE_URL;

export const MAP_ATTRIBUTION_TEXT = "© CARTO, © OpenStreetMap contributors";
