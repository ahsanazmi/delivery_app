// Maps & Location System Phase 11 — Admin Location Visibility. Same free/
// open-source tile provider as every other map on this platform (business-web's
// restaurant location map, the mobile apps' MapLibre integrations) — CARTO's
// free Voyager style, kept in its own config file, separate from the
// map-rendering component, so a provider swap is a one-line env var change
// rather than a code change.
export const DEFAULT_MAP_STYLE_URL = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json";

export const MAP_STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL?.trim() || DEFAULT_MAP_STYLE_URL;

export const MAP_ATTRIBUTION_TEXT = "© CARTO, © OpenStreetMap contributors";
