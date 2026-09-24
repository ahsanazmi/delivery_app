// Live Rider Location Tracking — the one place the tracking map's basemap
// provider is chosen, kept deliberately separate from RiderMap.tsx (the
// rendering component) so a provider swap is a one-line env var change,
// never a code change. See .env.example's own long comment for the full
// terms/limits rationale — short version here: CARTO's free Voyager
// style, commercial-use fair-use limit 1M tile requests/month, requires
// the attribution string below, keyless requests may be watermarked
// (get a free CARTO account before real production use).
export const DEFAULT_MAP_STYLE_URL = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json";

export const MAP_STYLE_URL = process.env.EXPO_PUBLIC_MAP_STYLE_URL?.trim() || DEFAULT_MAP_STYLE_URL;

// Required by CARTO's and OpenStreetMap's own terms regardless of which
// style URL is actually configured above — rendered as a fixed overlay
// by RiderMap.tsx, not sourced from the style JSON itself (CARTO's
// vector tile source doesn't always carry it inline).
export const MAP_ATTRIBUTION_TEXT = "© CARTO, © OpenStreetMap contributors";
